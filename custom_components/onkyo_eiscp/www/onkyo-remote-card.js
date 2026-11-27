// The Onkyo remote card: header, tab row and the pane of the chosen tab (DESIGN.md).
//
// Plain JavaScript, no build step. The card loads its other files itself, with the version of
// this file's own URL appended, so a new release reaches the browser (Home Assistant puts
// `?v=<version>` on the resource URL). One file per tab in `tabs/`: a tab file that does not
// exist is skipped, so tabs can be added without touching this file.
//
// Card config: `device_id` (the receiver; the first one if missing), `volume_unit` (`db` or
// `percent`, the readout's main unit, default `db`).

const VERSION = new URL(import.meta.url).search;
const load = (path) => import(new URL(`${path}${VERSION}`, import.meta.url).href);

const shared = await load("./shared.js");
const { STYLE } = await load("./styles.js");
const { Remote, VolumeSender, WS_CARD_INFO, clamp01, entityIds, icon, esc, pickDevice, volumeTexts } = shared;

const TAB_FILES = ["main", "modes", "remote", "info", "zones"];
const TABS = (
  await Promise.all(
    TAB_FILES.map((name) =>
      load(`./tabs/${name}.js`)
        .then((module) => module.default)
        .catch((error) => {
          console.debug(`onkyo-remote-card: tab ${name} not loaded`, error);
          return null;
        }),
    ),
  )
)
  .filter(Boolean)
  .sort((a, b) => a.order - b.order);

const UNIT_KEY = "onkyo_eiscp.volume_unit";
const HOLD_DELAY = 450;
const HOLD_REPEAT = 120;
const LOCAL_VOLUME_MS = 1500;
const INFO_RETRY_MS = 10000;

class OnkyoRemoteCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._config = null;
    this._hass = null;
    this._deviceId = null;
    this._info = null;
    this._infoAt = 0;
    this._seen = [];
    this._busy = 0;
    this._drag = false;
    this._dirty = false;
    this._wasUnavailable = false;
    this._ctx = null;
    this._ui = { tab: "main", volumeUnit: "db", volLocal: null, pendingMode: null };
    this._sender = new VolumeSender((level) =>
      this._callOn("media_player.main", "media_player", "volume_set", { volume_level: level }),
    );
  }

  static getConfigElement() {
    return load("./onkyo-remote-card-editor.js").then(() => document.createElement("onkyo-remote-card-editor"));
  }

  static getStubConfig(hass) {
    return { type: "custom:onkyo-remote-card", device_id: pickDevice(hass, null) ?? undefined };
  }

  setConfig(config) {
    if (!config || typeof config !== "object") throw new Error("Invalid configuration");
    if (config.volume_unit && !["db", "percent"].includes(config.volume_unit)) {
      throw new Error("volume_unit must be db or percent");
    }
    this._config = { ...config };
    this._ui.volumeUnit = localStorage.getItem(UNIT_KEY) || config.volume_unit || "db";
    this._seen = [];
    if (this._hass) this._update(true);
  }

  set hass(hass) {
    this._hass = hass;
    this._update(false);
  }

  get hass() {
    return this._hass;
  }

  getCardSize() {
    return 12;
  }

  getGridOptions() {
    return { columns: 12, min_columns: 6, rows: "auto" };
  }

  connectedCallback() {
    this._build();
    this._observer ??= new ResizeObserver(() => this._afterRender());
    this._observer.observe(this._card);
    if (this._hass) this._update(true);
  }

  disconnectedCallback() {
    this._observer?.disconnect();
    clearTimeout(this._holdTimer);
    clearTimeout(this._localTimer);
  }

  // ------------------------------------------------------------------ structure and events

  _build() {
    if (this._card) return;
    this.shadowRoot.innerHTML = `<style>${STYLE}</style>
      <ha-card class="oc"><div class="busy"></div><div class="in"></div></ha-card>`;
    this._card = this.shadowRoot.querySelector("ha-card");
    this._in = this.shadowRoot.querySelector(".in");
    const card = this._card;
    card.addEventListener("click", (event) => this._onClick(event));
    card.addEventListener("pointerdown", (event) => this._onPointerDown(event));
    card.addEventListener("keydown", (event) => this._onKeyDown(event));
  }

  _onClick(event) {
    const button = event.target.closest("[data-a]");
    if (!button) return;
    // A pointer press on a repeating button already fired; a keyboard press has no pointer.
    if (button.hasAttribute("data-rep") && event.detail !== 0) return;
    this._act(button.dataset.a, button.dataset.v, button.dataset.k);
  }

  _onKeyDown(event) {
    const tab = event.target.closest?.("[role=tab]");
    if (tab && (event.key === "ArrowRight" || event.key === "ArrowLeft")) {
      const tabs = this._tabs();
      const index = tabs.findIndex((t) => t.id === this._ui.tab);
      const next = tabs[(index + (event.key === "ArrowRight" ? 1 : tabs.length - 1)) % tabs.length];
      this._ui.tab = next.id;
      this._render();
      this._in.querySelector("[role=tab][aria-selected=true]")?.focus();
      event.preventDefault();
      return;
    }
    if (event.target.closest?.("[data-slider]") && ["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(event.key)) {
      this._act("vol", event.key === "ArrowLeft" || event.key === "ArrowDown" ? "-1" : "1");
      event.preventDefault();
    }
  }

  _onPointerDown(event) {
    const slider = event.target.closest("[data-slider]");
    if (slider) {
      this._startDrag(slider, event);
      return;
    }
    const button = event.target.closest("[data-rep]");
    if (!button || event.button > 0) return;
    const fire = () => this._act(button.dataset.a, button.dataset.v, button.dataset.k);
    const stop = () => {
      clearTimeout(this._holdTimer);
      window.removeEventListener("pointerup", stop);
      window.removeEventListener("pointercancel", stop);
    };
    const tick = () => {
      fire();
      this._holdTimer = setTimeout(tick, HOLD_REPEAT);
    };
    fire();
    this._holdTimer = setTimeout(tick, HOLD_DELAY);
    window.addEventListener("pointerup", stop);
    window.addEventListener("pointercancel", stop);
  }

  _startDrag(slider, event) {
    this._drag = true;
    slider.setPointerCapture?.(event.pointerId);
    const move = (ev) => {
      const box = slider.getBoundingClientRect();
      let level = clamp01((ev.clientX - box.left - 18) / (box.width - 18));
      const max = this._info?.volume_max;
      if (max) level = Math.round(level * max) / max;
      this._setVolume(level, false);
      slider.style.setProperty("--f", level.toFixed(4));
      const readout = this._card.querySelector("[data-vol-readout]");
      if (readout) readout.innerHTML = this._readoutHtml();
    };
    const end = () => {
      slider.removeEventListener("pointermove", move);
      slider.removeEventListener("pointerup", end);
      slider.removeEventListener("pointercancel", end);
      this._drag = false;
      if (this._dirty) this._render();
    };
    slider.addEventListener("pointermove", move);
    slider.addEventListener("pointerup", end);
    slider.addEventListener("pointercancel", end);
    move(event);
  }

  // ------------------------------------------------------------------ state to screen

  _tabs() {
    const ctx = this._ctx;
    return ctx ? TABS.filter((tab) => tab.available(ctx)) : TABS;
  }

  _update(force) {
    if (!this._hass || !this._config || !this._card) return;
    const deviceId = pickDevice(this._hass, this._config);
    if (deviceId !== this._deviceId) {
      this._deviceId = deviceId;
      this._info = null;
      this._infoAt = 0;
      force = true;
    }
    const remote = new Remote(this._hass, deviceId, this._info);
    const unavailable = remote.power === "unavailable";
    if (this._wasUnavailable && !unavailable) this._infoAt = 0;
    this._wasUnavailable = unavailable;
    if (deviceId && !this._info && Date.now() - this._infoAt > INFO_RETRY_MS) this._fetchInfo();
    const seen = [this._hass.devices?.[deviceId], this._hass.user?.is_admin, ...Object.values(remote.ids).map((id) => this._hass.states?.[id])];
    const changed = force || seen.length !== this._seen.length || seen.some((item, index) => item !== this._seen[index]);
    this._seen = seen;
    if (changed) this._render();
  }

  async _fetchInfo() {
    this._infoAt = Date.now();
    const deviceId = this._deviceId;
    try {
      const info = await this._hass.callWS({ type: WS_CARD_INFO, device_id: deviceId });
      if (deviceId === this._deviceId) {
        this._info = info;
        this._render();
      }
    } catch (error) {
      console.debug("onkyo-remote-card: card_info failed", error);
    }
  }

  _makeCtx() {
    const remote = new Remote(this._hass, this._deviceId, this._info);
    return {
      hass: this._hass,
      remote,
      ui: this._ui,
      h: shared.HELPERS,
      config: this._config,
      info: this._info,
      admin: this._hass.user?.is_admin === true,
      callOn: (key, domain, service, data) => this._callOn(key, domain, service, data),
      refresh: () => this._render(),
      toast: (message) => this._toast(message),
    };
  }

  _readoutHtml() {
    const volume = this._ctx.remote.volume(this._ui.volLocal?.level);
    const texts = volumeTexts(volume, this._ui.volumeUnit);
    return volume.muted ? `Muted<small>${esc(texts.main)}</small>` : `${esc(texts.main)}<small>${esc(texts.small)}</small>`;
  }

  _render() {
    if (!this._card || !this._hass || !this._config) return;
    if (this._drag) {
      this._dirty = true;
      return;
    }
    this._dirty = false;
    const ctx = this._makeCtx();
    this._ctx = ctx;
    const { remote } = ctx;
    if (!this._deviceId || !remote.player) {
      this._card.className = "oc";
      this._in.innerHTML = `<div class="notice">${icon("alertO", 22)}<span>No Onkyo receiver found. Add one under Settings, Devices and services.</span></div>`;
      return;
    }
    const tabs = this._tabs();
    if (!tabs.some((tab) => tab.id === this._ui.tab)) this._ui.tab = tabs[0]?.id ?? "main";
    const tab = tabs.find((t) => t.id === this._ui.tab);
    const on = remote.power === "on";
    this._card.className = `oc${on ? " on" : ""}${this._busy || this._ui.pendingMode ? " sending" : ""}`;
    const sub = on
      ? `On · ${esc(remote.source || "No input")} · ${esc(this._ui.pendingMode?.name ?? remote.mode)}`
      : remote.power === "standby"
        ? "Standby"
        : "Unavailable";
    const tabRow = tabs
      .map(
        (t) => `<button class="opt pr ${t.id === tab.id ? "sel" : ""}" role="tab" aria-selected="${t.id === tab.id}" data-a="tab" data-v="${t.id}">${icon(t.icon, 20)}<span>${esc(t.label)}</span></button>`,
      )
      .join("");
    const focused = this._focusKey();
    this._in.innerHTML = `<div class="head"><div class="hicon">${icon("speaker")}</div>
        <div class="htxt"><div class="hname">${esc(remote.name)}</div><div class="hsub">${sub}</div></div>
        <button class="power pr" data-a="power" aria-label="Power">${icon("power")}</button></div>
      <div class="seg tabs" role="tablist" style="--cols:${tabs.length}">${tabRow}</div>
      <div class="pane p-${tab.id}" role="tabpanel">${tab.render(ctx)}</div>`;
    this._restoreFocus(focused);
    this._afterRender();
  }

  /** Which control has the keyboard focus, so a render does not lose it. */
  _focusKey() {
    const el = this.shadowRoot.activeElement;
    if (!el || !this._in.contains(el)) return null;
    if (el.hasAttribute("data-slider")) return "[data-slider]";
    if (!el.dataset.a) return null;
    const part = (name, value) => (value === undefined ? "" : `[data-${name}="${CSS.escape(value)}"]`);
    return `[data-a="${CSS.escape(el.dataset.a)}"]${part("k", el.dataset.k)}${part("v", el.dataset.v)}`;
  }

  _restoreFocus(selector) {
    if (selector) this._in.querySelector(selector)?.focus({ preventScroll: true });
  }

  _afterRender() {
    const ctx = this._ctx;
    if (!ctx || !this._in) return;
    const pane = this._in.querySelector(".pane");
    const tab = TABS.find((t) => t.id === this._ui.tab);
    if (pane && tab?.after) tab.after(ctx, pane);
  }

  // ------------------------------------------------------------------ actions

  _act(action, value, key) {
    const ctx = this._ctx;
    if (!ctx) return;
    switch (action) {
      case "tab":
        this._ui.tab = value;
        this._render();
        return;
      case "power":
        if (ctx.remote.power !== "unavailable") {
          this._callOn("media_player.main", "media_player", ctx.remote.power === "on" ? "turn_off" : "turn_on");
        }
        return;
      case "mute":
        this._callOn("media_player.main", "media_player", "volume_mute", {
          is_volume_muted: !ctx.remote.volume().muted,
        });
        return;
      case "unit":
        this._ui.volumeUnit = this._ui.volumeUnit === "percent" ? "db" : "percent";
        localStorage.setItem(UNIT_KEY, this._ui.volumeUnit);
        this._render();
        return;
      case "vol":
        this._stepVolume(Number(value));
        return;
      case "rename":
        this._openRename(value);
        return;
      case "settings":
        history.pushState(null, "", "/onkyo");
        window.dispatchEvent(new CustomEvent("location-changed"));
        return;
      default: {
        const tab = TABS.find((t) => t.id === this._ui.tab);
        tab?.action?.(ctx, action, value, key);
      }
    }
  }

  async _openRename(kind) {
    const { openRenameSheet } = await load("./rename-sheet.js");
    openRenameSheet({
      hass: this._hass,
      deviceId: this._deviceId,
      host: this.shadowRoot,
      kind,
      currentInput: this._ctx.remote.sourceCode,
      currentMode: this._ctx.remote.modeCode,
      toast: (message) => this._toast(message),
      onSaved: () => {
        this._infoAt = 0;
        this._fetchInfo();
      },
    });
  }

  _stepVolume(direction) {
    const volume = this._ctx.remote.volume(this._ui.volLocal?.level);
    const max = this._info?.volume_max;
    if (max && volume.level !== null) {
      this._setVolume(clamp01(Math.round(volume.level * max + direction) / max), true);
    } else {
      this._callOn("media_player.main", "media_player", direction > 0 ? "volume_up" : "volume_down");
    }
  }

  /** Show the new volume at once and send it; `render` is false while a slider drags. */
  _setVolume(level, render) {
    this._ui.volLocal = { level };
    this._sender.set(level);
    clearTimeout(this._localTimer);
    this._localTimer = setTimeout(() => {
      this._ui.volLocal = null;
      this._render();
    }, LOCAL_VOLUME_MS);
    if (render) this._render();
  }

  async _callOn(key, domain, service, data = {}) {
    const entityId = this._ctx?.remote.entityId(key) ?? entityIds(this._hass, this._deviceId)[key];
    if (!entityId) return;
    this._busy += 1;
    this._card?.classList.add("sending");
    try {
      await this._hass.callService(domain, service, { entity_id: entityId, ...data });
    } catch (error) {
      this._toast(error?.message || String(error));
    } finally {
      this._busy -= 1;
      if (this._busy === 0 && !this._ui.pendingMode) this._card?.classList.remove("sending");
    }
  }

  _toast(message) {
    this.dispatchEvent(new CustomEvent("hass-notification", { detail: { message }, bubbles: true, composed: true }));
  }
}

if (!customElements.get("onkyo-remote-card")) customElements.define("onkyo-remote-card", OnkyoRemoteCard);

window.customCards = window.customCards || [];
if (!window.customCards.some((card) => card.type === "onkyo-remote-card")) {
  window.customCards.push({
    type: "onkyo-remote-card",
    name: "Onkyo Remote",
    description: "Remote for an Onkyo, Pioneer or Integra network receiver: power, volume, inputs, listening modes and more.",
    preview: false,
  });
}
