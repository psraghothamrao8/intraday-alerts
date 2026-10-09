"""
Claude LLM reader using official anthropic SDK structured outputs.
Implements spec 01 §5 pattern for text and PDF document parsing.
"""
import asyncio
import logging
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Type, TypeVar
import anthropic
from pydantic import BaseModel

from engine.config import get_settings
from engine.llm.schemas import ResultsExtraction, FilingExtraction, Period, Statement

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

PROMPTS_DIR = Path(__file__).parent / "prompts"


def get_prompt_text(name: str) -> str:
    path = PROMPTS_DIR / f"{name}.md"
    return path.read_text(encoding="utf-8") if path.exists() else ""


class LlmReader:
    """Invokes Anthropic structured outputs to extract filings data."""

    def __init__(self):
        self.settings = get_settings()

    async def extract_results(
        self,
        symbol: str,
        company_name: str,
        subject: str,
        text_content: Optional[str] = None,
        pdf_base64: Optional[str] = None
    ) -> Optional[ResultsExtraction]:
        """Extract quarterly results using ResultsExtraction schema."""
        system_prompt = get_prompt_text("results")
        user_text = f"Company: {company_name} ({symbol}). Filing subject: {subject}. Extract the results."

        return await self._call_llm(
            system_prompt=system_prompt,
            user_instruction=user_text,
            schema=ResultsExtraction,
            text_content=text_content,
            pdf_base64=pdf_base64
        )

    async def extract_filing_flash(
        self,
        symbol: str,
        company_name: str,
        kind: str,
        subject: str,
        text_content: Optional[str] = None,
        pdf_base64: Optional[str] = None
    ) -> Optional[FilingExtraction]:
        """Extract order or buyback details using FilingExtraction schema."""
        prompt_name = "buyback" if kind == "buyback" else "order"
        system_prompt = get_prompt_text(prompt_name)
        user_text = f"Company: {company_name} ({symbol}). Filing subject: {subject}. Extract announcement details."

        return await self._call_llm(
            system_prompt=system_prompt,
            user_instruction=user_text,
            schema=FilingExtraction,
            text_content=text_content,
            pdf_base64=pdf_base64
        )

    async def _call_llm(
        self,
        system_prompt: str,
        user_instruction: str,
        schema: Type[T],
        text_content: Optional[str] = None,
        pdf_base64: Optional[str] = None
    ) -> Optional[T]:
        api_key = self.settings.ANTHROPIC_API_KEY
        if not api_key:
            logger.info("[FREE MODE] ANTHROPIC_API_KEY not configured: using free heuristic text extractor.")
            return self._heuristic_extract(schema, user_instruction, text_content)

        cfg = self.settings.llm
        client = anthropic.AsyncAnthropic(api_key=api_key)

        # Build content blocks: PDF document first if present, then text
        content_blocks: List[Dict[str, Any]] = []
        if pdf_base64:
            content_blocks.append({
                "type": "document",
                "source": {
                    "type": "base64",
                    "media_type": "application/pdf",
                    "data": pdf_base64
                }
            })
        if text_content:
            content_blocks.append({"type": "text", "text": text_content})
        content_blocks.append({"type": "text", "text": user_instruction})

        kwargs: Dict[str, Any] = {
            "model": cfg.model,
            "max_tokens": 16000,
            "system": system_prompt,
            "messages": [{"role": "user", "content": content_blocks}],
            "output_format": schema,
            "timeout": cfg.timeout_sec,
        }

        # Effort parameter
        if cfg.effort:
            kwargs["output_config"] = {"effort": cfg.effort}

        # Server-side fallback for Opus / Sonnet
        if "opus" in cfg.model.lower() or "sonnet" in cfg.model.lower():
            kwargs["betas"] = ["server-side-fallback-2026-07-01"]
            kwargs["fallbacks"] = "default"

        for attempt in range(cfg.max_retries + 1):
            try:
                # Use messages.parse for structured outputs
                resp = await client.beta.messages.parse(**kwargs)
                if getattr(resp, "stop_reason", None) == "refusal":
                    logger.warning("LLM refused to process document.")
                    return None
                return resp.parsed_output
            except Exception as e:
                logger.error(f"LLM extraction attempt {attempt + 1} failed: {e}")
                if attempt < cfg.max_retries:
                    await asyncio.sleep(2.0)
                else:
                    return None
        return None

    def _heuristic_extract(
        self,
        schema: Type[T],
        user_instruction: str,
        text_content: Optional[str] = None
    ) -> Optional[T]:
        """Free rule-based regex and heuristic extractor for when no LLM API key is provided."""
        text = text_content or ""
        full = f"{user_instruction}\n{text}".lower()

        if schema == FilingExtraction:
            kind = "order" if ("order" in full or "contract" in full) else ("buyback" if ("buyback" in full or "buy back" in full) else "other")
            if kind == "order":
                m_val = re.search(r"(?:rs\.?|inr|₹|usd|eur)?\s*([\d,]+(?:\.\d+)?)\s*(crores?|cr|lakhs?|millions?|billions?)\b", full)
                val = None
                unit = "crores"
                curr = "INR"
                if "usd" in full or "$" in full:
                    curr = "USD"
                elif "eur" in full or "€" in full:
                    curr = "EUR"
                if m_val:
                    try:
                        val = float(m_val.group(1).replace(",", ""))
                        unit_str = m_val.group(2).lower()
                        if "cr" in unit_str: unit = "crores"
                        elif "lakh" in unit_str: unit = "lakhs"
                        elif "mil" in unit_str: unit = "millions"
                        elif "bil" in unit_str: unit = "billions"
                    except ValueError:
                        pass

                binding = True
                if any(w in full for w in ["mou", "memorandum of understanding", "letter of intent", "loi", "l1"]):
                    binding = False

                cust_type = "unknown"
                if any(w in full for w in ["railway", "defence", "nhai", "government", "ministry"]):
                    cust_type = "government"
                elif any(w in full for w in ["ntpc", "bhel", "ongc", "psu", "iocl", "bpcl"]):
                    cust_type = "psu"
                elif any(w in full for w in ["export", "overseas", "international", "usa", "europe"]):
                    cust_type = "export"
                elif any(w in full for w in ["private", "ltd", "corp", "inc"]):
                    cust_type = "private"

                return FilingExtraction(
                    kind="order",
                    binding=binding,
                    value=val,
                    currency=curr,
                    unit=unit,
                    customer_type=cust_type,
                    summary=user_instruction[:120]
                )  # type: ignore

            elif kind == "buyback":
                m_price = re.search(r"(?:price\s*(?:of|at)?|rs\.?|₹)\s*([\d,]+(?:\.\d+)?)\s*(?:per\s*share|/-)?", full)
                price = None
                if m_price:
                    try:
                        price = float(m_price.group(1).replace(",", ""))
                    except ValueError:
                        pass
                method = "tender"
                if "open market" in full:
                    method = "open_market"

                return FilingExtraction(
                    kind="buyback",
                    buyback_method=method,
                    buyback_price=price,
                    summary=user_instruction[:120]
                )  # type: ignore

            return FilingExtraction(kind="other", summary=user_instruction[:120])  # type: ignore

        elif schema == ResultsExtraction:
            if not any(k in full for k in ["financial results", "statement of profit", "revenue", "quarter ended", "quarterly results"]):
                return None

            m_rev = re.search(r"(?:revenue from operations|total revenue|turnover)[^\d\n]*([\d,]+(?:\.\d+)?)[^\d\n]*([\d,]+(?:\.\d+)?)[^\d\n]*([\d,]+(?:\.\d+)?)", full)
            m_pat = re.search(r"(?:net profit|profit after tax|pat)[^\d\n]*([\d,]+(?:\.\d+)?)[^\d\n]*([\d,]+(?:\.\d+)?)[^\d\n]*([\d,]+(?:\.\d+)?)", full)
            if m_rev and m_pat:
                try:
                    rev_cur = float(m_rev.group(1).replace(",", ""))
                    rev_yago = float(m_rev.group(3).replace(",", "")) if m_rev.group(3) else float(m_rev.group(2).replace(",", ""))
                    pat_cur = float(m_pat.group(1).replace(",", ""))
                    pat_yago = float(m_pat.group(3).replace(",", "")) if m_pat.group(3) else float(m_pat.group(2).replace(",", ""))
                    unit = "lakhs"
                    if "in crore" in full or "in cr" in full: unit = "crores"
                    elif "in million" in full: unit = "millions"

                    cur_p = Period(revenue_ops=rev_cur, net_profit=pat_cur)
                    yago_p = Period(revenue_ops=rev_yago, net_profit=pat_yago)
                    prev_p = Period(revenue_ops=rev_cur, net_profit=pat_cur)
                    stmt = Statement(current_qtr=cur_p, previous_qtr=prev_p, year_ago_qtr=yago_p)
                    return ResultsExtraction(
                        is_financial_results=True,
                        unit=unit,
                        standalone=stmt
                    )  # type: ignore
                except Exception:
                    pass

        return None


LLMReader = LlmReader

