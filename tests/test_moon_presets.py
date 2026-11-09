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


# ---- moonrise / moonset ------------------------------------------------------
from datetime import timedelta
from zoneinfo import ZoneInfo

ADL = ZoneInfo("Australia/Adelaide")
LAT, LON = -34.93, 138.60


def _local(y, m, d, hh=0, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=ADL)


def test_full_moon_is_up_most_of_the_night():
    w = moon.night_glow_window(_local(2025, 2, 12, 20), 11, LAT, LON)   # 20:00 -> 07:00
    assert w is not None
    assert _local(2025, 2, 12, 19, 30) <= w["start"] <= _local(2025, 2, 12, 21, 30)   # rises near sunset
    assert _local(2025, 2, 13, 5, 0) <= w["end"] <= _local(2025, 2, 13, 7, 30)        # sets near sunrise
    assert w["illumination"] >= 95


def test_new_moon_is_down_in_the_middle_of_the_night():
    assert moon.night_glow_window(_local(2025, 1, 30, 22), 8, LAT, LON) is None       # 22:00 -> 06:00
    w = moon.night_glow_window(_local(2025, 1, 30, 20), 11, LAT, LON)                 # but up briefly at dusk
    assert w is not None and (w["end"] - w["start"]) < timedelta(hours=2)
    assert w["illumination"] <= 5


def test_window_stays_inside_the_night():
    for day in range(1, 29):
        s = _local(2025, 2, day, 20)
        w = moon.night_glow_window(s, 11, LAT, LON)
        if w:
            assert s <= w["start"] < w["end"] <= s + timedelta(hours=11)


def test_moonrise_advances_roughly_50_minutes_a_day():
    def rise(day):
        spans = moon.moon_up_intervals(_local(2025, 2, day), _local(2025, 2, day) + timedelta(hours=24), LAT, LON)
        return [a for a, _ in spans if a.hour or a.minute][0]
    gaps = [((rise(d + 1) - rise(d)).total_seconds() / 60) % 1440 for d in range(6, 12)]
    assert all(30 <= g <= 75 for g in gaps), gaps


def test_northern_hemisphere_also_works():
    # London, full moon 2025-02-12: up through the winter night
    w = moon.night_glow_window(datetime(2025, 2, 12, 18, tzinfo=ZoneInfo("Europe/London")), 12, 51.5, -0.1)
    assert w is not None and (w["end"] - w["start"]) > timedelta(hours=8)


# ---- follow the moon: effective night layer ------------------------------------
def _base_night(**kw):
    n = night.default_night(["blue", "uv"])
    n.update(enable=True, level=10.0, **kw)
    return n


def test_effective_night_unchanged_without_follow():
    n = _base_night()
    assert night.effective_night(n, {"start": 1, "end": 2, "illumination": 50}) is n


def test_effective_night_confines_window_and_scales_by_phase():
    n = _base_night(follow_moon=True, moon_min=10.0)
    e = night.effective_night(n, {"start": 1224, "end": 367, "illumination": 62})
    assert (e["start"], e["end"]) == (1224, 367)
    assert abs(e["level"] - 6.2) < 1e-9 and e["enable"] is True
    # a thin crescent never drops below the floor
    e2 = night.effective_night(n, {"start": 1224, "end": 367, "illumination": 3})
    assert abs(e2["level"] - 1.0) < 1e-9
    # nothing rises tonight -> no glow at all
    assert night.effective_night(n, None)["enable"] is False
    assert night.effective_night({**n, "enable": False}, {"start": 1, "end": 2, "illumination": 90})["enable"] is False


def test_follow_moon_composes_a_valid_schedule():
    day = _day()
    n = _base_night(follow_moon=True, channels=["blue"])
    e = night.effective_night(n, {"start": 1224, "end": 367, "illumination": 62})
    out = night.compose(day, e)
    api.validate_schedule(out, ["blue", "uv"])
    assert abs(_val(out, "blue", 1300) - 62) < 1 and _val(out, "blue", 200) == 62   # 6.2 % of 1000 = 62
    assert _val(out, "blue", 600) == _val(day, "blue", 600)


def test_clean_night_validates_moon_fields():
    ch = ["blue", "uv"]
    assert night.clean_night({"follow_moon": True, "moon_min": 20}, ch)["moon_min"] == 20.0
    try:
        night.clean_night({"moon_min": 150}, ch)
    except ValueError:
        return
    raise AssertionError("moon_min 150 accepted")
