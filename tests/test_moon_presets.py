"""Pure helpers: moon phase and preset builder."""
import importlib.util
import pathlib
import sys
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parents[1] / "custom_components" / "aqua_illumination"


def load(name):
    spec = importlib.util.spec_from_file_location(f"aqua_{name}", ROOT / f"{name}.py")
    m = importlib.util.module_from_spec(spec)
    sys.modules[f"aqua_{name}"] = m
    spec.loader.exec_module(m)
    return m


moon, presets, api = load("moon"), load("presets"), load("api")
CH = ["deep_red", "uv", "deep_blue", "violet", "cool_white", "green", "blue"]


def utc(*a):
    return datetime(*a, tzinfo=timezone.utc)


def test_known_phases():
    assert moon.moon_phase(utc(2000, 1, 6, 18, 14))["name"] == "new_moon"
    # Real events: new moon 2025-01-29 12:36 UTC, full moon 2025-02-12 13:53 UTC.
    assert moon.moon_phase(utc(2025, 1, 29, 13, 0))["name"] == "new_moon"
    full = moon.moon_phase(utc(2025, 2, 12, 14, 0))
    assert full["name"] == "full_moon" and full["illumination"] >= 99
    assert moon.moon_phase(utc(2025, 2, 5, 9, 0))["name"] == "first_quarter"


def test_illumination_extremes():
    assert moon.moon_phase(utc(2000, 1, 6, 18, 14))["illumination"] == 0
    half = moon.moon_phase(utc(2000, 1, 6, 18, 14).replace(day=21, hour=8))
    assert half["illumination"] > 90


def test_presets_validate_against_api():
    for key in presets.PRESETS:
        for glow in (True, False):
            sched = presets.build_schedule(key, CH, glow)
            clean = api.validate_schedule(sched, CH)
            assert len(clean["ramps"]) == len(CH)


def test_night_glow_only_on_blue_channels():
    s = presets.build_schedule("standard", CH, True)
    first = {r["color"]: r["points"][0]["intensity"] for r in s["ramps"]}
    assert first["blue"] == 100 and first["deep_blue"] == 50 and first["uv"] == 0
    s2 = presets.build_schedule("standard", CH, False)
    assert all(r["points"][0]["intensity"] == 0 for r in s2["ramps"])
