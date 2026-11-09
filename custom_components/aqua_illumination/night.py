"""Night-light layer: overlay a low glow on the schedule (pure; no HA imports).

The light's own lunar mode only dims whatever night level the schedule already
has, so a schedule that is 0 at night shows no "moon". We keep the schedule as
two layers - the DAY layer (what the user edits) and a NIGHT config - and write
the composition to the light. Editing the day layer therefore never loses the
night glow, and switching the glow off puts the day layer back untouched.
"""
from __future__ import annotations

from typing import Any

LAST_MINUTE = 1439  # the firmware drops a trailing 1440 point


def default_night(channels: list[str]) -> dict[str, Any]:
    """Off by default; blue-ish channels pre-selected, window 20:00-07:00, 5 %."""
    blues = [c for c in ("blue", "royal", "deep_blue") if c in channels]
    return {
        "enable": False, "start": 1200, "end": 420, "level": 5.0,
        "channels": blues or channels[:1],
        # Follow the real moon: glow only while it is up, scaled by its phase.
        "follow_moon": False, "moon_min": 10.0,
    }


def clean_night(night: dict[str, Any], channels: list[str]) -> dict[str, Any]:
    """Validate a night config, returning a normalised copy or raising ValueError."""
    out = {**default_night(channels), **{k: v for k, v in night.items() if v is not None}}
    out["enable"] = bool(out["enable"])
    for k in ("start", "end"):
        out[k] = int(out[k])
        if not 0 <= out[k] < 1440:
            raise ValueError("night light times must be 00:00-23:59")
    out["level"] = float(out["level"])
    if not 0 <= out["level"] <= 100:
        raise ValueError("night light level must be 0-100 %")
    out["follow_moon"] = bool(out["follow_moon"])
    out["moon_min"] = float(out["moon_min"])
    if not 0 <= out["moon_min"] <= 100:
        raise ValueError("moon minimum must be 0-100 %")
    chans = list(out["channels"])
    bad = [c for c in chans if c not in channels]
    if bad:
        raise ValueError(f"unknown channel(s): {', '.join(bad)}")
    out["channels"] = chans
    return out


def value_at(points: list[dict], minute: float) -> float:
    """Linear interpolation of a ramp, holding flat before the first / after the last point."""
    if not points:
        return 0.0
    if minute <= points[0]["time"]:
        return float(points[0]["intensity"])
    for a, b in zip(points, points[1:]):
        if minute <= b["time"]:
            span = b["time"] - a["time"]
            if span <= 0:
                return float(b["intensity"])
            return a["intensity"] + (b["intensity"] - a["intensity"]) * (minute - a["time"]) / span
    return float(points[-1]["intensity"])


def _segments(start: int, end: int) -> list[tuple[int, int]]:
    """Window [start, end) as one or two minute intervals, clipped to the day."""
    if start == end:
        return []
    if start < end:
        segs = [(start, end)]
    else:  # wraps midnight
        segs = [(start, LAST_MINUTE + 1), (0, end)]
    return [(a, min(b, LAST_MINUTE + 1)) for a, b in segs]


def _overlay_ramp(points: list[dict], segs: list[tuple[int, int]], level: int) -> list[dict]:
    inside = lambda t: any(a <= t < b for a, b in segs)  # noqa: E731
    keep = {p["time"]: p["intensity"] for p in points if not inside(p["time"])}
    forced: dict[int, int] = {}
    for a, b in segs:
        if a > 0:  # step: hold the day value up to the minute before the window
            forced[a - 1] = round(value_at(points, a - 1))
        forced[a] = level
        forced[min(b - 1, LAST_MINUTE)] = level
        if b <= LAST_MINUTE:
            forced[b] = round(value_at(points, b))
    merged = {**keep, **forced}
    merged.setdefault(0, round(value_at(points, 0)))
    merged.setdefault(LAST_MINUTE, round(value_at(points, LAST_MINUTE)))
    return [{"time": t, "intensity": merged[t]} for t in sorted(merged)]


def compose(day: dict[str, Any], night: dict[str, Any]) -> dict[str, Any]:
    """The schedule to write: the day layer with the night glow replacing the
    selected channels inside the window. Disabled night -> the day layer as is."""
    if not night.get("enable"):
        return day
    segs = _segments(int(night["start"]), int(night["end"]))
    if not segs or not night["channels"]:
        return day
    level = round(float(night["level"]) * 10)
    ramps = []
    for r in day["ramps"]:
        if r["color"] in night["channels"]:
            ramps.append({"color": r["color"], "points": _overlay_ramp(r["points"], segs, level)})
        else:
            ramps.append(r)
    return {"name": day.get("name", "default"), "ramps": ramps}


def effective_night(night: dict[str, Any], window: dict | None) -> dict[str, Any]:
    """The night layer actually written to the light.

    Without "follow the moon" this is the configured night layer. With it, the
    glow is confined to the part of the night the moon is up (``window`` =
    ``{"start": minute, "end": minute, "illumination": %}``, or ``None`` if it
    never rises in the night) and its level is scaled by how lit the moon is,
    never below ``moon_min`` % of the full-moon level."""
    if not night.get("follow_moon"):
        return night
    if not night.get("enable") or not window:
        return {**night, "enable": False}
    factor = max(night["moon_min"] / 100.0, window["illumination"] / 100.0)
    return {
        **night, "start": window["start"], "end": window["end"],
        "level": round(night["level"] * factor, 2),
    }
