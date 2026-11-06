"""Find lights on the local network by asking each address for its identity.

Pure helpers (no Home Assistant imports) so they can be unit-tested; the config
flow supplies the session and the networks to scan.
"""
from __future__ import annotations

import asyncio
import ipaddress
from typing import Any

import aiohttp

MAX_HOSTS = 1024  # never sweep more than a /22


def hosts_from_cidr(cidr: str, limit: int = MAX_HOSTS) -> list[str]:
    """Usable host addresses of a CIDR (a bare IP means that one host)."""
    net = ipaddress.ip_network(cidr.strip(), strict=False)
    if net.version != 4:
        raise ValueError("IPv4 only")
    if net.num_addresses > limit + 2:  # check before listing: a /8 is 16M addresses
        raise ValueError(f"{cidr} has {net.num_addresses} addresses; scan at most {limit}")
    return [str(h) for h in net.hosts()] or [str(net.network_address)]


def adapter_networks(adapters: list[dict[str, Any]]) -> list[str]:
    """Networks to scan from Home Assistant's adapter list: each enabled adapter's
    IPv4 subnet, capped at a /24 around the adapter's own address."""
    out: list[str] = []
    for ad in adapters:
        if not ad.get("enabled", True):
            continue
        for v4 in ad.get("ipv4", []):
            addr = v4.get("address")
            if not addr:
                continue
            ip = ipaddress.ip_address(addr)
            if ip.is_loopback or ip.is_link_local:
                continue
            prefix = max(int(v4.get("network_prefix", 24)), 24)
            net = str(ipaddress.ip_network(f"{addr}/{prefix}", strict=False))
            if net not in out:
                out.append(net)
    return out


async def _probe(session, host: str, timeout: float, sem, found: list) -> None:
    async with sem:
        try:
            async with session.get(
                f"http://{host}/api/identity", timeout=aiohttp.ClientTimeout(total=timeout)
            ) as resp:
                data = await resp.json(content_type=None)
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, OSError):
            return
    if isinstance(data, dict) and data.get("serial_number") and data.get("response_code", 0) == 0:
        found.append((host, data))


async def scan(
    session: aiohttp.ClientSession, hosts: list[str], timeout: float = 3.0,
    concurrency: int = 64,
) -> list[tuple[str, dict[str, Any]]]:
    """Return ``[(host, identity)]`` for every address that answers like a light,
    sorted by address. Child lights of a linked pair (``parent`` set) are kept so
    the caller can decide; the config flow hides them."""
    sem, found = asyncio.Semaphore(concurrency), []
    await asyncio.gather(*(_probe(session, h, timeout, sem, found) for h in hosts))
    return sorted(found, key=lambda r: tuple(int(p) if p.isdigit() else 0 for p in r[0].replace(":", ".").split(".")))
