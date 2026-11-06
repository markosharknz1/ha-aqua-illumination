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
