# ha-aqua-illumination — project state

HACS integration `aqua_illumination` for Aqua Illumination Prime lights + Lovelace card; wavemakers planned.
Owner's light: **AI Prime 16** at <light-ip>, serial <serial>, fw 2.5.1, 7 channels
(deep_red uv deep_blue violet cool_white green blue), time zone Australia/Adelaide.

## Protocol (confirmed live on the light)
Plain HTTP+JSON `http://<ip>/api/<path>`, every reply has `response_code` (0 ok). No auth needed on this unit.
GET identity, power, colors, schedule, schedule/enable, schedule/minute, time, temperature, stealth.
POST colors (all channels, 0-1000), POST schedule `{name, ramps:[{color, points:[{time(min),intensity}]}]}` (verified live),
PUT schedule/enable `{enable}` (body read regardless of content-type), POST time (`month` is 0-based, verified).
GET/PUT schedule/lunar `{enable,start,end}` (minutes; verified live). Lunar only REDUCES scheduled night levels by moon phase (app help text) - no night level in the schedule = nothing visible. POST schedule VERIFIED live (fw drops a trailing 1440 point). 404 on this fw: storm, acclimation. First connection after idle can take ~5 s (client timeout is 15 s).
Source: myAI 3.25 APK (jadx; `comm/PrimeRequests/*`), AquaIPy.

## Done (v0.1.0, uncommitted-to-GitHub)
api.py (pure client), coordinator.py, config_flow (host + options), number/switch/sensor/button, services,
card, panel.py auto-registration. Tests: `python -m pytest -p no:socket -p no:homeassistant -q` (9 pass; fake light server).
All modules import against HA 2025.1.4. Live: reads, channel write, schedule POST, schedule on/off, lunar, set_time; user confirmed light output + overnight blue visible.

## v0.2.0 (local commit, not released)
Dropout detection: pure `dropout.py` tracker (2 failed polls = offline, one miss keeps last state), `binary_sensor.<light>_connection`, card offline banner/greyed controls/last-chart cache. Tests 12 pass; card render checked in node with stub DOM only (not a browser, not live HA).

## v0.3.0 (released) + v0.4.0 (local commit, not pushed/released)
v0.3.0: dropout events + persistent notification, moon sensor, presets (select + Store + services), copy_schedule, multi-light services, power-draw sensor, card point editor + preset UI.
v0.4.0: DHCP discovery (manifest `dhcp` MAC D89760*; config_flow `async_step_dhcp` updates the saved host for a known serial - the light DID change IP, .67 -> .50, on 2026-11-07), stealth (api.set_stealth, coordinator poll + async_set_stealth, diagnostic sensor, `set_stealth` service), preset select now identifies by comparing ramps (firmware ignores the schedule name and always reports "default").
LIVE-VERIFIED 2026-11-07 on the Prime 16 (new DHCP address): `power` shape (`normal` per-channel mW, max 40 W), stealth GET/PUT `{enable,dim,intensity(0-1000),suspend(ms)}`, preset schedule writes read back identical, restore of the original schedule, coordinator `_poll`, preset apply/save/delete, stealth set, sensors, via real coordinator code in a bare HomeAssistant object (not a running HA). Tests 17 pass.
The light's schedule is currently the user's overnight-blue one (backup: C:/Claude/ai-prime-backup\schedule-before-v030-test.json), schedule DISABLED, all channels 0.

## NOT verified
Entity layer on a running HA (platform setup, registry, dhcp step); card against real HA; night-feeding restore across a restart;
`power`-endpoint HD overdrive (>100 %) not exposed.

## Next
1. Install on the owner's HA, fix what breaks (their prior integrations always had 1-2 real-HA bugs).
2. Verify schedule POST with a self-restoring probe.
3. Card schedule editor (see aquarium-light-re `lovelace/aipai-reef-card.js` for the pattern).
4. Wavemakers: need hardware + capture; app uses Director/Mobius `/api/controller|tanks|groups`.
5. GitHub repo markosharknz1/ha-aqua-illumination — user confirms pushes; HACS needs a *release*;
   token lacks `workflow` scope (park CI in `ci/`).
