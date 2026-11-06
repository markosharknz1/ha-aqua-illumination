/* Aqua Illumination card - shows a Prime light's schedule, live levels and controls.
 *
 *   type: custom:aqua-illumination-card
 *   entity: sensor.ai_prime_0a82_schedule_data   # the "Schedule data" sensor
 *   name: Reef            # optional
 *
 * Every other entity is derived from the sensor's name, so one line is enough.
 */
const CARD_VERSION = "0.6.0";
const BUILTIN_PRESETS = ["Standard day", "Coral growth", "Acclimation (gentle)"];

const COLORS = {
  deep_red: "#b3202a", red: "#e03a3a", far_red: "#8a1c1c", uv: "#8f5bff",
  violet: "#a06bd6", deep_blue: "#2740c9", blue: "#3b82f6", royal: "#2f5bd6",
  cool_white: "#d8e4f0", neutral_white: "#e8e2cf", warm_white: "#f1d9a0",
  green: "#3fb26b",
};
// Linear interpolation of a ramp, flat before the first / after the last point (same as the integration).
const valueAt = (pts, m) => {
  if (!pts.length) return 0;
  if (m <= pts[0].time) return pts[0].intensity;
  for (let i = 1; i < pts.length; i++) {
    if (m <= pts[i].time) {
      const a = pts[i - 1], b = pts[i], span = b.time - a.time;
      return span <= 0 ? b.intensity : a.intensity + ((b.intensity - a.intensity) * (m - a.time)) / span;
    }
  }
  return pts[pts.length - 1].intensity;
};
const hhmm = (m) => `${String(Math.floor(m / 60)).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`;
const LABEL = (k) => k.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());

class AquaIlluminationCard extends HTMLElement {
  setConfig(config) {
    if (!config.entity || !config.entity.endsWith("_schedule_data")) {
      throw new Error("Set 'entity' to the light's 'Schedule data' sensor (…_schedule_data)");
    }
    this._config = config;
    this._prefix = config.entity.split(".")[1].replace(/_schedule_data$/, "");
    if (!this._root) {
      this._root = this.attachShadow({ mode: "open" });
      this._root.innerHTML = `<style>${AquaIlluminationCard.css}</style><ha-card></ha-card>`;
      this._card = this._root.querySelector("ha-card");
    }
  }

  getCardSize() { return 8; }
  static getConfigElement() { return document.createElement("aqua-illumination-card-editor"); }
  // Start the picker on a real light when there is one (hass is passed in by the dashboard editor).
  static getStubConfig(hass) {
    const real = hass && Object.keys(hass.states || {}).find((id) => /^sensor\..+_schedule_data$/.test(id)
      && hass.states[id].attributes && "day_ramps" in hass.states[id].attributes);
    return { entity: real || "sensor.ai_prime_0000_schedule_data" };
  }

  set hass(hass) {
    this._hass = hass;
    // Don't rebuild while the user is dragging a slider.
    // ...or while the schedule editor is open (it draws itself).
    if (this._dragging || this._edit || this._sheet || this._dz) return;
    this._render();
  }

  _e(domain, suffix) { return this._hass.states[`${domain}.${this._prefix}_${suffix}`]; }

  _channels() {
    const out = [];
    for (const id of Object.keys(this._hass.states)) {
      if (!id.startsWith(`number.${this._prefix}_`)) continue;
      out.push({ key: id.slice(`number.${this._prefix}_`.length), id });
    }
    return out;
  }

