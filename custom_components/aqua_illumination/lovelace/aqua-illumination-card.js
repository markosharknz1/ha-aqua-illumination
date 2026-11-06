/* Aqua Illumination card - shows a Prime light's schedule, live levels and controls.
 *
 *   type: custom:aqua-illumination-card
 *   entity: sensor.ai_prime_0a82_schedule_data   # the "Schedule data" sensor
 *   name: Reef            # optional
 *
 * Every other entity is derived from the sensor's name, so one line is enough.
 */
const CARD_VERSION = "0.3.0";
const BUILTIN_PRESETS = ["Standard day", "Coral growth", "Acclimation (gentle)"];

const COLORS = {
  deep_red: "#b3202a", red: "#e03a3a", far_red: "#8a1c1c", uv: "#8f5bff",
  violet: "#a06bd6", deep_blue: "#2740c9", blue: "#3b82f6", royal: "#2f5bd6",
  cool_white: "#d8e4f0", neutral_white: "#e8e2cf", warm_white: "#f1d9a0",
  green: "#3fb26b",
};
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
  static getStubConfig() { return { entity: "sensor.ai_prime_0000_schedule_data" }; }

  set hass(hass) {
    this._hass = hass;
    // Don't rebuild while the user is dragging a slider.
    // ...or while the schedule editor is open (it draws itself).
    if (this._dragging || this._edit) return;
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
        <div class="sliders ${offline ? "off" : ""}">
          ${chans.map((c) => this._slider(c)).join("")}
        </div>
        <div class="foot">${offline
          ? `Last seen ${ca.last_seen ? this._ago(ca.last_seen) + " ago" : "never"}${ca.last_error ? " · " + ca.last_error : ""}`
          : `Clock: ${clock ? clock.state : "?"}${ca.dropouts ? ` · ${ca.dropouts} dropout${ca.dropouts > 1 ? "s" : ""}${ca.last_outage_seconds ? ` (last ${this._dur(ca.last_outage_seconds)})` : ""}` : ""}`} · v${CARD_VERSION}</div>
      </div>`;
    this._wire();
  }

  // ---- schedule editor ------------------------------------------------
  _startEdit() {
    const ramps = (this._lastRamps || []).map((r) => ({
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
      <div class="foot" data-pt>${e.pt !== null ? this._pointText() : "Drag a point · click empty space to add one"}</div>
      <div class="toggles">
        <button class="chip" data-edit="del" ${canDel ? "" : "disabled"}>Delete point</button>
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
        if (a === "cancel") { this._edit = null; this._render(); }
        if (a === "del" && canDel) { r.points.splice(e.pt, 1); e.pt = null; this._renderEdit(); }
        if (a === "save") this._saveEdit();
      };
    });
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
    this._lastRamps = e.ramps;
    this._edit = null;
    this._render();
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
        if (a === "edit") this._startEdit();
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

customElements.define("aqua-illumination-card", AquaIlluminationCard);
window.customCards = window.customCards || [];
window.customCards.push({
  type: "aqua-illumination-card",
  name: "Aqua Illumination",
  description: "Schedule chart, live channel levels and controls for an AI Prime light",
});
