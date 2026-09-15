import time
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class RateLimit:
    limit: int = 0
    remaining: int = 0
    reset_at: float = 0.0
    used: int = 0

    @classmethod
    def from_api(cls, data: dict) -> "RateLimit":
        resources = data.get("resources", {})
        core = resources.get("core", {})
        return cls(
            limit=core.get("limit", 0),
            remaining=core.get("remaining", 0),
            reset_at=core.get("reset", 0),
            used=core.get("used", 0),
        )

    def is_exhausted(self) -> bool:
        return self.remaining <= 10

    def wait_seconds(self) -> float:
        if self.remaining > 10:
            return 0.0
        now = time.time()
        wait = self.reset_at - now
        return max(wait, 0)

    def to_dict(self) -> dict:
        return {
            "limit": self.limit,
            "remaining": self.remaining,
            "reset_at": self.reset_at,
            "used": self.used,
            "is_exhausted": self.is_exhausted(),
            "wait_seconds": self.wait_seconds(),
        }


class RateLimiter:
    def __init__(self, requests_per_hour: int = 5000, burst_size: int = 30):
        self.requests_per_hour = requests_per_hour
        self.burst_size = burst_size
        self._timestamps: list[float] = []
        self._lock = False

    def acquire(self) -> None:
        now = time.monotonic()
        self._timestamps = [t for t in self._timestamps if now - t < 3600]
        if len(self._timestamps) >= self.burst_size:
            oldest = self._timestamps[0]
            wait = 3600 - (now - oldest) + 0.1
            time.sleep(max(wait, 0))
            now = time.monotonic()
            self._timestamps = [t for t in self._timestamps if now - t < 3600]
        self._timestamps.append(time.monotonic())

    def get_status(self) -> dict:
        now = time.monotonic()
        self._timestamps = [t for t in self._timestamps if now - t < 3600]
        remaining = max(0, self.burst_size - len(self._timestamps))
        return {
            "burst_remaining": remaining,
            "burst_size": self.burst_size,
            "requests_per_hour": self.requests_per_hour,
        }