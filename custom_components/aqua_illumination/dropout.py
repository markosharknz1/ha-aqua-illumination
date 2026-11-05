"""Dropout tracking: pure logic, no Home Assistant imports (unit-testable)."""
from __future__ import annotations

from datetime import datetime


class DropoutTracker:
    """Counts consecutive poll failures and records offline episodes.

    One failed poll is a blip (the light is slow to answer after idle); the
    light only counts as offline after `threshold` failures in a row.
    """

    def __init__(self, threshold: int = 2) -> None:
        self.threshold = threshold
        self.failures = 0
        self.dropouts = 0
        self.last_seen: datetime | None = None
        self.offline_since: datetime | None = None
        self.last_error: str | None = None
        self.last_outage_seconds: float | None = None

    @property
    def online(self) -> bool:
        return self.offline_since is None

    def success(self, now: datetime) -> bool:
        """Record a good poll. Returns True if the light just came back."""
        recovered = self.offline_since is not None
        if recovered:
            self.last_outage_seconds = (now - self.offline_since).total_seconds()
        self.failures = 0
        self.offline_since = None
        self.last_error = None
        self.last_seen = now
        return recovered

    def failure(self, now: datetime, error: str) -> bool:
        """Record a failed poll. Returns True once the light counts as offline."""
        self.failures += 1
        self.last_error = error
        if self.offline_since is None and self.failures >= self.threshold:
            # Back-date to the last good poll so "since" matches reality.
            self.offline_since = self.last_seen or now
            self.dropouts += 1
        return self.offline_since is not None
