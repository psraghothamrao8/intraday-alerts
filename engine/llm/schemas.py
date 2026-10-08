"""
Pydantic schemas for LLM structured outputs per spec 02 §S1.4 and §S3.3.
"""
from typing import Literal, Optional
from pydantic import BaseModel, Field


class Period(BaseModel):
    revenue_ops: Optional[float] = None          # "Revenue from operations" (NOT total income)
    other_income: Optional[float] = None
    total_income: Optional[float] = None
    total_expenses: Optional[float] = None
    finance_costs: Optional[float] = None
    depreciation: Optional[float] = None         # "Depreciation and amortisation expense"
    exceptional_items: Optional[float] = None    # gain positive, loss negative
    profit_before_tax: Optional[float] = None
    tax_expense: Optional[float] = None          # total tax (current + deferred)
    net_profit: Optional[float] = None           # profit for the period after tax, before OCI
    net_profit_owners: Optional[float] = None    # "attributable to owners of the company" (consol.)


class Statement(BaseModel):
    current_qtr: Period
    previous_qtr: Period
    year_ago_qtr: Period
    ytd_current: Optional[Period] = None         # half-year / nine-months columns, if printed
    ytd_previous: Optional[Period] = None
    last_full_year: Optional[Period] = None


class ResultsExtraction(BaseModel):
    is_financial_results: bool
    company_name: Optional[str] = None
    period_end: Optional[str] = None             # current quarter end, "YYYY-MM-DD"
    unit: Literal["rupees", "thousands", "lakhs", "millions", "crores", "unknown"] = "lakhs"
    consolidated: Optional[Statement] = None
    standalone: Optional[Statement] = None
    auditor_modified_opinion: bool = False
    going_concern_doubt: bool = False
    exceptional_item_note: Optional[str] = None


class FilingExtraction(BaseModel):
    kind: Literal["order", "buyback", "other"]
    binding: Optional[bool] = None               # True: firm order/contract. False: MoU/LoI/L1
    value: Optional[float] = None
    currency: Optional[Literal["INR", "USD", "EUR", "GBP", "AED", "other"]] = "INR"
    unit: Optional[Literal["rupees", "thousands", "lakhs", "millions", "crores", "billions"]] = "crores"
    includes_gst: Optional[bool] = None
    customer: Optional[str] = None
    customer_type: Literal["government", "psu", "private", "export", "unknown"] = "unknown"
    execution_months: Optional[float] = None
    company_share_pct: Optional[float] = None
    is_repeat_or_extension: Optional[bool] = None
    buyback_method: Optional[Literal["tender", "open_market", "unknown"]] = None
    buyback_price: Optional[float] = None        # ₹ per share
    summary: str = ""