  _render() {
    const sched = this._hass.states[this._config.entity];
    if (!sched) {
      this._card.innerHTML = `<div class="pad warn">Entity ${this._config.entity} not found</div>`;
      return;
    }
    // Dropout detection: the Connection sensor stays available while the
    // light is down; fall back to "unavailable" states for older installs.
    const conn = this._e("binary_sensor", "connection");
    const ca = (conn && conn.attributes) || {};
    const offline = conn
      ? conn.state === "off"
      : [sched.state, (this._e("switch", "schedule") || {}).state].includes("unavailable");
    // Entities blank out while offline - keep the last good schedule for the chart.
    if ((sched.attributes.ramps || []).length) this._lastRamps = sched.attributes.ramps;
    if ((sched.attributes.day_ramps || []).length) this._lastDay = sched.attributes.day_ramps;
    const night = sched.attributes.night || {};
    const lightsOff = this._e("switch", "lights_off");
    const ramps = sched.attributes.ramps || this._lastRamps || [];
    const temp = this._e("sensor", "temperature");
    const clock = this._e("sensor", "device_clock");
    const schedSw = this._e("switch", "schedule");
    const nightSw = this._e("switch", "night_feeding");
    const chans = this._channels();
    const moon = this._e("sensor", "moon_phase");
    const presetSel = this._e("select", "schedule_preset");

    // "now" marker: minutes since midnight from the light's own clock.
    let nowMin = null;
    if (clock && /\d\d:\d\d$/.test(clock.state || "")) {
      const [h, m] = clock.state.slice(-5).split(":").map(Number);
      nowMin = h * 60 + m;
    }

    const title = this._config.name || (sched.attributes.friendly_name || "").replace(/ Schedule data$/, "");
    this._card.innerHTML = `
      <div class="pad">
        <div class="head">
          <div class="title">${title}</div>
          <div class="meta">${moon && moon.state !== "unavailable" ? `🌙 ${LABEL(moon.state)} ${moon.attributes.illumination}%  ` : ""}${temp && temp.state !== "unavailable" ? temp.state + " °C" : ""}</div>
        </div>
        ${offline ? `<div class="warn">⚠ Light offline${ca.offline_since ? " for " + this._ago(ca.offline_since) : ""} — check its power and WiFi${ca.dropouts ? ` · ${ca.dropouts} dropout${ca.dropouts > 1 ? "s" : ""} this session` : ""}</div>` : ""}
        <div class="toggles ${offline ? "off" : ""}">
          <button class="chip ${schedSw && schedSw.state === "on" ? "on" : ""}" data-act="schedule">Schedule ${schedSw ? schedSw.state : "?"}</button>
          <button class="chip ${nightSw && nightSw.state === "on" ? "on" : ""}" data-act="night">Night feeding</button>
          <button class="chip" data-act="clock">Sync clock</button>
        </div>
        <div class="${offline ? "off" : ""}">${this._chart(ramps, nowMin)}</div>
        <div class="presets ${offline ? "off" : ""}">
          ${presetSel ? `<select data-preset>${(presetSel.attributes.options || []).map((o) =>
            `<option ${o === presetSel.state ? "selected" : ""}>${o}</option>`).join("")}</select>
            <button class="chip" data-act="apply">Apply</button>` : ""}
          <button class="chip" data-act="edit">Edit schedule</button>
          <button class="chip" data-act="save">Save as preset…</button>
        </div>
        <div class="presets ${offline ? "off" : ""}">
          <button class="chip ${night.enable ? "on" : ""}" data-act="night">Night light${night.enable ? " on" : ""}</button>
          ${lightsOff ? `<button class="chip ${lightsOff.state === "on" ? "on" : ""}" data-act="off">${lightsOff.state === "on" ? "Resume" : "Lights off…"}</button>` : ""}
          <button class="chip" data-act="export">Export presets</button>
          <button class="chip" data-act="import">Import…</button>
        </div>
        <div class="sliders ${offline ? "off" : ""}">
          ${chans.map((c) => this._slider(c)).join("")}
        </div>
        <div class="foot">${offline
          ? `Last seen ${ca.last_seen ? this._ago(ca.last_seen) + " ago" : "never"}${ca.last_error ? " · " + ca.last_error : ""}`
          : `Clock: ${clock ? clock.state : "?"}${ca.dropouts ? ` · ${ca.dropouts} dropout${ca.dropouts > 1 ? "s" : ""}${ca.last_outage_seconds ? ` (last ${this._dur(ca.last_outage_seconds)})` : ""}` : ""}`} · v${CARD_VERSION}</div>
      </div>`;
    this._wire();
  }

  // ---- point designer: every channel at each time point --------------------
  // The schedule is a list of time points; each point has a time and a level for
  // every channel, and the light fades between points. Selecting or editing a
  // point previews it on the light; nothing is kept until "Save to light"
  // (Cancel puts the light back).
  _pointsFromRamps(ramps, name) {
    const colors = ramps.map((r) => r.color);
    const times = new Set([0, 1439]);
    ramps.forEach((r) => r.points.forEach((p) => times.add(Math.min(p.time, 1439))));
    const pts = [...times].sort((a, b) => a - b).map((t) => ({
      time: t, ch: Object.fromEntries(ramps.map((r) => [r.color, Math.round(valueAt(r.points, t))])),
    }));
    return { colors, pts, sel: null, live: true, name: name || "default" };
  }

  _rampsFromPoints(dz) {
    return dz.colors.map((c) => ({ color: c, points: dz.pts.map((p) => ({ time: p.time, intensity: p.ch[c] })) }));
  }

  _startDesigner() {
    const ramps = this._lastDay || this._lastRamps || [];
    if (!ramps.length) { alert("No schedule loaded yet."); return; }
    const sched = this._hass.states[this._config.entity];
    this._dz = this._pointsFromRamps(ramps, sched && sched.state);
    this._renderDesigner();
  }

