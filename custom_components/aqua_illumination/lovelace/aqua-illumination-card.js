/* Aqua Illumination card - shows a Prime light's schedule, live levels and controls.
 *
 *   type: custom:aqua-illumination-card
 *   entity: sensor.ai_prime_0a82_schedule_data   # the "Schedule data" sensor
 *   name: Reef            # optional
 *
 * Every other entity is derived from the sensor's name, so one line is enough.
 */
const CARD_VERSION = "0.1.0";

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
    if (this._dragging) return;
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
    const ramps = sched.attributes.ramps || [];
    const temp = this._e("sensor", "temperature");
    const clock = this._e("sensor", "device_clock");
    const schedSw = this._e("switch", "schedule");
    const nightSw = this._e("switch", "night_feeding");
    const chans = this._channels();
    const offline = [sched.state, schedSw && schedSw.state].includes("unavailable");

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
          <div class="meta">${temp && temp.state !== "unavailable" ? temp.state + " °C" : ""}</div>
        </div>
        ${offline ? `<div class="warn">Light is offline</div>` : ""}
        <div class="toggles">
          <button class="chip ${schedSw && schedSw.state === "on" ? "on" : ""}" data-act="schedule">Schedule ${schedSw ? schedSw.state : "?"}</button>
          <button class="chip ${nightSw && nightSw.state === "on" ? "on" : ""}" data-act="night">Night feeding</button>
          <button class="chip" data-act="clock">Sync clock</button>
        </div>
        ${this._chart(ramps, nowMin)}
        <div class="sliders">
          ${chans.map((c) => this._slider(c)).join("")}
        </div>
        <div class="foot">Clock: ${clock ? clock.state : "?"} · v${CARD_VERSION}</div>
      </div>`;
    this._wire();
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
    const v = Number(st.state) || 0;
    const colour = COLORS[c.key] || "#888";
    return `<label class="row">
      <span class="dot" style="background:${colour}"></span>
      <span class="lbl">${LABEL(c.key)}</span>
      <input type="range" min="0" max="100" step="0.5" value="${v}" data-id="${c.id}" style="accent-color:${colour}">
      <span class="val">${v}%</span>
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
