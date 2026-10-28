# Aqua Illumination for Home Assistant

Local, cloud-free control of **Aqua Illumination Prime** lights (verified on a
Prime 16, firmware 2.5.1) with a dashboard card. Wavemaker (Nero) support is
planned in the same repo — see [Roadmap](#roadmap).

> Unofficial. Not affiliated with Aqua Illumination / EcoTech Marine. The API
> was worked out from the myAI app and the community
> [AquaIPy](https://github.com/mcclown/AquaIPy) library (Apache-2.0).

## Install (HACS)
1. HACS → Integrations → ⋮ → Custom repositories → add this repo (category *Integration*).
2. Install, restart Home Assistant.
3. Settings → Devices & services → Add integration → **Aqua Illumination** → enter the light's IP.
   Give the light a DHCP reservation so the address never changes. For linked lights use the **parent**.

> HACS installs the latest **release**, not the branch — cut a release after changes.

## What you get (per light)
| Entity | |
|---|---|
| `number.<light>_<channel>` | each colour channel, 0–100 % |
| `switch.<light>_schedule` | the light's own schedule on/off |
| `switch.<light>_night_feeding` | manual mode, only red at 25 %; off restores the previous look and schedule |
| `switch.<light>_lunar_cycle`, `time.<light>_lunar_start` / `_end` | lunar mode: during the window the schedule's levels are *reduced* by moon phase (it adds no light — give the schedule a low night level for a "moon") |
| `sensor.<light>_temperature` | heatsink temperature (+ fan / thermal-shutdown attributes) |
| `sensor.<light>_schedule_data` | diagnostic; carries the ramps for the card |
| `sensor.<light>_device_clock`, `button.<light>_sync_clock`, `button.<light>_refresh` | clock tools |

Setting a channel **turns the light's schedule off** (as the vendor app does) — otherwise the
schedule overwrites your change within a minute. Turn the Schedule switch back on to resume.
The integration also keeps the light's clock right automatically (option).

## Card
Registered automatically. Add to a dashboard:
```yaml
type: custom:aqua-illumination-card
entity: sensor.ai_prime_0a82_schedule_data   # your light's "Schedule data" sensor
```
Shows the 24 h schedule with a "now" marker, live sliders per channel, and Schedule /
Night feeding / Sync clock buttons.

## Services
- `aqua_illumination.set_channels` — `levels: {blue: 40, deep_blue: 60}` (percent)
- `aqua_illumination.set_schedule` — `ramps: [{color, points: [{time: minutes, intensity: 0-1000}]}]`
  (every channel needs a ramp; times strictly increasing 0–1440)
- `aqua_illumination.set_lunar` — `enable`, `start`, `end` (lunar window; reduces schedule levels by moon phase)
- `aqua_illumination.sync_clock`

All take an `entity_id` of any entity belonging to the light.

## Roadmap
- Card schedule *editor* (currently read-only; edit via the `set_schedule` service).
- Wavemaker (Nero) cards in this repo, modelled on the Jebao pump cards. **Not started** — the app
  drives pumps through a separate "Director/Mobius" hub API (`/api/controller`, `/api/tanks`,
  `/api/groups`), and no pump hardware has been available to capture against.
- Storm / acclimation / stealth endpoints (not present on Prime 16 firmware 2.5.1 —
  `storm` and `acclimation` return 404 there).

## Status
Verified on real hardware: reads, channel writes, schedule read+write, schedule on/off, lunar mode, clock read/write.
**Not yet verified:** the HA entity layer on a running Home Assistant,
the card in a browser. See `CLAUDE.md`.

## Develop
```
python -m pytest -p no:socket -p no:homeassistant -q
```