  _renderDesigner() {
    const dz = this._dz, sel = dz.sel === null ? null : dz.pts[dz.sel];
    const edge = sel && (dz.sel === 0 || dz.sel === dz.pts.length - 1);
    this._card.innerHTML = `<div class="pad">
      <div class="head"><div class="title">Schedule designer</div><div class="meta">${dz.name}</div></div>
      <svg viewBox="0 0 360 170" class="chart edit" data-dzchart></svg>
      <div class="presets">
        <button class="chip ${dz.live ? "on" : ""}" data-dz="live">Live preview ${dz.live ? "on" : "off"}</button>
        ${this._prevActive ? `<button class="chip" data-dz="endprev">End preview</button>` : ""}
        <span class="foot" style="margin:0">Tap a marker to edit it · drag it sideways to retime · tap empty space to add a point</span>
      </div>
      ${sel ? `<div class="presets"><span>Point at</span>
          <input type="time" data-dztime value="${hhmm(sel.time)}" ${edge ? "disabled" : ""}>
          <button class="chip" data-dz="copy" title="Give every other point these levels">Copy to all</button>
          <button class="chip" data-dz="del" ${edge ? "disabled" : ""}>Delete point</button></div>
        <div class="sliders">${dz.colors.map((c) => `<label class="row">
          <span class="dot" style="background:${COLORS[c] || "#888"}"></span><span class="lbl">${LABEL(c)}</span>
          <input type="range" min="0" max="100" step="0.5" value="${sel.ch[c] / 10}" data-dzch="${c}" style="accent-color:${COLORS[c] || "#888"}">
          <span class="val">${sel.ch[c] / 10}%</span></label>`).join("")}</div>`
        : `<div class="foot">Select a point to set all channels at that time.</div>`}
      <div class="toggles">
        <button class="chip on" data-dz="save">Save to light</button>
        <button class="chip" data-dz="cancel">Cancel</button>
        <button class="chip" data-dz="curves">Per-channel curves</button>
      </div></div>`;
    this._drawDesigner();
    const q = (x) => this._card.querySelector(x);
    this._card.querySelectorAll("[data-dz]").forEach((b) => {
      b.onclick = () => this._dzAction(b.dataset.dz);
    });
    const ti = q("[data-dztime]");
    if (ti) {
      ti.onchange = () => {
        if (!ti.value) return;
        const [h, m] = ti.value.split(":").map(Number);
        const lo = dz.pts[dz.sel - 1].time + 1, hi = dz.pts[dz.sel + 1].time - 1;
        sel.time = Math.max(lo, Math.min(hi, h * 60 + m));
        ti.value = hhmm(sel.time);
        this._drawDesigner();
      };
    }
    this._card.querySelectorAll("[data-dzch]").forEach((inp) => {
      const val = inp.parentElement.querySelector(".val");
      inp.oninput = () => {
        sel.ch[inp.dataset.dzch] = Math.round(Number(inp.value) * 10);
        val.textContent = `${inp.value}%`;
        this._drawDesigner();
        this._dzPreview();
      };
    });
    this._wireDesignerChart();
  }

  _drawDesigner() {
    const dz = this._dz, W = 360, H = 170, TOP = 22, PLOT = H - TOP - 14;
    const x = (t) => 8 + (t / 1440) * (W - 16), y = (i) => TOP + PLOT - (Math.min(i, 1000) / 1000) * PLOT;
    let g = "";
    for (let h = 0; h <= 24; h += 3) {
      g += `<line x1="${x(h * 60)}" x2="${x(h * 60)}" y1="${TOP}" y2="${TOP + PLOT}" class="grid"/><text x="${x(h * 60) + 2}" y="${H - 3}" class="tick">${String(h).padStart(2, "0")}</text>`;
    }
    for (const c of dz.colors) {
      const d = dz.pts.map((p, n) => `${n ? "L" : "M"}${x(p.time).toFixed(1)},${y(p.ch[c]).toFixed(1)}`).join(" ");
      g += `<path d="${d}" fill="none" stroke="${COLORS[c] || "#888"}" stroke-width="1.8" opacity="0.9"/>`;
    }
    dz.pts.forEach((p, n) => {
      const on = n === dz.sel;
      g += `<line x1="${x(p.time)}" x2="${x(p.time)}" y1="${TOP}" y2="${TOP + PLOT}" stroke="var(--primary-color)" stroke-width="${on ? 1.5 : 0.7}" stroke-dasharray="3 2" opacity="${on ? 1 : 0.4}"/>`
        + `<circle cx="${x(p.time)}" cy="11" r="${on ? 7 : 5.5}" fill="${on ? "var(--primary-color)" : "var(--card-background-color,#fff)"}" stroke="var(--primary-color)" stroke-width="2"/>`;
    });
    this._card.querySelector("[data-dzchart]").innerHTML = g;
  }

