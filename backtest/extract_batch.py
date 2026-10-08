"""
Message Batches API extractor for backtesting historical filings (spec 06 §3.1).
Processes large volumes of historical filings at 50% discount using Anthropic Batches API.
Stores structured extractions in SQLite fundamentals table and filings.extraction_json.
"""
from __future__ import annotations

import argparse
import base64
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import anthropic

from engine.config import get_settings
from engine.core.state import get_connection
from engine.llm.reader import LLMReader
from engine.llm.schemas import FilingExtraction, FinancialStatementExtraction

logger = logging.getLogger("backtest.extract_batch")


class BatchExtractor:
    """Manages creation, monitoring, and retrieval of Anthropic batch extractions."""

    def __init__(self):
        self.settings = get_settings()
        self.reader = LLMReader()
        self.client = anthropic.Anthropic(api_key=self.settings.llm.api_key or "DUMMY_KEY")

    def prepare_batch_requests(self, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Query unextracted filings from SQLite and build batch request items.
        """
        conn = get_connection()
        rows = conn.execute(
            """
            SELECT id, exchange, symbol, subject, category, subcategory, pdf_url, pdf_sha256, trigger_group
            FROM filings
            WHERE extraction_json IS NULL AND (trigger_group = 'results' OR trigger_group = 'order_buyback')
            LIMIT ?
            """,
            (limit,)
        ).fetchall()

        requests = []
        for r in rows:
            filing_id = r["id"]
            trigger = r["trigger_group"]
            sha = r["pdf_sha256"]
            pdf_path = Path(f"data/pdf/{sha}.pdf") if sha else None

            # Build user content
            if trigger == "results":
                schema_cls = FinancialStatementExtraction
                prompt_name = "results"
            elif "order" in (r["subcategory"] or "").lower():
                schema_cls = FilingExtraction
                prompt_name = "order"
            else:
                schema_cls = FilingExtraction
                prompt_name = "buyback"

            system_prompt = self.reader._load_prompt(prompt_name)
            tool_definition = {
                "name": f"record_{prompt_name}",
                "description": f"Record structured extraction for {prompt_name}",
                "input_schema": schema_cls.model_json_schema(),
            }

            content: List[Dict[str, Any]] = []
            if pdf_path and pdf_path.exists():
                try:
                    pdf_bytes = pdf_path.read_bytes()
                    b64_pdf = base64.b64encode(pdf_bytes).decode("ascii")
                    content.append({
                        "type": "document",
                        "source": {
                            "type": "base64",
                            "media_type": "application/pdf",
                            "data": b64_pdf,
                        }
                    })
                except Exception as e:
                    logger.warning(f"Could not load PDF {pdf_path}: {e}")

            text_desc = f"Exchange: {r['exchange']}\nSymbol: {r['symbol']}\nCategory: {r['category']}\nSubcategory: {r['subcategory']}\nSubject: {r['subject']}"
            content.append({"type": "text", "text": text_desc})

            req_item = {
                "custom_id": filing_id,
                "params": {
                    "model": self.settings.llm.model,
                    "max_tokens": self.settings.llm.max_tokens,
                    "system": system_prompt,
                    "tools": [tool_definition],
                    "tool_choice": {"type": "tool", "name": tool_definition["name"]},
                    "messages": [{"role": "user", "content": content}],
                }
            }
            requests.append(req_item)

        return requests

    def submit_batch(self, requests: List[Dict[str, Any]]) -> str:
        """Submit requests to Anthropic Message Batches API."""
        if not requests:
            logger.info("No requests to submit.")
            return ""

        batch = self.client.messages.batches.create(requests=requests)
        logger.info(f"Submitted batch ID: {batch.id} with {len(requests)} items.")
        return batch.id

    def check_batch_status(self, batch_id: str) -> str:
        """Check status of batch processing."""
        batch = self.client.messages.batches.retrieve(batch_id)
        logger.info(f"Batch {batch_id} status: {batch.processing_status}")
        return batch.processing_status

    def process_batch_results(self, batch_id: str) -> int:
        """Retrieve completed batch results and update SQLite tables."""
        conn = get_connection()
        count = 0

        for result in self.client.messages.batches.results(batch_id):
            filing_id = result.custom_id
            if result.result.type == "succeeded":
                message = result.result.message
                tool_use = next((b for b in message.content if b.type == "tool_use"), None)
                if tool_use:
                    extraction_data = tool_use.input
                    json_str = json.dumps(extraction_data)

                    conn.execute(
                        "UPDATE filings SET extraction_json = ?, status = 'extracted' WHERE id = ?",
                        (json_str, filing_id)
                    )
                    count += 1
            else:
                conn.execute(
                    "UPDATE filings SET status = 'extraction_error' WHERE id = ?",
                    (filing_id,)
                )

        conn.commit()
        logger.info(f"Successfully processed {count} batch extraction results.")
        return count


def main():
    parser = argparse.ArgumentParser(description="Anthropic Message Batches API extractor")
    parser.add_argument("--create", action="store_true", help="Prepare and submit a new batch")
    parser.add_argument("--limit", type=int, default=50, help="Max filings to submit in batch")
    parser.add_argument("--status", type=str, help="Check batch status by batch ID")
    parser.add_argument("--retrieve", type=str, help="Retrieve and save batch results by batch ID")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    extractor = BatchExtractor()

    if args.create:
        reqs = extractor.prepare_batch_requests(limit=args.limit)
        if reqs:
            b_id = extractor.submit_batch(reqs)
            print(f"Batch created: {b_id}")
        else:
            print("No unextracted filings found.")
    elif args.status:
        st = extractor.check_batch_status(args.status)
        print(f"Status for batch {args.status}: {st}")
    elif args.retrieve:
        c = extractor.process_batch_results(args.retrieve)
        print(f"Retrieved and saved {c} extractions.")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
