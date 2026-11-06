"""Dashboard generator produces valid YAML with the right entities."""
import importlib.util
import pathlib

import yaml

path = pathlib.Path(__file__).resolve().parents[1] / "dashboards" / "generate_dashboard.py"
spec = importlib.util.spec_from_file_location("gen_dash", path)
gen = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gen)


def test_single_light():
    d = yaml.safe_load(gen.dashboard(["ai_prime_0a82"], "Reef"))
    cards = d["views"][0]["cards"]
    assert d["title"] == "Reef"
    assert cards[0] == {"type": "custom:aqua-illumination-card",
                        "entity": "sensor.ai_prime_0a82_schedule_data", "name": "Ai Prime 0A82"}
    assert "switch.ai_prime_0a82_lights_off" in cards[1]["entities"]
    assert cards[2]["type"] == "history-graph"


def test_multiple_lights_nest_in_stacks():
    d = yaml.safe_load(gen.dashboard(["a_1", "b_2"]))
    stacks = d["views"][0]["cards"]
    assert [s["type"] for s in stacks] == ["vertical-stack", "vertical-stack"]
    assert stacks[1]["cards"][0]["entity"] == "sensor.b_2_schedule_data"
    assert len(stacks[0]["cards"]) == 3