  _wireDesignerChart() {
    const svg = this._card.querySelector("[data-dzchart]"), dz = this._dz, W = 360;
    const tAt = (ev) => {
      const b = svg.getBoundingClientRect(), k = b.width / W;
      return { t: (((ev.clientX - b.left) / k - 8) / (W - 16)) * 1440, k };
    };
    let drag = null;
    svg.onpointerdown = (ev) => {
      const { t, k } = tAt(ev);
      let best = -1, bd = 1e9;
      dz.pts.forEach((p, n) => { const d = Math.abs(((p.time - t) / 1440) * (W - 16) * k); if (d < bd) { bd = d; best = n; } });
      if (bd > 12) {  // empty space: add a point here with the levels the curve already has
        const tt = Math.max(1, Math.min(1438, Math.round(t / 5) * 5));
        if (dz.pts.some((p) => p.time === tt)) return;
        const ch = Object.fromEntries(dz.colors.map((c) => [c, Math.round(valueAt(dz.pts.map((p) => ({ time: p.time, intensity: p.ch[c] })), tt))]));
        dz.pts.push({ time: tt, ch });
        dz.pts.sort((a, b) => a.time - b.time);
        best = dz.pts.findIndex((p) => p.time === tt);
      }
      dz.sel = best; drag = best;
      svg.setPointerCapture(ev.pointerId);
      this._drawDesigner();
    };
    svg.onpointermove = (ev) => {
      if (drag === null || drag === 0 || drag === dz.pts.length - 1) return;
      const { t } = tAt(ev), p = dz.pts[drag];
      const nt = Math.max(dz.pts[drag - 1].time + 1, Math.min(dz.pts[drag + 1].time - 1, Math.round(t / 5) * 5));
      if (nt !== p.time) { p.time = nt; this._drawDesigner(); }
    };
    const end = () => { if (drag !== null) { drag = null; this._renderDesigner(); this._dzPreview(); } };
    svg.onpointerup = end;
    svg.onpointercancel = end;
  }

  _dzPreview() {
    const dz = this._dz;
    if (!dz || !dz.live || dz.sel === null) return;
    clearTimeout(this._dzTimer);
    this._dzTimer = setTimeout(async () => {
      const p = dz.pts[dz.sel];
      if (!p) return;
      const levels = Object.fromEntries(dz.colors.map((c) => [c, p.ch[c] / 10]));
      try {
        await this._hass.callService("aqua_illumination", "preview_levels", { entity_id: this._config.entity, levels, duration: 10 });
        if (!this._prevActive) { this._prevActive = true; if (this._dz) this._renderDesigner(); }
      } catch (err) { dz.live = false; alert(`Preview failed: ${err.message || err}`); this._renderDesigner(); }
    }, 350);
  }

  async _dzAction(a) {
    const dz = this._dz;
    if (a === "live") {
      dz.live = !dz.live;
      if (!dz.live) await this._endPreview(); else this._dzPreview();
      this._renderDesigner();
    }
    if (a === "endprev") { await this._endPreview(); this._renderDesigner(); }
    if (a === "copy" && dz.sel !== null) {
      const src = dz.pts[dz.sel].ch;
      dz.pts.forEach((p) => { p.ch = { ...src }; });
      this._renderDesigner();
    }
    if (a === "del" && dz.sel !== null && dz.sel > 0 && dz.sel < dz.pts.length - 1) {
      dz.pts.splice(dz.sel, 1); dz.sel = null; this._renderDesigner();
    }
    if (a === "cancel") { clearTimeout(this._dzTimer); await this._endPreview(); this._dz = null; this._render(); }
    if (a === "curves") {
      clearTimeout(this._dzTimer);
      const ramps = this._rampsFromPoints(dz);
      this._dz = null;
      this._edit = { ramps, sel: ramps[0].color, pt: null, name: dz.name };
      this._renderEdit();
    }
    if (a === "save") {
      clearTimeout(this._dzTimer);
      if (dz.pts.length < 2) { alert("Need at least 2 points."); return; }
      const ramps = this._rampsFromPoints(dz);
      try {
        await this._hass.callService("aqua_illumination", "set_schedule", { entity_id: this._config.entity, name: dz.name, ramps });
      } catch (err) { alert(`Could not save: ${err.message || err}`); return; }
      this._lastDay = ramps;
      await this._endPreview();
      this._dz = null;
      this._render();
    }
  }

  // ---- schedule editor ------------------------------------------------
  _startEdit() {
    const ramps = (this._lastDay || this._lastRamps || []).map((r) => ({
      color: r.color, points: (r.points || []).map((p) => ({ time: p.time, intensity: p.intensity })),
    }));
    if (!ramps.length) { alert("No schedule loaded yet."); return; }
    const sched = this._hass.states[this._config.entity];
    this._edit = { ramps, sel: ramps[0].color, pt: null, name: (sched && sched.state) || "default" };
    this._renderEdit();
  }

  _editRamp() { return this._edit.ramps.find((r) => r.color === this._edit.sel); }

