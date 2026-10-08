"""
Transaction costs and slippage calculations (spec 05 §9).
Calculates Zerodha intraday equity costs and liquidity-based slippage.
"""
from typing import Optional


def get_slippage_pct(adv_cr: float, is_news_recent: bool = False) -> float:
    """
    Get slippage percentage per side based on 20-day ADV in ₹ crore.
    Returns fraction (e.g., 0.0010 for 0.10%).
    """
    if adv_cr >= 50.0:
        base = 0.0005  # 0.05%
    elif adv_cr >= 10.0:
        base = 0.0010  # 0.10%
    elif adv_cr >= 3.0:
        base = 0.0020  # 0.20%
    else:
        base = 0.0040  # 0.40%

    if is_news_recent:
        base += 0.0010  # +0.10% per side during initial 5 minutes
    return base


def calculate_intraday_costs(
    buy_value: float,
    sell_value: float,
    adv_cr: float = 20.0,
    is_news_recent: bool = False
) -> float:
    """
    Calculate total round-trip intraday equity costs and slippage in ₹.
    Formula per spec 05 §9:
      brokerage = min(20, 0.0003*B) + min(20, 0.0003*S)
      stt       = 0.00025*S
      exchange  = 0.0000307*(B + S)
      sebi      = 0.000001*(B + S)
      stamp     = 0.00003*B
      gst       = 0.18*(brokerage + exchange + sebi)
      slippage  = slip(ADV_cr)*(B + S)
    """
    b = max(0.0, buy_value)
    s = max(0.0, sell_value)
    if b == 0.0 and s == 0.0:
        return 0.0

    brokerage = min(20.0, 0.0003 * b) + min(20.0, 0.0003 * s)
    stt = 0.00025 * s
    exchange = 0.0000307 * (b + s)
    sebi = 0.000001 * (b + s)
    stamp = 0.00003 * b
    gst = 0.18 * (brokerage + exchange + sebi)

    slip_rate = get_slippage_pct(adv_cr, is_news_recent=is_news_recent)
    slippage = slip_rate * (b + s)

    return brokerage + stt + exchange + sebi + stamp + gst + slippage
