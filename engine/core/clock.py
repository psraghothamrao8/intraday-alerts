"""
Clock abstraction for time-dependent operations.
Ensures reproducible replay and testing without calling datetime.now() directly.
"""
from abc import ABC, abstractmethod
from datetime import date, datetime, timedelta
import zoneinfo

IST = zoneinfo.ZoneInfo("Asia/Kolkata")


class Clock(ABC):
    """Abstract clock interface."""

    @abstractmethod
    def now(self) -> datetime:
        """Return current timezone-aware datetime (Asia/Kolkata by default)."""
        pass

    def today(self) -> date:
        """Return current date."""
        return self.now().date()


class RealClock(Clock):
    """Real system wall-clock, returning timezone-aware datetimes."""

    def __init__(self, tz_name: str = "Asia/Kolkata"):
        self.tz = zoneinfo.ZoneInfo(tz_name)

    def now(self) -> datetime:
        return datetime.now(self.tz)


class FakeClock(Clock):
    """
    Controllable fake clock for testing and replaying past trading sessions.
    """

    def __init__(self, initial_time: datetime | str | None = None, tz_name: str = "Asia/Kolkata"):
        self.tz = zoneinfo.ZoneInfo(tz_name)
        if initial_time is None:
            self._current_time = datetime.now(self.tz)
        elif isinstance(initial_time, str):
            dt = datetime.fromisoformat(initial_time)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=self.tz)
            self._current_time = dt
        else:
            if initial_time.tzinfo is None:
                self._current_time = initial_time.replace(tzinfo=self.tz)
            else:
                self._current_time = initial_time.astimezone(self.tz)

    def now(self) -> datetime:
        return self._current_time

    def set_time(self, new_time: datetime | str) -> None:
        if isinstance(new_time, str):
            dt = datetime.fromisoformat(new_time)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=self.tz)
            self._current_time = dt
        else:
            if new_time.tzinfo is None:
                self._current_time = new_time.replace(tzinfo=self.tz)
            else:
                self._current_time = new_time.astimezone(self.tz)

    def advance(self, duration: timedelta | float | int) -> datetime:
        """Advance fake clock by timedelta or seconds (float/int)."""
        if isinstance(duration, (int, float)):
            delta = timedelta(seconds=duration)
        elif isinstance(duration, timedelta):
            delta = duration
        else:
            raise TypeError(f"Unsupported duration type: {type(duration)}")
        self._current_time += delta
        return self._current_time


_GLOBAL_CLOCK: Clock = RealClock()


def get_clock() -> Clock:
    """Get the active global clock instance."""
    return _GLOBAL_CLOCK


def set_clock(clock: Clock) -> None:
    """Set the active global clock instance."""
    global _GLOBAL_CLOCK
    _GLOBAL_CLOCK = clock
