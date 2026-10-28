"""Async client for the Aqua Illumination Prime local HTTP API.

Reverse-engineered from the myAI Android app (com.aquaillumination.prime) and
cross-checked against mcclown/AquaIPy (Apache-2.0) and a live Prime 16 on
firmware 2.5.1. Every endpoint lives under ``http://<host>/api`` and returns a
JSON object carrying ``response_code`` (0 = success).

This module has no Home Assistant imports so it can be tested on its own.
"""
from __future__ import annotations

import asyncio
from typing import Any

import aiohttp

REQUEST_TIMEOUT = 15


class AquaIlluminationError(Exception):
    """Base error."""


class CannotConnect(AquaIlluminationError):
    """The light did not answer."""


class ApiError(AquaIlluminationError):
    """The light answered with a non-zero response_code."""

    def __init__(self, path: str, code: Any) -> None:
        super().__init__(f"{path} returned response_code {code}")
        self.path = path
        self.code = code


class AquaIlluminationClient:
    """Thin wrapper over the light's REST API."""

    def __init__(self, session: aiohttp.ClientSession, host: str) -> None:
        self._session = session
        self.host = host

    @property
    def base(self) -> str:
        return f"http://{self.host}/api"

    async def _request(
        self, method: str, path: str, body: dict | None = None
    ) -> dict[str, Any]:
        url = f"{self.base}/{path}"
        try:
            async with asyncio.timeout(REQUEST_TIMEOUT):
                async with self._session.request(
                    method, url, json=body if method == "POST" else None,
                    data=None if method != "PUT" else _json(body),
                ) as resp:
                    data = await resp.json(content_type=None)
        except (aiohttp.ClientError, TimeoutError, ValueError) as err:
            raise CannotConnect(f"{self.host}: {err!r}") from err
        if not isinstance(data, dict):
            raise ApiError(path, "not-json-object")
        if data.get("response_code", 0) != 0:
            raise ApiError(path, data.get("response_code"))
        data.pop("response_code", None)
        return data

    # -- reads ---------------------------------------------------------
    async def identity(self) -> dict[str, Any]:
        return await self._request("GET", "identity")

    async def power(self) -> dict[str, Any]:
        return await self._request("GET", "power")

    async def colors(self) -> dict[str, int]:
        """Per-channel intensity, 0-1000 (1000-2000 = HD overdrive)."""
        return await self._request("GET", "colors")

    async def schedule(self) -> dict[str, Any]:
        return await self._request("GET", "schedule")

    async def schedule_enabled(self) -> bool:
        return bool((await self._request("GET", "schedule/enable"))["enable"])

    async def time(self) -> dict[str, Any]:
        return await self._request("GET", "time")

    async def temperature(self) -> dict[str, Any]:
        return await self._request("GET", "temperature")

    async def lunar(self) -> dict[str, Any] | None:
        """Moonlight window: {enable, start, end} (minutes since midnight).

        Not every firmware has it (404 -> ApiError/CannotConnect); callers treat
        a failure as "no lunar support".
        """
        return await self._request("GET", "schedule/lunar")

    async def stealth(self) -> dict[str, Any]:
        return await self._request("GET", "stealth")

    # -- writes --------------------------------------------------------
    async def set_colors(self, levels: dict[str, int]) -> None:
        """Set channels. The firmware wants every channel, so callers merge."""
        await self._request("POST", "colors", levels)

    async def set_schedule_enabled(self, enable: bool) -> None:
        await self._request("PUT", "schedule/enable", {"enable": enable})

    async def set_schedule(self, schedule: dict[str, Any]) -> None:
        await self._request("POST", "schedule", schedule)

    async def set_time(
        self, location: str, year: int, month0: int, day: int,
        hours: int, minutes: int,
    ) -> None:
        """Set the wall clock. ``month0`` is 0-based (January = 0)."""
        await self._request("POST", "time", {
            "location": location, "seconds": 0, "minutes": minutes,
            "hours": hours, "day": day, "month": month0, "year": year,
        })

    async def set_lunar(self, enable: bool, start: int, end: int) -> None:
        await self._request("PUT", "schedule/lunar",
                            {"enable": enable, "start": start, "end": end})

    async def reboot(self) -> None:
        await self._request("PUT", "reboot", {})


def _json(body: dict | None) -> str:
    import json

    return json.dumps(body if body is not None else {})


def percent_to_raw(percent: float) -> int:
    """0-100 % -> 0-1000 (the HD range above 100 % is not exposed)."""
    return max(0, min(1000, round(percent * 10)))


def raw_to_percent(raw: int) -> float:
    """0-2000 -> percent; HD overdrive reads as 100 %."""
    return round(min(raw, 1000) / 10, 1)


def validate_schedule(schedule: dict[str, Any], channels: list[str]) -> dict[str, Any]:
    """Return a clean schedule dict or raise ValueError.

    Shape: ``{"name": str, "ramps": [{"color": ch, "points": [{"time": minute,
    "intensity": 0-1000}, ...]}]}`` - times in minutes since midnight, strictly
    increasing, one ramp per channel.
    """
    ramps = schedule.get("ramps")
    if not isinstance(ramps, list) or not ramps:
        raise ValueError("schedule needs a non-empty 'ramps' list")
    seen: set[str] = set()
    clean = []
    for ramp in ramps:
        color = ramp.get("color")
        if color not in channels:
            raise ValueError(f"unknown channel {color!r}")
        if color in seen:
            raise ValueError(f"duplicate ramp for {color}")
        seen.add(color)
        last = -1
        points = []
        for pt in ramp.get("points", []):
            t, i = int(pt["time"]), int(pt["intensity"])
            if not 0 <= t <= 1440 or t <= last:
                raise ValueError(f"{color}: times must increase within 0-1440")
            if not 0 <= i <= 1000:
                raise ValueError(f"{color}: intensity must be 0-1000")
            last = t
            points.append({"time": t, "intensity": i})
        if len(points) < 2:
            raise ValueError(f"{color}: needs at least 2 points")
        clean.append({"color": color, "points": points})
    missing = set(channels) - seen
    if missing:
        raise ValueError(f"missing ramps for: {', '.join(sorted(missing))}")
    return {"name": schedule.get("name", "default"), "ramps": clean}