  _renderEdit() {
    const e = this._edit, r = this._editRamp();
    const canDel = e.pt !== null && e.pt > 0 && e.pt < r.points.length - 1;
    this._card.innerHTML = `<div class="pad">
      <div class="head"><div class="title">Edit schedule</div><div class="meta">${e.name}</div></div>
      <div class="toggles">${e.ramps.map((x) => `<button class="chip ${x.color === e.sel ? "on" : ""}" data-sel="${x.color}"
        style="${x.color === e.sel ? `background:${COLORS[x.color] || "#888"};border-color:${COLORS[x.color] || "#888"}` : ""}">${LABEL(x.color)}</button>`).join("")}</div>
      <svg viewBox="0 0 360 150" class="chart edit" data-chart></svg>
      <div class="presets">
        <span>Preview on light at</span>
        <input type="range" min="0" max="1439" step="5" value="${e.prevAt ?? 720}" data-prev style="flex:1">
        <span data-prevt>${hhmm(e.prevAt ?? 720)}</span>
        ${this._prevActive ? `<button class="chip on" data-edit="endprev">End preview</button>` : ""}
      </div>
      <div class="foot" data-pt>${e.pt !== null ? this._pointText() : "Drag a point · click empty space to add one"}</div>
      <div class="toggles">
        <button class="chip" data-edit="del" ${canDel ? "" : "disabled"}>Delete point</button>
        <button class="chip" data-edit="designer">Point designer</button>
        <button class="chip on" data-edit="save">Save to light</button>
        <button class="chip" data-edit="cancel">Cancel</button>
      </div></div>`;
    this._drawEdit();
    this._card.querySelectorAll("[data-sel]").forEach((b) => {
      b.onclick = () => { e.sel = b.dataset.sel; e.pt = null; this._renderEdit(); };
    });
    this._card.querySelectorAll("[data-edit]").forEach((b) => {
      b.onclick = () => {
        const a = b.dataset.edit;
        if (a === "cancel") { this._endPreview().then(() => { this._edit = null; this._render(); }); }
        if (a === "del" && canDel) { r.points.splice(e.pt, 1); e.pt = null; this._renderEdit(); }
        if (a === "save") this._saveEdit();
        if (a === "endprev") this._endPreview().then(() => this._renderEdit());
        if (a === "designer") {
          this._dz = this._pointsFromRamps(e.ramps, e.name);
          this._edit = null;
          this._renderDesigner();
        }
      };
    });
    const pv = this._card.querySelector("[data-prev]");
    if (pv) {
      pv.oninput = () => { this._card.querySelector("[data-prevt]").textContent = hhmm(Number(pv.value)); };
      pv.onchange = async () => {
        e.prevAt = Number(pv.value);
        const levels = {};
        for (const r of e.ramps) levels[r.color] = Math.round(valueAt(r.points, e.prevAt)) / 10;
        try {
          await this._hass.callService("aqua_illumination", "preview_levels", {
            entity_id: this._config.entity, levels, duration: 10 });
          if (!this._prevActive) { this._prevActive = true; this._renderEdit(); }
        } catch (err) { alert(`Preview failed: ${err.message || err}`); }
      };
    }
    this._wireChart();
  }

  _drawEdit() {
    const e = this._edit, W = 360, H = 150;
    const x = (t) => (t / 1440) * W, y = (i) => H - 14 - (i / 1000) * (H - 22);
    const svg = this._card.querySelector("[data-chart]");
    let g = "";
    for (let h = 0; h <= 24; h += 3) {
      g += `<line x1="${x(h * 60)}" x2="${x(h * 60)}" y1="0" y2="${H - 14}" class="grid"/><text x="${x(h * 60) + 2}" y="${H - 3}" class="tick">${String(h).padStart(2, "0")}</text>`;
    }
    for (const r of e.ramps) {
      const sel = r.color === e.sel;
      const d = r.points.map((q, n) => `${n ? "L" : "M"}${x(q.time).toFixed(1)},${y(q.intensity).toFixed(1)}`).join(" ");
      g += `<path d="${d}" fill="none" stroke="${COLORS[r.color] || "#888"}" stroke-width="${sel ? 2.4 : 1}" opacity="${sel ? 1 : 0.25}"/>`;
    }
    this._editRamp().points.forEach((q, n) => {
      g += `<circle cx="${x(q.time)}" cy="${y(q.intensity)}" r="${n === e.pt ? 6 : 4.5}" fill="${n === e.pt ? "var(--primary-color)" : "var(--card-background-color,#fff)"}" stroke="${COLORS[e.sel] || "#888"}" stroke-width="2"/>`;
    });
    svg.innerHTML = g;
  }

  _wireChart() {
    const svg = this._card.querySelector("[data-chart]"), e = this._edit;
    const W = 360, H = 150, PLOT = H - 22;
    const pos = (ev) => {
      const b = svg.getBoundingClientRect(), k = b.width / W;
      const vy = ((ev.clientY - b.top) / k);  // y in viewBox units
      return { t: ((ev.clientX - b.left) / b.width) * 1440, i: ((H - 14 - vy) / PLOT) * 1000, k };
    };
    const snapT = (t) => Math.max(0, Math.min(1439, Math.round(t / 5) * 5));
    const snapI = (i) => Math.max(0, Math.min(1000, Math.round(i / 5) * 5));
    const info = () => { const el = this._card.querySelector("[data-pt]"); if (el) el.textContent = this._pointText(); };
    let drag = null;
    svg.onpointerdown = (ev) => {
      const r = this._editRamp(), p = pos(ev);
      // Nearest existing point within ~14 px grabs; otherwise add a new point.
      let best = -1, bd = 1e9;
      r.points.forEach((q, n) => {
        const dx = ((q.time - p.t) / 1440) * W * p.k, dy = ((q.intensity - p.i) / 1000) * PLOT * p.k;
        const d = Math.hypot(dx, dy);
        if (d < bd) { bd = d; best = n; }
      });
      if (bd > 14) {
        const t = snapT(p.t);
        if (r.points.some((q) => q.time === t)) return;
        r.points.push({ time: t, intensity: snapI(p.i) });
        r.points.sort((a, b) => a.time - b.time);
        best = r.points.findIndex((q) => q.time === t);
      }
      e.pt = best; drag = best;
      svg.setPointerCapture(ev.pointerId);
      this._drawEdit(); info();
    };
    svg.onpointermove = (ev) => {
      if (drag === null) return;
      const r = this._editRamp(), p = pos(ev), q = r.points[drag];
      q.intensity = snapI(p.i);
      // First/last points keep their time; the others stay between their neighbours.
      if (drag > 0 && drag < r.points.length - 1) {
        q.time = Math.max(r.points[drag - 1].time + 1, Math.min(r.points[drag + 1].time - 1, snapT(p.t)));
      }
      this._drawEdit(); info();
    };
    const end = () => { if (drag !== null) { drag = null; this._renderEdit(); } };
    svg.onpointerup = end;
    svg.onpointercancel = end;
  }

  _pointText() {
    const p = this._editRamp().points[this._edit.pt];
    if (!p) return "";
    const m = p.time;
    return `Point ${String(Math.floor(m / 60)).padStart(2, "0")}:${String(m % 60).padStart(2, "0")} · ${(p.intensity / 10).toFixed(1)}%`;
  }

  async _saveEdit() {
    const e = this._edit;
    if (e.ramps.some((r) => r.points.length < 2)) { alert("Every channel needs at least 2 points."); return; }
    try {
      await this._hass.callService("aqua_illumination", "set_schedule", {
        entity_id: this._config.entity, name: e.name, ramps: e.ramps,
      });
    } catch (err) { alert(`Could not save: ${err.message || err}`); return; }
    this._lastDay = e.ramps;
    await this._endPreview();
    this._edit = null;
    this._render();
  }

  async _endPreview() {
    if (!this._prevActive) return;
    this._prevActive = false;
    try { await this._hass.callService("aqua_illumination", "cancel_lights_off", { entity_id: this._config.entity }); }
    catch (err) { alert(`Could not end the preview: ${err.message || err}`); }
  }

  // ---- night light ------------------------------------------------------
  _startNight() {
    const sched = this._hass.states[this._config.entity];
    const n = (sched && sched.attributes.night) || {};
    this._sheet = {
      enable: !!n.enable, start: n.start ?? 1200, end: n.end ?? 420,
      level: n.level ?? 5, channels: [...(n.channels || [])],
    };
    this._renderNight();
  }

  _renderNight() {
    const n = this._sheet;
    const chans = this._channels().map((c) => c.key);
    this._card.innerHTML = `<div class="pad">
      <div class="head"><div class="title">Night light</div></div>
      <div class="foot">A low glow on the channels you pick, laid over the schedule between these times. Lunar mode then dims it by moon phase.</div>
      <div class="presets"><label><input type="checkbox" data-n="enable" ${n.enable ? "checked" : ""}> Enabled</label></div>
      <div class="presets"><span>From</span><input type="time" data-n="start" value="${hhmm(n.start)}">
        <span>to</span><input type="time" data-n="end" value="${hhmm(n.end)}"></div>
      <div class="presets"><span>Level</span><input type="range" min="0" max="30" step="0.5" value="${n.level}" data-n="level" style="flex:1"><span data-lv>${n.level}%</span></div>
      <div class="toggles">${chans.map((c) => `<button class="chip ${n.channels.includes(c) ? "on" : ""}" data-ch="${c}">${LABEL(c)}</button>`).join("")}</div>
      <div class="toggles"><button class="chip on" data-nsave>Save</button><button class="chip" data-ncancel>Cancel</button></div></div>`;
    const q = (sel) => this._card.querySelector(sel);
    const mins = (v) => { const [h, m] = v.split(":").map(Number); return h * 60 + m; };
    q('[data-n=enable]').onchange = (ev) => { n.enable = ev.target.checked; };
    q('[data-n=start]').onchange = (ev) => { if (ev.target.value) n.start = mins(ev.target.value); };
    q('[data-n=end]').onchange = (ev) => { if (ev.target.value) n.end = mins(ev.target.value); };
    q('[data-n=level]').oninput = (ev) => { n.level = Number(ev.target.value); q("[data-lv]").textContent = `${n.level}%`; };
    this._card.querySelectorAll("[data-ch]").forEach((b) => {
      b.onclick = () => {
        const c = b.dataset.ch;
        n.channels = n.channels.includes(c) ? n.channels.filter((x) => x !== c) : [...n.channels, c];
        b.classList.toggle("on");
      };
    });
    q("[data-ncancel]").onclick = () => { this._sheet = null; this._render(); };
    q("[data-nsave]").onclick = async () => {
      if (n.enable && !n.channels.length) { alert("Pick at least one channel."); return; }
      const t = (m) => `${hhmm(m)}:00`;
      try {
        await this._hass.callService("aqua_illumination", "set_night_light", {
          entity_id: this._config.entity, enable: n.enable, start: t(n.start), end: t(n.end),
          level: n.level, channels: n.channels });
      } catch (err) { alert(`Could not save: ${err.message || err}`); return; }
      this._sheet = null; this._render();
    };
  }

  // ---- preset import / export -------------------------------------------
  async _exportPresets() {
    const sched = this._hass.states[this._config.entity];
    const saved = (sched && sched.attributes.saved_presets) || {};
    const names = Object.keys(saved);
    if (!names.length) { alert("No saved presets yet - use \"Save as preset…\" first."); return; }
    const presets = {};
    for (const n of names) presets[n] = { ramps: saved[n].ramps };
    const text = JSON.stringify({ aqua_illumination_presets: 1, presets });
    try { await navigator.clipboard.writeText(text); alert(`Copied ${names.length} preset(s) to the clipboard.`); }
    catch (err) { prompt("Copy this text:", text); }
  }

  async _importPresets() {
    const text = prompt("Paste exported presets:");
    if (!text) return;
    const go = (replace) => this._hass.callService("aqua_illumination", "import_presets", {
      entity_id: this._config.entity, data: text, replace });
    try { await go(false); alert("Imported."); }
    catch (err) {
      const msg = String((err && err.message) || err);
      if (/already saved/.test(msg) && confirm(`${msg}\n\nReplace them?`)) {
        try { await go(true); alert("Imported."); } catch (e2) { alert(`Import failed: ${e2.message || e2}`); }
      } else if (!/already saved/.test(msg)) alert(`Import failed: ${msg}`);
    }
  }

  _dur(sec) {
    sec = Math.round(sec);
    if (sec < 90) return `${sec}s`;
    if (sec < 5400) return `${Math.round(sec / 60)} min`;
    return `${(sec / 3600).toFixed(1)} h`;
  }

  _ago(iso) {
    const t = Date.parse(iso);
    return Number.isNaN(t) ? "?" : this._dur(Math.max(0, (Date.now() - t) / 1000));
  }

  _chart(ramps, nowMin) {
    const W = 360, H = 120;
    const x = (t) => (t / 1440) * W;
    const y = (i) => H - (Math.min(i, 1000) / 1000) * (H - 6) - 3;
    let paths = "";
    for (const r of ramps) {
      const pts = r.points || [];
      if (pts.length < 2) continue;
      // Hold flat before the first and after the last point (24h wrap).
      const d = pts.map((p, n) => `${n ? "L" : "M"}${x(p.time).toFixed(1)},${y(p.intensity).toFixed(1)}`).join(" ");
      paths += `<path d="${d}" fill="none" stroke="${COLORS[r.color] || "#888"}" stroke-width="1.8" opacity="0.9"/>`;
    }
    let grid = "";
    for (let h = 0; h <= 24; h += 6) {
      grid += `<line x1="${x(h * 60)}" x2="${x(h * 60)}" y1="0" y2="${H}" class="grid"/>`
        + `<text x="${x(h * 60) + 2}" y="${H - 2}" class="tick">${String(h).padStart(2, "0")}</text>`;
    }
    const now = nowMin === null ? "" : `<line x1="${x(nowMin)}" x2="${x(nowMin)}" y1="0" y2="${H}" class="now"/>`;
    return `<svg viewBox="0 0 ${W} ${H}" class="chart">${grid}${paths}${now}</svg>`;
  }

  _slider(c) {
    const st = this._hass.states[c.id];
    if (!st) return "";
    const gone = st.state === "unavailable" || st.state === "unknown";
    const v = gone ? 0 : Number(st.state) || 0;
    const colour = COLORS[c.key] || "#888";
    return `<label class="row">
      <span class="dot" style="background:${colour}"></span>
      <span class="lbl">${LABEL(c.key)}</span>
      <input type="range" min="0" max="100" step="0.5" value="${v}" data-id="${c.id}" ${gone ? "disabled" : ""} style="accent-color:${colour}">
      <span class="val">${gone ? "—" : v + "%"}</span>
    </label>`;
  }

  _wire() {
    const call = (d, s, data) => this._hass.callService(d, s, data);
    this._card.querySelectorAll("[data-act]").forEach((b) => {
      b.onclick = () => {
        const a = b.dataset.act;
        if (a === "schedule") call("switch", "toggle", { entity_id: `switch.${this._prefix}_schedule` });
        if (a === "night") call("switch", "toggle", { entity_id: `switch.${this._prefix}_night_feeding` });
        if (a === "clock") call("button", "press", { entity_id: `button.${this._prefix}_sync_clock` });
        if (a === "apply") {
          const sel = this._card.querySelector("[data-preset]");
          if (sel && confirm(`Replace the light's schedule with "${sel.value}"?`)) {
            call("select", "select_option", { entity_id: `select.${this._prefix}_schedule_preset`, option: sel.value });
          }
        }
        if (a === "save") {
          const name = (prompt("Name for the current schedule:") || "").trim();
          if (!name) return;
          if (BUILTIN_PRESETS.includes(name)) { alert("That name is a built-in preset."); return; }
          call("aqua_illumination", "save_preset", { entity_id: this._config.entity, name });
        }
        if (a === "edit") this._startDesigner();
        if (a === "night") this._startNight();
        if (a === "off") {
          const sw = this._e("switch", "lights_off");
          if (sw && sw.state === "on") { call("aqua_illumination", "cancel_lights_off", { entity_id: this._config.entity }); return; }
          const txt = prompt("Lights off for how many minutes? (blank = until you resume)", "30");
          if (txt === null) return;
          const mins = parseFloat(txt);
          call("aqua_illumination", "lights_off", Object.assign({ entity_id: this._config.entity }, mins > 0 ? { duration: mins } : {}));
        }
        if (a === "export") this._exportPresets();
        if (a === "import") this._importPresets();
      };
    });
    this._card.querySelectorAll("input[type=range]").forEach((inp) => {
      const val = inp.parentElement.querySelector(".val");
      inp.oninput = () => { this._dragging = true; val.textContent = `${inp.value}%`; };
      inp.onchange = () => {
        call("number", "set_value", { entity_id: inp.dataset.id, value: Number(inp.value) });
        this._dragging = false;
      };
    });
  }
}

