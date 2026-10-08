"""
Trading calendar and session schedule calculations for Indian markets (NSE/BSE).
Handles holidays, trading day checks, square-off cutoffs, and exit times.
"""
from datetime import date, datetime, time, timedelta
from typing import Set
from engine.config import get_settings
from engine.core.clock import IST, get_clock

# Standard NSE Trading Holidays for 2025 and 2026 (YYYY-MM-DD)
NSE_HOLIDAYS: Set[str] = {
    # 2025
    "2025-01-26", "2025-02-26", "2025-03-14", "2025-03-31",
    "2025-04-10", "2025-04-14", "2025-04-18", "2025-05-01",
    "2025-06-07", "2025-08-15", "2025-08-27", "2025-10-02",
    "2025-10-21", "2025-10-22", "2025-11-05", "2025-12-25",
    # 2026
    "2026-01-26", "2026-02-17", "2026-03-04", "2026-03-20",
    "2026-04-03", "2026-04-14", "2026-05-01", "2026-05-28",
    "2026-08-15", "2026-08-26", "2026-10-02", "2026-10-20",
    "2026-11-08", "2026-11-24", "2026-12-25",
}


def get_all_holidays() -> Set[str]:
    """Return all known trading holidays including extra holidays configured in config.yaml."""
    settings = get_settings()
    holidays = set(NSE_HOLIDAYS)
    if settings.calendar and settings.calendar.extra_holidays:
        holidays.update(settings.calendar.extra_holidays)
    return holidays


def is_trading_day(d: date | datetime | None = None) -> bool:
    """Return True if the date is a weekday (Monday-Friday) and not an exchange holiday."""
    if d is None:
        d = get_clock().today()
    elif isinstance(d, datetime):
        d = d.date()

    if d.weekday() >= 5:  # Saturday = 5, Sunday = 6
        return False

    date_str = d.isoformat()
    return date_str not in get_all_holidays()


def next_trading_day(d: date | datetime | None = None) -> date:
    """Return the next trading day following the given date."""
    if d is None:
        d = get_clock().today()
    elif isinstance(d, datetime):
        d = d.date()

    cur = d + timedelta(days=1)
    while not is_trading_day(cur):
        cur += timedelta(days=1)
    return cur


def previous_trading_day(d: date | datetime | None = None) -> date:
    """Return the previous trading day before the given date."""
    if d is None:
        d = get_clock().today()
    elif isinstance(d, datetime):
        d = d.date()

    cur = d - timedelta(days=1)
    while not is_trading_day(cur):
        cur -= timedelta(days=1)
    return cur


def _parse_time_str(time_str: str) -> time:
    parts = [int(p) for p in time_str.split(":")]
    if len(parts) == 2:
        return time(hour=parts[0], minute=parts[1])
    elif len(parts) == 3:
        return time(hour=parts[0], minute=parts[1], second=parts[2])
    raise ValueError(f"Invalid time string: {time_str}")


def squareoff_time(symbol: str, is_fno: bool = False) -> time:
    """Return broker square-off time for the symbol (F&O or non-F&O)."""
    settings = get_settings()
    sq_cfg = settings.broker.squareoff
    time_str = sq_cfg.fno_stocks if is_fno else sq_cfg.other_stocks
    return _parse_time_str(time_str)


def last_exit_time(symbol: str, is_fno: bool = False, on_date: date | None = None) -> datetime:
    """
    Return last exit time for an MIS trade (squareoff_time - exit_buffer_min).
    All MIS trades must exit by this time.
    """
    settings = get_settings()
    if on_date is None:
        on_date = get_clock().today()

    sq_t = squareoff_time(symbol, is_fno)
    sq_dt = datetime.combine(on_date, sq_t, tzinfo=IST)
    exit_buffer = timedelta(minutes=settings.broker.exit_buffer_min)
    return sq_dt - exit_buffer


def entry_cutoff(symbol: str, is_fno: bool = False, on_date: date | None = None) -> datetime:
    """
    Return cutoff time after which no new MIS entries are allowed
    (last_exit_time - entry_cutoff_min).
    """
    settings = get_settings()
    exit_dt = last_exit_time(symbol, is_fno, on_date)
    cutoff_buffer = timedelta(minutes=settings.broker.entry_cutoff_min)
    return exit_dt - cutoff_buffer
