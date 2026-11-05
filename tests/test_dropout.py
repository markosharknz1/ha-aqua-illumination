"""DropoutTracker: pure logic."""
import importlib.util
import pathlib
import sys
from datetime import datetime, timedelta

ROOT = pathlib.Path(__file__).resolve().parents[1] / "custom_components" / "aqua_illumination"
spec = importlib.util.spec_from_file_location("aqua_dropout", ROOT / "dropout.py")
mod = importlib.util.module_from_spec(spec)
sys.modules["aqua_dropout"] = mod
spec.loader.exec_module(mod)

T0 = datetime(2026, 11, 5, 12, 0, 0)


def at(s):
    return T0 + timedelta(seconds=s)


def test_single_failure_is_a_blip():
    d = mod.DropoutTracker(2)
    d.success(at(0))
    assert d.failure(at(30), "timeout") is False
    assert d.online and d.dropouts == 0
    d.success(at(60))
    assert d.failures == 0 and d.last_error is None


def test_offline_after_threshold_and_recovery():
    d = mod.DropoutTracker(2)
    d.success(at(0))
    d.failure(at(30), "x")
    assert d.failure(at(60), "x") is True
    assert not d.online and d.dropouts == 1
    assert d.offline_since == at(0)  # back-dated to last good poll
    assert d.failure(at(90), "x") is True and d.dropouts == 1  # same episode
    assert d.success(at(120)) is True
    assert d.online and d.last_outage_seconds == 120 and d.last_seen == at(120)


def test_repeated_episodes_counted():
    d = mod.DropoutTracker(2)
    for base in (0, 1000):
        d.success(at(base))
        d.failure(at(base + 30), "x")
        d.failure(at(base + 60), "x")
    assert d.dropouts == 2
