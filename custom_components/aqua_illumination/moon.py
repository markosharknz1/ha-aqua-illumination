"""Moon phase from the date alone (pure; no Home Assistant imports)."""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

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


# ---- moonrise / moonset ----------------------------------------------------
# Low-precision lunar position (Astronomical Almanac style), good to a few
# minutes for rise/set, which is plenty for a night light.

def _julian_day(dt: datetime) -> float:
    return dt.timestamp() / 86400.0 + 2440587.5


def moon_altitude(dt: datetime, lat: float, lon: float) -> float:
    """Moon altitude in degrees above the rise/set horizon (negative = below).

    The horizon threshold already includes refraction and parallax, so the sign
    flips exactly at moonrise and moonset."""
    d = _julian_day(dt) - 2451545.0
    L = math.radians((218.316 + 13.176396 * d) % 360)
    M = math.radians((134.963 + 13.064993 * d) % 360)
    F = math.radians((93.272 + 13.229350 * d) % 360)
    lam = L + math.radians(6.289) * math.sin(M)
    beta = math.radians(5.128) * math.sin(F)
    dist = 385001 - 20905 * math.cos(M)
    eps = math.radians(23.439 - 0.0000004 * d)
    ra = math.atan2(math.sin(lam) * math.cos(eps) - math.tan(beta) * math.sin(eps), math.cos(lam))
    dec = math.asin(math.sin(beta) * math.cos(eps) + math.cos(beta) * math.sin(eps) * math.sin(lam))
    gmst = math.radians((280.147 + 360.9856235 * d) % 360)
    hour_angle = gmst + math.radians(lon) - ra
    phi = math.radians(lat)
    alt = math.asin(math.sin(phi) * math.sin(dec) + math.cos(phi) * math.cos(dec) * math.cos(hour_angle))
    parallax = math.degrees(math.asin(6378.14 / dist))
    return math.degrees(alt) - (0.7275 * parallax - 0.5667)


def moon_up_intervals(
    start: datetime, end: datetime, lat: float, lon: float, step_minutes: int = 10
) -> list[tuple[datetime, datetime]]:
    """Spans inside [start, end] during which the moon is above the horizon."""
    step = timedelta(minutes=step_minutes)
    out: list[tuple[datetime, datetime]] = []
    t, up_since = start, None
    prev_up = moon_altitude(start, lat, lon) > 0
    if prev_up:
        up_since = start
    while t < end:
        nxt = min(t + step, end)
        now_up = moon_altitude(nxt, lat, lon) > 0
        if now_up != prev_up:
            lo, hi = t, nxt  # bisect to ~30 s
            while (hi - lo) > timedelta(seconds=30):
                mid = lo + (hi - lo) / 2
                if (moon_altitude(mid, lat, lon) > 0) == prev_up:
                    lo = mid
                else:
                    hi = mid
            cross = hi
            if now_up:
                up_since = cross
            else:
                out.append((up_since, cross))
                up_since = None
        prev_up, t = now_up, nxt
    if up_since is not None:
        out.append((up_since, end))
    return out


def night_glow_window(
    start: datetime, hours: float, lat: float, lon: float, min_minutes: int = 10
) -> dict | None:
    """The part of the night (``hours`` long, from ``start``) in which the moon is up.

    Returns ``{"start": dt, "end": dt, "illumination": %}`` for the longest such
    stretch (the moon is up in one contiguous span per night), or ``None`` when
    it never rises in the night or is up for less than ``min_minutes``."""
    end = start + timedelta(hours=hours)
    spans = moon_up_intervals(start, end, lat, lon)
    spans = [(a, b) for a, b in spans if (b - a) >= timedelta(minutes=min_minutes)]
    if not spans:
        return None
    a, b = max(spans, key=lambda s: s[1] - s[0])
    mid = a + (b - a) / 2
    return {"start": a, "end": b, "illumination": moon_phase(mid)["illumination"]}
