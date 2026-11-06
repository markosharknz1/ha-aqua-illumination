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


def test_identify_ignores_name_and_finds_presets():
    sched = presets.build_schedule("coral_growth", CH, True)
    on_light = {**sched, "name": "default"}  # firmware keeps the name "default"
    assert presets.identify(on_light, CH, {}) == "Coral growth"
    assert presets.identify(presets.build_schedule("standard", CH, False), CH, {}) == "Standard day"
    mine = {"name": "Mine", "ramps": [{"color": c, "points": [{"time": 0, "intensity": 5}, {"time": 600, "intensity": 7}]} for c in CH]}
    assert presets.identify(mine, CH, {"Mine": mine}) == "Mine"
    assert presets.identify(mine, CH, {}) is None
    assert presets.identify(None, CH, {}) is None


night = load("night")


def _day(ch="blue"):
    pts = [{"time": 0, "intensity": 0}, {"time": 480, "intensity": 0},
           {"time": 600, "intensity": 600}, {"time": 1080, "intensity": 600},
           {"time": 1200, "intensity": 0}, {"time": 1439, "intensity": 0}]
    return {"name": "default", "ramps": [{"color": c, "points": [dict(p) for p in pts]} for c in (ch, "uv")]}


def _val(sched, color, t):
    return night.value_at(next(r for r in sched["ramps"] if r["color"] == color)["points"], t)


def test_night_disabled_is_identity():
    day = _day()
    assert night.compose(day, {"enable": False, "start": 1200, "end": 420, "level": 5, "channels": ["blue"]}) is day


def test_night_wraps_midnight_and_only_touches_chosen_channels():
    day = _day()
    n = {"enable": True, "start": 1200, "end": 420, "level": 5, "channels": ["blue"]}
    out = night.compose(day, n)
    api.validate_schedule(out, ["blue", "uv"])  # still a valid schedule
    for t in (0, 100, 300, 410, 1210, 1300, 1439):   # inside the window
        assert _val(out, "blue", t) == 50
    for t in (480, 540, 600, 800, 1080, 1150):        # outside: day curve unchanged
        assert abs(_val(out, "blue", t) - _val(day, "blue", t)) < 1
    assert all(_val(out, "uv", t) == _val(day, "uv", t) for t in (0, 300, 700, 1300))
    assert night.compose(day, n)["ramps"][1] is day["ramps"][1]


def test_night_does_not_mutate_day_layer():
    day = _day()
    snap = presets.normalize(day)
    night.compose(day, {"enable": True, "start": 1200, "end": 420, "level": 5, "channels": ["blue"]})
    assert presets.normalize(day) == snap


def test_night_window_inside_one_day_and_edges():
    day = _day()
    out = night.compose(day, {"enable": True, "start": 0, "end": 300, "level": 10, "channels": ["blue"]})
    assert _val(out, "blue", 0) == 100 and _val(out, "blue", 299) == 100
    assert _val(out, "blue", 700) == _val(day, "blue", 700)
    out2 = night.compose(day, {"enable": True, "start": 600, "end": 600, "level": 10, "channels": ["blue"]})
    assert out2 is day  # empty window


def test_clean_night_validation():
    ch = ["blue", "uv"]
    assert night.default_night(ch)["channels"] == ["blue"]
    assert night.clean_night({"level": 7, "start": 60}, ch)["level"] == 7.0
    for bad in ({"level": 101}, {"start": 2000}, {"channels": ["nope"]}):
        try:
            night.clean_night(bad, ch)
        except ValueError:
            continue
        raise AssertionError(bad)


def test_export_import_roundtrip_and_validation():
    sched = presets.build_schedule("coral_growth", CH, False)
    saved = {"Mine": {"name": "Mine", "ramps": sched["ramps"]}}
    payload = presets.export_payload(saved)
    import json
    back = presets.parse_import(json.dumps(payload), CH, api.validate_schedule)
    assert presets.normalize(back["Mine"]) == presets.normalize(saved["Mine"])
    for bad in ("not json", "{}", json.dumps({presets.EXPORT_TAG: 1, "presets": {}}),
                json.dumps({presets.EXPORT_TAG: 1, "presets": {"Coral growth": {"ramps": sched["ramps"]}}}),
                json.dumps({presets.EXPORT_TAG: 1, "presets": {"X": {"ramps": sched["ramps"][:2]}}})):
        try:
            presets.parse_import(bad, CH, api.validate_schedule)
        except ValueError:
            continue
        raise AssertionError(bad)


def test_normalize_survives_json_roundtrip():
    import json
    n = presets.normalize(presets.build_schedule("standard", CH, True))
    assert json.loads(json.dumps(n)) == n
