"""
Claude LLM reader using official anthropic SDK structured outputs.
Implements spec 01 §5 pattern for text and PDF document parsing.
"""
import asyncio
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Type, TypeVar
import anthropic
from pydantic import BaseModel

from engine.config import get_settings
from engine.llm.schemas import ResultsExtraction, FilingExtraction

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
            logger.warning("ANTHROPIC_API_KEY not configured; skipping LLM extraction.")
            return None

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


LLMReader = LlmReader
