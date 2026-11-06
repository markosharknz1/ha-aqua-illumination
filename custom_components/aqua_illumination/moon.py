"""Moon phase from the date alone (pure; no Home Assistant imports)."""
from __future__ import annotations

import math
from datetime import datetime, timezone

SYNODIC_DAYS = 29.530588853
_NEW_MOON = datetime(2000, 1, 6, 18, 14, tzinfo=timezone.utc)  # a known new moon

PHASES = [
    "new_moon", "waxing_crescent", "first_quarter", "waxing_gibbous",
    "full_moon", "waning_gibbous", "last_quarter", "waning_crescent",
]


def moon_phase(now: datetime) -> dict:
    """Return {name, age_days, illumination (0-100 %)} for `now` (tz-aware or UTC)."""
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    age = ((now - _NEW_MOON).total_seconds() / 86400) % SYNODIC_DAYS
    frac = age / SYNODIC_DAYS
    illumination = (1 - math.cos(2 * math.pi * frac)) / 2 * 100
    name = PHASES[int(frac * 8 + 0.5) % 8]
    return {"name": name, "age_days": round(age, 1), "illumination": round(illumination)}