AquaIlluminationCard.css = `
  .pad{padding:14px 16px}
  .head{display:flex;justify-content:space-between;align-items:baseline}
  .title{font-size:1.15em;font-weight:600}
  .meta{opacity:.7}
  .warn{color:var(--error-color,#c33);margin:6px 0}
  .off{opacity:.4;pointer-events:none}
  .presets{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin:10px 0 0}
  .presets select{background:var(--card-background-color);color:inherit;border:1px solid var(--divider-color,#888);border-radius:8px;padding:4px 6px;font:inherit}
  .chip[disabled]{opacity:.4;cursor:default}
  .edit{touch-action:none;cursor:crosshair}
  .toggles{display:flex;gap:8px;flex-wrap:wrap;margin:10px 0}
  .chip{border:1px solid var(--divider-color,#888);background:none;color:inherit;border-radius:14px;padding:4px 12px;cursor:pointer;font:inherit}
  .chip.on{background:var(--primary-color);color:var(--text-primary-color,#fff);border-color:var(--primary-color)}
  .chart{width:100%;height:auto;background:var(--secondary-background-color,#0001);border-radius:8px}
  .grid{stroke:var(--divider-color,#8884);stroke-width:.5}
  .tick{font-size:8px;fill:var(--secondary-text-color,#888)}
  .now{stroke:var(--primary-color);stroke-width:1;stroke-dasharray:3 2}
  .sliders{margin-top:10px;display:grid;gap:4px}
  .row{display:grid;grid-template-columns:12px 92px 1fr 48px;align-items:center;gap:8px}
  .dot{width:10px;height:10px;border-radius:50%}
  .val{text-align:right;font-variant-numeric:tabular-nums}
  input[type=range]{width:100%}
  .foot{margin-top:8px;font-size:.8em;opacity:.6}
`;

