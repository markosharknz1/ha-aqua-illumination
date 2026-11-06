"""Built-in schedule presets (pure; no Home Assistant imports).

A preset is a recipe: photoperiod + per-channel peak weights. `build_schedule`
turns it into the ramps the light wants (every channel needs a ramp).
"""
from __future__ import annotations

# Fraction of full output each channel reaches at midday, per preset.
_WEIGHTS = {
    "standard": {
        "blue": .7, "deep_blue": .7, "royal": .7, "violet": .5, "uv": .35,
        "cool_white": .6, "neutral_white": .5, "warm_white": .3, "green": .3,
        "deep_red": .2, "red": .2, "far_red": .1,
    },
    "coral_growth": {
        "blue": .9, "deep_blue": .9, "royal": .9, "violet": .7, "uv": .5,
        "cool_white": .35, "neutral_white": .3, "warm_white": .15, "green": .2,
        "deep_red": .15, "red": .15, "far_red": .1,
    },
    "acclimation": {
        "blue": .3, "deep_blue": .3, "royal": .3, "violet": .2, "uv": .1,
        "cool_white": .2, "neutral_white": .2, "warm_white": .1, "green": .1,
        "deep_red": .1, "red": .1, "far_red": .05,
    },
}
_DEFAULT_WEIGHT = .4

# name -> (label, sunrise-start minute, sunset-end minute, ramp minutes)
PRESETS = {
    "standard": ("Standard day", 7 * 60, 19 * 60, 120),
    "coral_growth": ("Coral growth", 8 * 60, 20 * 60, 150),
    "acclimation": ("Acclimation (gentle)", 10 * 60, 18 * 60, 120),
}

# Faint overnight glow so lunar mode has something to dim (percent).
NIGHT_GLOW = {"blue": 10, "royal": 10, "deep_blue": 5}


def builtin_names() -> list[str]:
    return [v[0] for v in PRESETS.values()]


def key_for_label(label: str) -> str | None:
    for key, (lab, *_rest) in PRESETS.items():
        if lab == label:
            return key
    return None


def build_schedule(key: str, channels: list[str], night_glow: bool = True) -> dict:
    label, start, end, ramp = PRESETS[key]
    ramp = min(ramp, (end - start) // 2)
    out = []
    for ch in channels:
        peak = round(1000 * _WEIGHTS[key].get(ch, _DEFAULT_WEIGHT))
        night = round(NIGHT_GLOW.get(ch, 0) * 10) if night_glow else 0
        night = min(night, peak)
        out.append({"color": ch, "points": [
            {"time": 0, "intensity": night},
            {"time": start, "intensity": night},
            {"time": start + ramp, "intensity": peak},
            {"time": end - ramp, "intensity": peak},
            {"time": end, "intensity": night},
            {"time": 1439, "intensity": night},
        ]})
    return {"name": label, "ramps": out}


def normalize(schedule: dict | None) -> dict:
    """channel -> [[minute, intensity], ...]; ignores the name, which the light
    does not keep (it always reports "default"). Lists, not tuples, so the value
    compares equal after a round trip through the JSON store."""
    return {
        r["color"]: [[p["time"], p["intensity"]] for p in r.get("points", [])]
        for r in (schedule or {}).get("ramps", [])
    }


def identify(schedule: dict | None, channels: list[str], saved: dict[str, dict]) -> str | None:
    """Label of the preset whose ramps equal `schedule`, if any."""
    cur = normalize(schedule)
    if not cur:
        return None
    for key, (label, *_rest) in PRESETS.items():
        for glow in (True, False):
            if normalize(build_schedule(key, channels, glow)) == cur:
                return label
    for name, sched in saved.items():
        if normalize(sched) == cur:
            return name
    return None


EXPORT_TAG = "aqua_illumination_presets"


def export_payload(saved: dict[str, dict]) -> dict:
    """Shareable form of the saved presets (JSON-serialisable)."""
    return {EXPORT_TAG: 1, "presets": {
        name: {"ramps": sched["ramps"]} for name, sched in saved.items()}}


def parse_import(data, channels: list[str], validate) -> dict[str, dict]:
    """Presets from an export (dict or JSON text), validated for this light.

    Raises ValueError on anything malformed, naming the offending preset. Built-in
    names are refused so an import can never shadow them."""
    import json

    if isinstance(data, str):
        try:
            data = json.loads(data)
        except ValueError as err:
            raise ValueError(f"not valid JSON: {err}") from err
    if not isinstance(data, dict) or EXPORT_TAG not in data or not isinstance(data.get("presets"), dict):
        raise ValueError("not an Aqua Illumination preset export")
    out = {}
    for name, sched in data["presets"].items():
        name = str(name).strip()
        if not name or key_for_label(name):
            raise ValueError(f"preset name {name!r} is empty or a built-in name")
        try:
            clean = validate({"name": name, "ramps": (sched or {}).get("ramps")}, channels)
        except (ValueError, KeyError, TypeError) as err:
            raise ValueError(f"preset {name!r}: {err}") from err
        out[name] = {"name": name, "ramps": clean["ramps"]}
    if not out:
        raise ValueError("the export contains no presets")
    return out
