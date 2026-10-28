"""API client tests against a fake Prime that mimics the real firmware 2.5.1 replies."""
import asyncio
import importlib.util
import pathlib
import sys

import pytest
from aiohttp import web

ROOT = pathlib.Path(__file__).resolve().parents[1] / "custom_components" / "aqua_illumination"
spec = importlib.util.spec_from_file_location("aqua_api", ROOT / "api.py")
api = importlib.util.module_from_spec(spec)
sys.modules["aqua_api"] = api
spec.loader.exec_module(api)

CHANNELS = ["deep_red", "uv", "deep_blue", "violet", "cool_white", "green", "blue"]


class FakePrime:
    def __init__(self):
        self.colors = {c: 0 for c in CHANNELS}
        self.enabled = True
        self.schedule = {"name": "default", "ramps": [
            {"color": c, "points": [{"time": 0, "intensity": 0}, {"time": 420, "intensity": 600}]}
            for c in CHANNELS]}
        self.time = None
        self.lunar = {"enable": True, "start": 1200, "end": 240}

    def app(self):
        a = web.Application()
        a.router.add_get("/api/identity", self.identity)
        a.router.add_get("/api/colors", lambda r: web.json_response({**self.colors, "response_code": 0}))
        a.router.add_post("/api/colors", self.post_colors)
        a.router.add_get("/api/schedule/enable", lambda r: web.json_response({"enable": self.enabled, "response_code": 0}))
        a.router.add_put("/api/schedule/enable", self.put_enable)
        a.router.add_get("/api/schedule", lambda r: web.json_response({**self.schedule, "response_code": 0}))
        a.router.add_post("/api/schedule", self.post_schedule)
        a.router.add_post("/api/time", self.post_time)
        a.router.add_get("/api/schedule/lunar", lambda r: web.json_response({**self.lunar, "response_code": 0}))
        a.router.add_put("/api/schedule/lunar", self.put_lunar)
        return a

    async def identity(self, r):
        return web.json_response({"serial_number": "AABBCCDDEEFF", "parent": "", "firmware": "2.5.1",
                                  "product": "Prime", "response_code": 0})

    async def post_colors(self, r):
        body = await r.json()
        self.colors.update(body)
        return web.json_response({"response_code": 0})

    async def put_enable(self, r):
        # the real firmware reads the body regardless of content-type
        import json
        self.enabled = json.loads(await r.text())["enable"]
        return web.json_response({"response_code": 0})

    async def post_schedule(self, r):
        self.schedule = await r.json()
        return web.json_response({"response_code": 0})

    async def put_lunar(self, r):
        import json
        self.lunar = json.loads(await r.text())
        return web.json_response({"response_code": 0})

    async def post_time(self, r):
        self.time = await r.json()
        return web.json_response({"response_code": 0})


@pytest.fixture
async def light(aiohttp_client):
    fake = FakePrime()
    client = await aiohttp_client(fake.app())
    c = api.AquaIlluminationClient(client.session, f"{client.host}:{client.port}")
    return fake, c


async def test_identity_strips_response_code(light):
    _, c = light
    ident = await c.identity()
    assert ident["serial_number"] == "AABBCCDDEEFF"
    assert "response_code" not in ident


async def test_set_colors_roundtrip(light):
    fake, c = light
    levels = await c.colors()
    levels["deep_blue"] = api.percent_to_raw(50)
    await c.set_colors(levels)
    assert (await c.colors())["deep_blue"] == 500


async def test_schedule_enable_put(light):
    fake, c = light
    await c.set_schedule_enabled(False)
    assert fake.enabled is False and await c.schedule_enabled() is False


async def test_set_time_is_zero_based_month(light):
    fake, c = light
    await c.set_time("Australia/Adelaide", 2026, 9, 28, 14, 5)
    assert fake.time["month"] == 9 and fake.time["location"] == "Australia/Adelaide"


async def test_api_error_on_nonzero_code():
    class S:
        def request(self, *a, **k):
            return _Resp({"response_code": 5})

    class _Resp:
        def __init__(self, d): self.d = d
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def json(self, content_type=None): return self.d

    with pytest.raises(api.ApiError):
        await api.AquaIlluminationClient(S(), "x").colors()


async def test_cannot_connect():
    import aiohttp
    async with aiohttp.ClientSession() as s:
        with pytest.raises(api.CannotConnect):
            await api.AquaIlluminationClient(s, "127.0.0.1:1").identity()


def test_percent_conversions():
    assert api.percent_to_raw(100) == 1000 and api.percent_to_raw(150) == 1000
    assert api.percent_to_raw(-5) == 0 and api.percent_to_raw(0.5) == 5
    assert api.raw_to_percent(1500) == 100.0 and api.raw_to_percent(255) == 25.5


def test_validate_schedule_ok_and_errors():
    good = {"ramps": [{"color": c, "points": [{"time": 0, "intensity": 0}, {"time": 60, "intensity": 100}]}
                      for c in CHANNELS]}
    assert api.validate_schedule(good, CHANNELS)["name"] == "default"
    with pytest.raises(ValueError, match="missing"):
        api.validate_schedule({"ramps": good["ramps"][:3]}, CHANNELS)
    bad = {"ramps": [{"color": "nope", "points": []}]}
    with pytest.raises(ValueError, match="unknown"):
        api.validate_schedule(bad, CHANNELS)
    dup = {"ramps": [{"color": "uv", "points": [{"time": 5, "intensity": 0}, {"time": 5, "intensity": 0}]}]}
    with pytest.raises(ValueError, match="increase"):
        api.validate_schedule(dup, ["uv"])


async def test_lunar_roundtrip(light):
    fake, c = light
    assert (await c.lunar())["start"] == 1200
    await c.set_lunar(False, 1080, 300)
    assert fake.lunar == {"enable": False, "start": 1080, "end": 300}
