#!/usr/bin/env python3
"""Generate a Lovelace dashboard (YAML) for one or more Aqua Illumination lights.

Usage:
    python dashboards/generate_dashboard.py ai_prime_0a82 [ai_reef_2] --title "Reef lights" > aqua.yaml

Each argument is the light's entity prefix: the part of its "Schedule data"
sensor id between "sensor." and "_schedule_data" (so sensor.ai_prime_0a82_schedule_data
-> ai_prime_0a82). Paste the output into a dashboard's raw configuration editor
(Edit dashboard > three dots > Raw configuration editor), or save it as a YAML-mode
dashboard. No third-party packages needed.
"""
from __future__ import annotations

import argparse
import sys


def light_cards(prefix: str, name: str | None = None) -> list[str]:
    """YAML lines (a block of list items) for one light's cards."""
    title = name or prefix.replace("_", " ").title()
    return [
        "      - type: custom:aqua-illumination-card",
        f"        entity: sensor.{prefix}_schedule_data",
        f"        name: {title}",
        "      - type: entities",
        f"        title: {title} controls",
        "        show_header_toggle: false",
        "        entities:",
        f"          - switch.{prefix}_schedule",
        f"          - select.{prefix}_schedule_preset",
        f"          - switch.{prefix}_night_light",
        f"          - switch.{prefix}_night_feeding",
        f"          - switch.{prefix}_lights_off",
        f"          - switch.{prefix}_lunar_cycle",
        f"          - sensor.{prefix}_moon_phase",
        f"          - binary_sensor.{prefix}_connection",
        "      - type: history-graph",
        f"        title: {title} temperature and power",
        "        hours_to_show: 24",
        "        entities:",
        f"          - sensor.{prefix}_temperature",
        f"          - sensor.{prefix}_power_draw_estimated",
    ]


def dashboard(prefixes: list[str], title: str = "Aquarium lights") -> str:
    lines = [f"title: {title}", "views:", f"  - title: {title}", "    path: aqua", "    icon: mdi:fishbowl-outline", "    cards:"]
    if len(prefixes) == 1:
        lines += light_cards(prefixes[0])
    else:
        for prefix in prefixes:
            lines += [
                "      - type: vertical-stack",
                "        cards:",
            ]
            # nest the light's cards one level deeper
            lines += ["    " + ln for ln in light_cards(prefix)]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("prefix", nargs="+", help="light entity prefix, e.g. ai_prime_0a82")
    ap.add_argument("--title", default="Aquarium lights")
    args = ap.parse_args(argv)
    sys.stdout.write(dashboard(args.prefix, args.title))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
