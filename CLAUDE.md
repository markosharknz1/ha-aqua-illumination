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

## v0.5.0 (local commit, not pushed/released)
Borrowed from the AIPAI project: night-light LAYER (night.py pure compose; coordinator keeps `day` layer + `night` config + `_written`, writes the composition; `_reconcile` adopts outside edits as the new day layer), overrides (`async_override`/`async_cancel_override`: lights_off + preview_levels, persisted + timer, restored after restart), preset import/export (presets.export_payload/parse_import), configurable night feeding (options level + channels), "Search my network" config flow (discovery.py), diagnostics.py, dashboard generator (dashboards/generate_dashboard.py), card: night sheet, lights-off, preview slider in editor (edits the DAY layer), export/import, visual config editor.
Presets/select identify via the DAY layer. Store load order matters: `async_load_store()` BEFORE first refresh (a save before load wiped stored data - found+fixed live). `presets.normalize` returns lists (tuples broke equality after the JSON round trip).
LIVE-VERIFIED (real coordinator in a bare HomeAssistant object + the Prime 16): scan finds the light, night compose write/readback identical, day layer untouched, no false external-change, preset+night, lights_off + restart rehydrate + timer restore, preview + cancel, all restored. Card behaviours tested in a real browser with a fake hass (ha-form editor only stub-tested). Tests 29 pass.
NOT exercised anywhere: the new config-flow steps (menu/search/pick), options flow with the channel multi-select, diagnostics download, services via the HA service layer, export_presets response.

## v0.6.0 card (local commit)
Card point designer modelled on the AIPAI card: time points, each with a time + a level per channel (sliders), drag-to-retime, add/delete, Copy to all, live preview via preview_levels, Save/Cancel; per-channel curve editor kept as "Per-channel curves". ramps<->points conversion is lossless (tested). Browser-tested with a fake hass. Both editors edit the DAY layer.

## v0.6.0 (local commit, not pushed/released) - card 0.7.0
Card locked by default (Edit/Done button, auto-relock after idle, `always_unlocked`, `lock_seconds`), slider tracks drawn by the card (accent-color blackened Cool White/Green), stub config picks a real light. BUG FIXED: the "Night feeding" chip and "Night light..." button shared data-act="night" so each fired both actions (shipped in v0.5.0/v0.5.1) - now "feed" vs "night". Found only by real mouse clicks; the earlier JS-click tests had hit the wrong element.

## v0.6.1 (local commit, not released)
`switch.<light>_all_lights` (AllLightsSwitch): on = lit/no hold, off = "lights_off" override; turn_on releases the hold and restores the previous look. Chosen so Feed and Water's snapshot/restore (switch channel: dim -> turn_off, restore -> turn_on) returns the light to its schedule instead of forcing full power. Live-verified on the Prime 16 incl. a night-red write while held, then restore.

## v0.6.2 (local commit, not released)
Icon: original artwork (reef light with 7 channel LEDs over coral, no vendor logo/text). Source `assets/icon.svg`; PNGs `assets/icon.png` + in-integration `custom_components/aqua_illumination/brand/icon.png` (256) and `icon@2x.png` (512) - HA 2026.3+ serves local brand images from the integration's brand folder - nothing else is needed (do NOT suggest a home-assistant/brands PR; the user has said that route is obsolete). Regenerate: Edge headless `--screenshot` of the SVG with `--default-background-color=00000000 --window-size=512,512`, then Pillow LANCZOS to 256.

## v0.7.0 (released) - version alignment
No code change from v0.6.2; integration version bumped to 0.7.0 to match card 0.7.0 (the user expected a "7" release). Card and integration versions are otherwise independent.

## v0.8.0 (local commit, not released) - card 0.8.0
Follow the moon: night config gains `follow_moon` + `moon_min`; moon.py now computes moonrise/moonset (low-precision lunar position, validated vs USNO api: rise/set within ~8 min, illumination within ~5 %) and `night_glow_window` (moon-up span inside the night hours); night.effective_night confines the glow to it and scales level by max(moon_min, illumination). Coordinator: `_compute_moon`/`async_refresh_moon`, daily tick at 12:00 local, takes over the light's lunar mode (turns it off, `lunar_restore` flag, restored when follow is turned off). Card Night light sheet: Follow the moon + info + minimum slider. Built-in presets now default night_glow False (the night layer is the proper glow). Live-verified on the Prime 16 (compose write/readback, lunar hand-over and restore, no-op refresh) and browser-tested with a fake hass. Tests 38 pass. Our scaling replaces the firmware's; the firmware's exact lunar scaling formula is unknown (app text only: Waxing Crescent turns 7 % blue into 1.4 %).

## v0.8.1 (local commit, not released) - card 0.8.1
Card: red "Schedule is OFF" banner + Turn on (inert while locked, hidden when lights are held off / preview running / offline); after Save to light (designer or per-channel) or Apply preset, if the schedule switch was off when the editor opened, confirm() offers to turn it on (state is snapshotted at editor open because a preview temporarily switches it off). Prompted by the user's light not following its saved schedule: the schedule had been left disabled after the earlier "switch the light off" request + test restores (light live-checked 2026-11-10: enabled False, colors 0, clock/schedule fine, reachable at the DHCP address). Browser-tested.

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