class AquaIlluminationCardEditor extends HTMLElement {
  setConfig(config) { this._config = config; this._draw(); }
  set hass(hass) { this._hass = hass; this._draw(); }
  _draw() {
    if (!this._hass || !this._config) return;
    if (!this._form) {
      this._form = document.createElement("ha-form");
      this._form.computeLabel = (sch) => ({ entity: "Light (its 'Schedule data' sensor)", name: "Name (optional)" }[sch.name] || sch.name);
      this._form.addEventListener("value-changed", (ev) => {
        const cfg = Object.assign({}, this._config, ev.detail.value);
        if (!cfg.name) delete cfg.name;
        this._config = cfg;
        this.dispatchEvent(new CustomEvent("config-changed", { detail: { config: cfg }, bubbles: true, composed: true }));
      });
      this.appendChild(this._form);
    }
    this._form.hass = this._hass;
    this._form.schema = [
      { name: "entity", required: true, selector: { entity: { domain: "sensor", integration: "aqua_illumination" } } },
      { name: "name", selector: { text: {} } },
    ];
    this._form.data = this._config;
  }
}

customElements.define("aqua-illumination-card", AquaIlluminationCard);
customElements.define("aqua-illumination-card-editor", AquaIlluminationCardEditor);
window.customCards = window.customCards || [];
window.customCards.push({
  type: "aqua-illumination-card",
  name: "Aqua Illumination",
  description: "Schedule chart, live channel levels and controls for an AI Prime light",
});
