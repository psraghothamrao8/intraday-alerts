"""
Tests for LLM results extraction (spec 07 Task 3).
"""
import json
from pathlib import Path
import pytest
from engine.llm.schemas import ResultsExtraction, Statement, Period, FilingExtraction
from engine.llm.reader import LLMReader
from engine.data.pdf_fetch import PDFFetcher


def test_results_extraction_schema_validation():
    """Unit test for ResultsExtraction pydantic schema validation."""
    stmt = Statement(
        current_qtr=Period(revenue_ops=1000.0, net_profit=150.0),
        previous_qtr=Period(revenue_ops=900.0, net_profit=120.0),
        year_ago_qtr=Period(revenue_ops=800.0, net_profit=100.0),
    )
    extracted = ResultsExtraction(
        is_financial_results=True,
        period_end="2026-09-30",
        unit="lakhs",
        standalone=stmt,
    )
    assert extracted.standalone.current_qtr.revenue_ops == 1000.0
    assert extracted.unit == "lakhs"
    assert extracted.standalone.current_qtr.net_profit == 150.0


@pytest.mark.live_llm
@pytest.mark.asyncio
async def test_live_results_extraction():
    """
    Live LLM test running against real PDFs in tests/fixtures/pdf/
    Checks that revenue_ops and net_profit are within 0.5% of expected.
    """
    fixture_dir = Path("tests/fixtures/pdf")
    expected_path = fixture_dir / "expected.json"
    if not expected_path.exists():
        pytest.skip("tests/fixtures/pdf/expected.json does not exist yet")

    with open(expected_path, "r", encoding="utf-8") as f:
        expected_cases = json.load(f)

    reader = LLMReader()
    fetcher = PDFFetcher()

    passed_count = 0
    total_count = len(expected_cases)

    for case in expected_cases:
        pdf_path = fixture_dir / case["pdf_file"]
        if not pdf_path.exists():
            continue

        pdf_bytes = pdf_path.read_bytes()
        pages = fetcher.extract_text_pages(pdf_bytes)
        result_pages = fetcher.detect_results_pages(pages)
        text_content = "\n\n".join(pages.get(p, "") for p in result_pages) if result_pages else None

        result = await reader.extract_results(
            symbol=case.get("symbol", "TEST"),
            company_name=case.get("company_name", "Test Corp"),
            subject="Financial Results",
            text_content=text_content,
        )
        if not result:
            continue

        stmt = result.consolidated or result.standalone
        if not stmt or not stmt.current_qtr:
            continue

        rev_cur = stmt.current_qtr.revenue_ops
        rev_exp = case["expected_revenue_ops_current"]
        pat_cur = stmt.current_qtr.net_profit
        pat_exp = case["expected_net_profit_current"]

        if rev_cur is not None and rev_exp:
            rev_err = abs(rev_cur - rev_exp) / rev_exp
        else:
            rev_err = 1.0

        if pat_cur is not None and pat_exp:
            pat_err = abs(pat_cur - pat_exp) / pat_exp
        else:
            pat_err = 1.0

        if rev_err <= 0.005 and pat_err <= 0.005:
            passed_count += 1

    assert passed_count >= int(total_count * 0.9), f"Only {passed_count}/{total_count} within 0.5%"
