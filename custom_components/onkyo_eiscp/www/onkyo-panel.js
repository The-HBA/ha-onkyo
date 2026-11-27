// The sidebar page: the remote card, and beside it everything the card leaves out (DESIGN.md
// "Card or sidebar"): tone, levels, sound and setup options, names and receiver info.
// Settings come from the receiver's entities; a setting the model lacks does not show.

const VERSION = new URL(import.meta.url).search;
const load = (path) => import(new URL(`${path}${VERSION}`, import.meta.url).href);

const shared = await load("./shared.js");
const { STYLE } = await load("./styles.js");
await load("./onkyo-remote-card.js");
const { Remote, esc, icon, optionLabel, pickDevice, receivers, segmented } = shared;

const HOLD_DELAY = 450;
const HOLD_REPEAT = 120;

/** What the page shows, in order. Kinds: number, select, switch, text (a sensor). */
const SECTIONS = [
  {
    title: "Tone",
    items: [
      ["number", "number.bass", "Bass"],
      ["number", "number.treble", "Treble"],
    ],
  },
  {
    title: "Levels",
    items: [
      ["number", "number.subwoofer_level", "Subwoofer"],
      ["number", "number.subwoofer2_level", "Subwoofer 2"],
      ["number", "number.center_level", "Center"],
      ["number", "number.vocal_enhancer", "Vocal enhancer"],
      ["number", "number.dialog_level", "Dialog"],
    ],
  },
  {
    title: "Sound",
    items: [
      ["select", "select.equalizer", "Equalizer"],
      ["switch", "switch.cinema_filter", "Cinema filter"],
    ],
  },
  {
    title: "Setup",
    items: [
      ["select", "select.dimmer", "Dimmer"],
      ["select", "select.digital_filter", "Digital filter"],
      ["number", "number.av_sync", "A/V sync"],
      ["select", "select.hdmi_output", "HDMI output"],
    ],
  },
];

const decimals = (step) => (String(step).split(".")[1] ?? "").length;

class OnkyoPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hass = null;
    this._narrow = false;
    this._deviceId = null;
    this._info = null;
    this._seen = [];
  }

  set hass(hass) {
    this._hass = hass;
    this._update();
  }

  set narrow(value) {
    this._narrow = value;
    this._renderFrame();
  }

  set panel(value) {
    this._panel = value;
  }

  connectedCallback() {
    this._build();
    if (this._hass) this._update();
  }

  _build() {
    if (this._root) return;
    this.shadowRoot.innerHTML = `<style>${STYLE}
      :host{display:block;height:100%;overflow:auto;background:var(--primary-background-color)}
      .bar{display:flex;align-items:center;gap:8px;height:56px;padding:0 12px;background:var(--app-header-background-color,var(--card-background-color));
        color:var(--app-header-text-color,var(--primary-text-color));border-bottom:1px solid var(--divider-color)}
      .bar h1{font-size:20px;font-weight:400;margin:0;flex:1}
      .bar select{font:inherit;color:inherit;background:var(--ctl);border:0;border-radius:var(--ir);min-height:40px;padding:0 10px}
      .menu{width:48px;height:48px;border-radius:50%;display:grid;place-items:center;background:none;border:0;color:inherit;cursor:pointer}
      .cols{display:flex;gap:16px;align-items:flex-start;padding:16px;max-width:1100px;margin:0 auto}
      .cols.narrow{flex-direction:column;padding:8px}
      .cols.narrow > *{width:100%}
      .left{flex:0 0 420px}
      .cols.narrow .left{flex:none}
      .right{flex:1;min-width:0;display:flex;flex-direction:column;gap:12px}
      .panelwrap .grp{background:var(--card-background-color)}
      .rowsel{display:flex;flex-direction:column;gap:4px}
      .empty{padding:24px;text-align:center;color:var(--secondary-text-color)}
    </style>
    <div class="panelwrap"><div class="bar"></div><div class="cols"><div class="left"></div><div class="right"></div></div></div>`;
    this._root = this.shadowRoot.querySelector(".panelwrap");
    this._bar = this._root.querySelector(".bar");
    this._cols = this._root.querySelector(".cols");
    this._left = this._root.querySelector(".left");
    this._right = this._root.querySelector(".right");
    this._root.addEventListener("click", (event) => this._onClick(event));
    this._root.addEventListener("change", (event) => {
      if (event.target.matches("[data-device]")) {
        this._deviceId = event.target.value;
        this._info = null;
        this._card.setConfig({ type: "custom:onkyo-remote-card", device_id: this._deviceId });
        this._seen = [];
        this._update();
      }
    });
    this._root.addEventListener("pointerdown", (event) => this._onPointerDown(event));
    this._renderFrame();
  }

  _renderFrame() {
    if (!this._root) return;
    this._cols.classList.toggle("narrow", this._narrow);
    const menu = this._narrow
      ? `<button class="menu" data-a="menu" aria-label="Sidebar">${icon("menu")}</button>`
      : "";
    this._bar.innerHTML = `${menu}<h1>${esc(this._panel?.title || "Onkyo")}</h1><span data-picker></span>`;
    this._seen = [];
    if (this._hass) this._update();
  }

  _update() {
    if (!this._root || !this._hass) return;
    const hass = this._hass;
    const list = receivers(hass);
    if (!this._deviceId || !list.some((item) => item.id === this._deviceId)) {
      this._deviceId = pickDevice(hass, null);
      this._info = null;
    }
    if (!this._card) {
      this._card = document.createElement("onkyo-remote-card");
      this._left.append(this._card);
    }
    if (this._card._config?.device_id !== this._deviceId) {
      this._card.setConfig({ type: "custom:onkyo-remote-card", device_id: this._deviceId ?? undefined });
    }
    this._card.hass = hass;
    if (!this._info && this._deviceId && !this._fetching) this._fetchInfo();
    const remote = new Remote(hass, this._deviceId, this._info);
    const seen = [list.length, this._deviceId, hass.user?.is_admin, this._info, ...Object.values(remote.ids).map((id) => hass.states?.[id])];
    if (seen.length === this._seen.length && seen.every((item, index) => item === this._seen[index])) return;
    this._seen = seen;
    this._renderPicker(list);
    this._right.innerHTML = this._deviceId ? this._settingsHtml(remote) : `<div class="empty">No Onkyo receiver found. Add one under Settings, Devices and services.</div>`;
  }

  async _fetchInfo() {
    this._fetching = true;
    try {
      this._info = await this._hass.callWS({ type: shared.WS_CARD_INFO, device_id: this._deviceId });
    } catch (error) {
      console.debug("onkyo-panel: card_info failed", error);
      this._info = { error: true };
    } finally {
      this._fetching = false;
    }
    this._seen = [];
    this._update();
  }

  _renderPicker(list) {
    const slot = this._bar.querySelector("[data-picker]");
    if (!slot) return;
    slot.innerHTML =
      list.length > 1
        ? `<select data-device aria-label="Receiver">${list
            .map((item) => `<option value="${esc(item.id)}" ${item.id === this._deviceId ? "selected" : ""}>${esc(item.name)}</option>`)
            .join("")}</select>`
        : "";
  }

  // ------------------------------------------------------------------ settings

  _settingsHtml(remote) {
    const blocks = [];
    if (remote.power === "standby") {
      blocks.push(shared.notice("The receiver is in standby. Some settings need it on."));
    }
    for (const section of SECTIONS) {
      const items = section.items.map((item) => this._itemHtml(remote, item)).filter(Boolean);
      if (items.length) blocks.push(`<div class="grp"><div class="gh"><span class="gt">${section.title}</span></div>${items.join("")}</div>`);
    }
    blocks.push(this._namesHtml());
    blocks.push(this._receiverHtml(remote));
    return blocks.join("");
  }

  _itemHtml(remote, [kind, key, label]) {
    const state = remote.state(key);
    if (!state) return "";
    const unavailable = ["unavailable", "unknown"].includes(state.state);
    if (kind === "number") {
      const unit = state.attributes.unit_of_measurement ? ` ${esc(state.attributes.unit_of_measurement)}` : "";
      const value = unavailable ? "Not available" : `${esc(state.state)}${unit}`;
      return `<div class="step"><div class="lbl">${esc(label)}</div><div class="stepper ${unavailable ? "ctl" : ""}" ${unavailable ? 'style="opacity:.5;pointer-events:none"' : ""}>
        <button class="ibtn pr" data-a="num" data-k="${key}" data-v="-1" data-rep aria-label="${esc(label)} down">${icon("minus")}</button>
        <span class="v" data-value="${key}">${value}</span>
        <button class="ibtn pr" data-a="num" data-k="${key}" data-v="1" data-rep aria-label="${esc(label)} up">${icon("plus")}</button></div></div>`;
    }
    if (kind === "select") {
      const options = (state.attributes.options ?? []).map((value) => ({
        value,
        label: optionLabel(this._hass, state, value),
        selected: value === state.state,
      }));
      if (unavailable || !options.length) return "";
      return `<div class="rowsel"><div class="lbl">${esc(label)}</div>${segmented(options, { action: "sel", key, cols: Math.min(options.length, 4), dense: true })}</div>`;
    }
    const on = state.state === "on";
    return `<button class="tgl pr ${unavailable ? "ctl" : ""}" role="switch" aria-checked="${on}" data-a="tgl" data-k="${key}" ${unavailable ? "disabled" : ""}>
      <span class="n">${esc(label)}</span><span class="sw"></span></button>`;
  }

  _namesHtml() {
    const admin = this._hass.user?.is_admin === true;
    const edit = admin
      ? `<button class="setlink pr" data-a="rename" data-v="inputs">${icon("pencil", 22)}<span class="n">Rename, hide and order inputs<small>One plain name each</small></span>${icon("right", 22)}</button>
         <button class="setlink pr" data-a="rename" data-v="modes">${icon("pencil", 22)}<span class="n">Rename and hide listening modes<small>Each shows only when the signal allows it</small></span>${icon("right", 22)}</button>`
      : `<div class="qnote">${icon("alertO", 18)}<span>Only an administrator can rename inputs and modes.</span></div>`;
    return `<div class="grp"><div class="gh"><span class="gt">Names</span></div>${edit}
      <button class="setlink pr" data-a="options">${icon("cog", 22)}<span class="n">Volume limits and more<small>Open the integration's options</small></span>${icon("open", 22)}</button></div>`;
  }

  _receiverHtml(remote) {
    const rows = [];
    const add = (label, value) => value && rows.push(`<div class="row"><span class="n">${esc(label)}</span><span class="v">${esc(value)}</span></div>`);
    add("Model", this._info?.model);
    add("Integration version", this._info?.version);
    const temperature = remote.state("sensor.temperature");
    if (temperature && !["unavailable", "unknown"].includes(temperature.state)) {
      add("Temperature", `${temperature.state} ${temperature.attributes.unit_of_measurement ?? ""}`.trim());
    }
    const display = remote.state("sensor.front_display");
    if (display && !["unavailable", "unknown"].includes(display.state)) add("Front display", display.state);
    if (!rows.length) return "";
    return `<div class="grp"><div class="gh"><span class="gt">Receiver</span></div><div class="rows">${rows.join("")}</div></div>`;
  }

  // ------------------------------------------------------------------ actions

  _onClick(event) {
    const button = event.target.closest("[data-a]");
    if (!button) return;
    if (button.hasAttribute("data-rep") && event.detail !== 0) return;
    this._act(button.dataset.a, button.dataset.v, button.dataset.k);
  }

  _onPointerDown(event) {
    const button = event.target.closest("[data-rep]");
    if (!button || event.button > 0) return;
    const fire = () => this._act(button.dataset.a, button.dataset.v, button.dataset.k);
    const tick = () => {
      fire();
      this._holdTimer = setTimeout(tick, HOLD_REPEAT);
    };
    const stop = () => {
      clearTimeout(this._holdTimer);
      window.removeEventListener("pointerup", stop);
      window.removeEventListener("pointercancel", stop);
    };
    fire();
    this._holdTimer = setTimeout(tick, HOLD_DELAY);
    window.addEventListener("pointerup", stop);
    window.addEventListener("pointercancel", stop);
  }

  async _call(domain, service, key, data) {
    const entityId = new Remote(this._hass, this._deviceId).entityId(key);
    if (!entityId) return;
    try {
      await this._hass.callService(domain, service, { entity_id: entityId, ...data });
    } catch (error) {
      this._toast(error?.message || String(error));
    }
  }

  _toast(message) {
    this.dispatchEvent(new CustomEvent("hass-notification", { detail: { message }, bubbles: true, composed: true }));
  }

  async _act(action, value, key) {
    switch (action) {
      case "menu":
        this.dispatchEvent(new CustomEvent("hass-toggle-menu", { bubbles: true, composed: true }));
        return;
      case "num": {
        const state = this._hass.states[new Remote(this._hass, this._deviceId).entityId(key)];
        if (!state || Number.isNaN(Number(state.state))) return;
        const { min, max, step = 1 } = state.attributes;
        const next = Math.min(max ?? Infinity, Math.max(min ?? -Infinity, Number(state.state) + Number(value) * step));
        await this._call("number", "set_value", key, { value: Number(next.toFixed(decimals(step))) });
        return;
      }
      case "sel":
        await this._call("select", "select_option", key, { option: value });
        return;
      case "tgl": {
        const state = new Remote(this._hass, this._deviceId).state(key);
        await this._call("switch", state?.state === "on" ? "turn_off" : "turn_on", key, {});
        return;
      }
      case "rename": {
        const { openRenameSheet } = await load("./rename-sheet.js");
        const remote = new Remote(this._hass, this._deviceId);
        openRenameSheet({
          hass: this._hass,
          deviceId: this._deviceId,
          host: this.shadowRoot,
          kind: value,
          currentInput: remote.sourceCode,
          currentMode: remote.modeCode,
          toast: (message) => this._toast(message),
          onSaved: () => {
            this._info = null;
            this._seen = [];
            this._update();
          },
        });
        return;
      }
      case "options":
        history.pushState(null, "", "/config/integrations/integration/onkyo_eiscp");
        window.dispatchEvent(new CustomEvent("location-changed"));
        return;
      default:
    }
  }
}

if (!customElements.get("onkyo-panel")) customElements.define("onkyo-panel", OnkyoPanel);
