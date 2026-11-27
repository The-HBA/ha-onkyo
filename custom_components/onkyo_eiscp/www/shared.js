// Shared helpers of the Onkyo remote card, its editor and the sidebar page: icons, the receiver
// model read from `hass`, volume maths and the volume group every tab can use.
// No imports: the shell loads this file once and hands it to the tabs through `ctx.h`.

export const DOMAIN = "onkyo_eiscp";
export const WS_CARD_INFO = "onkyo_eiscp/card_info";
export const WS_SET_NAMES = "onkyo_eiscp/set_names";

/* Material Design Icons paths */
export const ICONS = {
  power: "M16.56,5.44L15.11,6.89C16.84,7.94 18,9.83 18,12A6,6 0 0,1 12,18A6,6 0 0,1 6,12C6,9.83 7.16,7.94 8.88,6.88L7.44,5.44C5.36,6.88 4,9.28 4,12A8,8 0 0,0 12,20A8,8 0 0,0 20,12C20,9.28 18.64,6.88 16.56,5.44M13,3H11V13H13",
  up: "M7.41,15.41L12,10.83L16.59,15.41L18,14L12,8L6,14L7.41,15.41Z",
  down: "M7.41,8.58L12,13.17L16.59,8.58L18,10L12,16L6,10L7.41,8.58Z",
  left: "M15.41,16.58L10.83,12L15.41,7.41L14,6L8,12L14,18L15.41,16.58Z",
  right: "M8.59,16.58L13.17,12L8.59,7.41L10,6L16,12L10,18L8.59,16.58Z",
  back: "M20 13.5C20 17.09 17.09 20 13.5 20H6V18H13.5C16 18 18 16 18 13.5S16 9 13.5 9H7.83L10.91 12.09L9.5 13.5L4 8L9.5 2.5L10.92 3.91L7.83 7H13.5C17.09 7 20 9.91 20 13.5Z",
  home: "M12 5.69L17 10.19V18H15V12H9V18H7V10.19L12 5.69M12 3L2 12H5V20H11V14H13V20H19V12H22",
  menu: "M3,6H21V8H3V6M3,11H21V13H3V11M3,16H21V18H3V16Z",
  remote: "M12,0C8.96,0 6.21,1.23 4.22,3.22L5.63,4.63C7.26,3 9.5,2 12,2C14.5,2 16.74,3 18.36,4.64L19.77,3.23C17.79,1.23 15.04,0 12,0M7.05,6.05L8.46,7.46C9.37,6.56 10.62,6 12,6C13.38,6 14.63,6.56 15.54,7.46L16.95,6.05C15.68,4.78 13.93,4 12,4C10.07,4 8.32,4.78 7.05,6.05M12,15A2,2 0 0,1 10,13A2,2 0 0,1 12,11A2,2 0 0,1 14,13A2,2 0 0,1 12,15M15,9H9A1,1 0 0,0 8,10V22A1,1 0 0,0 9,23H15A1,1 0 0,0 16,22V10A1,1 0 0,0 15,9Z",
  info: "M11,9H13V7H11M12,20C7.59,20 4,16.41 4,12C4,7.59 7.59,4 12,4C16.41,4 20,7.59 20,12C20,16.41 16.41,20 12,20M12,2A10,10 0 0,0 2,12A10,10 0 0,0 12,22A10,10 0 0,0 22,12A10,10 0 0,0 12,2M11,17H13V11H11V17Z",
  cog: "M12,15.5A3.5,3.5 0 0,1 8.5,12A3.5,3.5 0 0,1 12,8.5A3.5,3.5 0 0,1 15.5,12A3.5,3.5 0 0,1 12,15.5M19.43,12.97C19.47,12.65 19.5,12.33 19.5,12C19.5,11.67 19.47,11.34 19.43,11L21.54,9.37C21.73,9.22 21.78,8.95 21.66,8.73L19.66,5.27C19.54,5.05 19.27,4.96 19.05,5.05L16.56,6.05C16.04,5.66 15.5,5.32 14.87,5.07L14.5,2.42C14.46,2.18 14.25,2 14,2H10C9.75,2 9.54,2.18 9.5,2.42L9.13,5.07C8.5,5.32 7.96,5.66 7.44,6.05L4.95,5.05C4.73,4.96 4.46,5.05 4.34,5.27L2.34,8.73C2.21,8.95 2.27,9.22 2.46,9.37L4.57,11C4.53,11.34 4.5,11.67 4.5,12C4.5,12.33 4.53,12.65 4.57,12.97L2.46,14.63C2.27,14.78 2.21,15.05 2.34,15.27L4.34,18.73C4.46,18.95 4.73,19.03 4.95,18.95L7.44,17.94C7.96,18.34 8.5,18.68 9.13,18.93L9.5,21.58C9.54,21.82 9.75,22 10,22H14C14.25,22 14.46,21.82 14.5,21.58L14.87,18.93C15.5,18.67 16.04,18.34 16.56,17.94L19.05,18.95C19.27,19.03 19.54,18.95 19.66,18.73L21.66,15.27C21.78,15.05 21.73,14.78 21.54,14.63L19.43,12.97Z",
  volHigh: "M14,3.23V5.29C16.89,6.15 19,8.83 19,12C19,15.17 16.89,17.84 14,18.7V20.77C18,19.86 21,16.28 21,12C21,7.72 18,4.14 14,3.23M16.5,12C16.5,10.23 15.5,8.71 14,7.97V16C15.5,15.29 16.5,13.76 16.5,12M3,9V15H7L12,20V4L7,9H3Z",
  volOff: "M12,4L9.91,6.09L12,8.18M4.27,3L3,4.27L7.73,9H3V15H7L12,20V13.27L16.25,17.53C15.58,18.04 14.83,18.46 14,18.7V20.77C15.38,20.45 16.63,19.82 17.68,18.96L19.73,21L21,19.73L12,10.73M19,12C19,12.94 18.8,13.82 18.46,14.64L19.97,16.15C20.62,14.91 21,13.5 21,12C21,7.72 18,4.14 14,3.23V5.29C16.89,6.15 19,8.83 19,12M16.5,12C16.5,10.23 15.5,8.71 14,7.97V10.18L16.45,12.63C16.5,12.43 16.5,12.21 16.5,12Z",
  plus: "M19,13H13V19H11V13H5V11H11V5H13V11H19V13Z",
  minus: "M19,13H5V11H19V13Z",
  close: "M19,6.41L17.59,5L12,10.59L6.41,5L5,6.41L10.59,12L5,17.59L6.41,19L12,13.41L17.59,19L19,17.59L13.41,12L19,6.41Z",
  pencil: "M20.71,7.04C21.1,6.65 21.1,6 20.71,5.63L18.37,3.29C18,2.9 17.35,2.9 16.96,3.29L15.12,5.12L18.87,8.87M3,17.25V21H6.75L17.81,9.93L14.06,6.18L3,17.25Z",
  alertO: "M11,15H13V17H11V15M11,7H13V13H11V7M12,2C6.47,2 2,6.5 2,12A10,10 0 0,0 12,22A10,10 0 0,0 22,12A10,10 0 0,0 12,2M12,20A8,8 0 0,1 4,12A8,8 0 0,1 12,4A8,8 0 0,1 20,12A8,8 0 0,1 12,20Z",
  open: "M14,3V5H17.59L7.76,14.83L9.17,16.24L19,6.41V10H21V3M19,19H5V5H12V3H5C3.89,3 3,3.9 3,5V19A2,2 0 0,0 5,21H19A2,2 0 0,0 21,19V12H19V19Z",
  monitor: "M21,16H3V4H21M21,2H3C1.89,2 1,2.89 1,4V16A2,2 0 0,0 3,18H10V20H8V22H16V20H14V18H21A2,2 0 0,0 23,16V4C23,2.89 22.1,2 21,2Z",
  speaker: "M12,12A3,3 0 0,0 9,15A3,3 0 0,0 12,18A3,3 0 0,0 15,15A3,3 0 0,0 12,12M12,20A5,5 0 0,1 7,15A5,5 0 0,1 12,10A5,5 0 0,1 17,15A5,5 0 0,1 12,20M12,4A2,2 0 0,1 14,6A2,2 0 0,1 12,8C10.89,8 10,7.1 10,6C10,4.89 10.89,4 12,4M17,2H7C5.89,2 5,2.89 5,4V20A2,2 0 0,0 7,22H17A2,2 0 0,0 19,20V4C19,2.89 18.1,2 17,2Z",
  play: "M10,16.5V7.5L16,12M12,2A10,10 0 0,0 2,12A10,10 0 0,0 12,22A10,10 0 0,0 22,12A10,10 0 0,0 12,2Z",
  note: "M12 3V13.55C11.41 13.21 10.73 13 10 13C7.79 13 6 14.79 6 17S7.79 21 10 21 14 19.21 14 17V7H18V3H12Z",
  grid: "M3,11H11V3H3M3,21H11V13H3M13,21H21V13H13M13,3V11H21V3",
  dots: "M16,12A2,2 0 0,1 18,10A2,2 0 0,1 20,12A2,2 0 0,1 18,14A2,2 0 0,1 16,12M10,12A2,2 0 0,1 12,10A2,2 0 0,1 14,12A2,2 0 0,1 12,14A2,2 0 0,1 10,12M4,12A2,2 0 0,1 6,10A2,2 0 0,1 8,12A2,2 0 0,1 6,14A2,2 0 0,1 4,12Z",
  drag: "M21,11H3V9H21V11M21,13H3V15H21V13Z",
  sleep: "M18.73,18C15.4,21.69 9.71,22 6,18.64C2.33,15.31 2.04,9.62 5.37,5.93C6.9,4.25 9,3.2 11.27,3C7.96,6.7 8.27,12.39 12,15.71C13.63,17.19 15.78,18 18,18C18.25,18 18.5,18 18.73,18Z",
};

export const icon = (name, size = 24) =>
  `<svg viewBox="0 0 24 24" width="${size}" height="${size}" aria-hidden="true"><path fill="currentColor" d="${ICONS[name] ?? ""}"/></svg>`;

const ESCAPES = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" };
export const esc = (text) => String(text ?? "").replace(/[&<>"]/g, (c) => ESCAPES[c]);

/** The tokens of a receiver in the entity registry that the frontend sees, by `domain.key`. */
export function entityIds(hass, deviceId) {
  const ids = {};
  for (const entry of Object.values(hass?.entities ?? {})) {
    if (entry.platform !== DOMAIN || entry.device_id !== deviceId || !entry.translation_key) continue;
    ids[`${entry.entity_id.split(".")[0]}.${entry.translation_key}`] = entry.entity_id;
  }
  return ids;
}

/** Every Onkyo receiver the frontend knows: `[{ id, name }]`, by name. */
export function receivers(hass) {
  const seen = new Map();
  for (const entry of Object.values(hass?.entities ?? {})) {
    if (entry.platform !== DOMAIN || !entry.device_id || seen.has(entry.device_id)) continue;
    const device = hass.devices?.[entry.device_id];
    seen.set(entry.device_id, {
      id: entry.device_id,
      name: device?.name_by_user || device?.name || "Onkyo",
    });
  }
  return [...seen.values()].sort((a, b) => a.name.localeCompare(b.name));
}

/** The device the card shows: the configured one, else the first receiver. */
export function pickDevice(hass, config) {
  if (config?.device_id) return config.device_id;
  return receivers(hass)[0]?.id ?? null;
}

const DIRAC_LABELS = { off: "Off", slot_1: "Slot 1", slot_2: "Slot 2", slot_3: "Slot 3" };

/** An option key as the user reads it ("preset_1" becomes "Preset 1"). */
export function optionLabel(hass, stateObj, option) {
  if (stateObj && typeof hass?.formatEntityState === "function") {
    const text = hass.formatEntityState(stateObj, option);
    if (text && text !== option) return text;
  }
  if (DIRAC_LABELS[option]) return DIRAC_LABELS[option];
  const words = String(option).replaceAll("_", " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/* ---------------------------------------------------------------- volume (RULES.md 16) */

const MINUS = "−";

export const formatDb = (value) =>
  `${value > 0 ? "+" : value < 0 ? MINUS : ""}${Math.abs(value).toFixed(1)} dB`;

/**
 * The main zone's volume. `level` is the media player's `volume_level` (1.0 = the maximum
 * volume option), `max` the raw maximum from `card_info`, `db` the dB value (null on models
 * without a dB scale).
 */
export function readVolume(player, info, local) {
  const attrs = player?.attributes ?? {};
  const level = typeof local === "number" ? local : Number(attrs.volume_level);
  const max = Number.isFinite(Number(info?.volume_max)) ? Number(info.volume_max) : null;
  if (!Number.isFinite(level)) return { level: null, max, raw: null, db: null, hasDb: false };
  const raw = max === null ? null : Math.round(level * max);
  const step = info?.volume_db_step ?? null;
  let db = null;
  if (attrs.volume_db !== undefined && attrs.volume_db !== null && Number.isFinite(Number(attrs.volume_db))) {
    db = Number(attrs.volume_db);
    if (typeof local === "number" && step && max) {
      // The dB value of the state belongs to the state's own raw volume; shift it for a local level.
      db += (raw - Math.round(Number(attrs.volume_level) * max)) * step;
    }
  }
  return {
    level,
    max,
    raw,
    db,
    hasDb: db !== null,
    percent: Math.round(level * 100),
    muted: attrs.is_volume_muted === true,
  };
}

/** The two readouts of the Volume group: `{ main, small }` as HTML-safe text. */
export function volumeTexts(volume, unit) {
  if (volume.level === null) return { main: "", small: "" };
  const percent = `${volume.percent} %`;
  const own = volume.hasDb
    ? formatDb(volume.db)
    : volume.raw !== null
      ? `${volume.raw} / ${volume.max}`
      : "";
  const wantPercent = unit === "percent" || !own;
  return { main: wantPercent ? percent : own, small: wantPercent ? own : percent };
}

export const clamp01 = (value) => Math.min(1, Math.max(0, value));

/** Sends the newest volume only: while a call runs, later values replace each other. */
export class VolumeSender {
  constructor(send) {
    this._send = send;
    this._next = null;
    this._busy = false;
  }

  set(level) {
    this._next = level;
    if (!this._busy) this._flush();
  }

  async _flush() {
    this._busy = true;
    try {
      while (this._next !== null) {
        const level = this._next;
        this._next = null;
        await this._send(level);
      }
    } finally {
      this._busy = false;
    }
  }
}

/* ---------------------------------------------------------------- the receiver model */

/** Reads one receiver out of `hass`. Built again for every render; holds no state. */
export class Remote {
  constructor(hass, deviceId, info = null) {
    this.hass = hass;
    this.deviceId = deviceId;
    this.info = info;
    this.ids = entityIds(hass, deviceId);
  }

  entityId(key) {
    return this.ids[key];
  }

  state(key) {
    const id = this.ids[key];
    return id ? this.hass.states?.[id] : undefined;
  }

  get player() {
    return this.state("media_player.main");
  }

  /** "on", "standby" or "unavailable" (not connected, or no entity yet). */
  get power() {
    const value = this.player?.state;
    if (value === "on") return "on";
    if (value === "off") return "standby";
    return "unavailable";
  }

  get name() {
    const device = this.hass.devices?.[this.deviceId];
    return device?.name_by_user || device?.name || this.player?.attributes?.friendly_name || "Onkyo";
  }

  get source() {
    return this.player?.attributes?.source ?? "";
  }

  get sources() {
    return this.player?.attributes?.source_list ?? [];
  }

  get sourceCode() {
    return this.player?.attributes?.source_code ?? "";
  }

  get mode() {
    return this.player?.attributes?.sound_mode ?? "";
  }

  get modeCode() {
    return this.player?.attributes?.sound_mode_code ?? "";
  }

  /** The listening modes the receiver accepts now: `[{ code, name }]`, in the receiver's order. */
  get modes() {
    const attrs = this.player?.attributes ?? {};
    const names = attrs.sound_mode_list ?? [];
    const codes = attrs.sound_mode_codes ?? [];
    return names.map((name, index) => ({ name, code: codes[index] ?? "" }));
  }

  /** Mode code to group name ("stereo", "surround", "thx", "dsp", "other"). */
  groupOf(code) {
    return this.info?.listening_mode_groups?.[code] ?? "other";
  }

  get zones() {
    return this.info?.zones ?? ["main"];
  }

  volume(local) {
    return readVolume(this.player, this.info, local);
  }
}

/* ---------------------------------------------------------------- small HTML pieces */

export const notice = (text) => `<div class="notice wide">${icon("sleep", 22)}<span>${esc(text)}</span></div>`;
export const qnote = (text) => `<div class="qnote wide">${icon("alertO", 18)}<span>${esc(text)}</span></div>`;

export const editButton = (ctx, kind) =>
  ctx.admin
    ? `<button class="tbtn pr" data-a="rename" data-v="${kind}">${icon("pencil", 18)}Edit</button>`
    : "";

/** A segmented grid of options: `[{ value, label, selected, pending }]`. */
export function segmented(options, { action, key = "", cols = 4, dense = false, extra = "" }) {
  const keyAttr = key ? ` data-k="${esc(key)}"` : "";
  return `<div class="seg ${dense ? "dense " : ""}${extra}" style="--cols:${cols}">${options
    .map(
      (o) =>
        `<button class="opt pr ${o.pending ? "pend" : o.selected ? "sel" : ""}" data-a="${action}"${keyAttr} data-v="${esc(o.value)}">${o.html ?? esc(o.label)}</button>`,
    )
    .join("")}</div>`;
}

/** The Volume group: readout (tap to switch unit), mute, minus, slider, plus. */
export function volumeGroup(ctx) {
  const volume = ctx.remote.volume(ctx.ui.volLocal?.level);
  const texts = volumeTexts(volume, ctx.ui.volumeUnit);
  const f = volume.level === null ? 0 : clamp01(volume.level);
  const readout = volume.muted
    ? `Muted<small>${esc(texts.main)}</small>`
    : `${esc(texts.main)}<small>${esc(texts.small)}</small>`;
  return `<div class="grp ctl"><div class="gh"><span class="gt">Volume</span><button class="vread pr" data-vol-readout data-a="unit" aria-label="Switch between ${volume.hasDb ? "dB" : "receiver units"} and percent">${readout}</button></div>
    <div class="srow"><button class="ibtn pr ${volume.muted ? "sel" : ""}" data-a="mute" aria-label="Mute" aria-pressed="${volume.muted}">${icon(volume.muted ? "volOff" : "volHigh")}</button>
    <button class="ibtn pr" data-a="vol" data-v="-1" data-rep aria-label="Volume down">${icon("minus")}</button>
    <div class="slider ${volume.muted ? "muted" : ""}" data-slider style="--f:${f.toFixed(4)}" role="slider" tabindex="0" aria-label="Volume" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${volume.percent ?? 0}"><div class="fill"></div><div class="hdl"></div></div>
    <button class="ibtn pr" data-a="vol" data-v="1" data-rep aria-label="Volume up">${icon("plus")}</button></div></div>`;
}

export const HELPERS = {
  icon,
  esc,
  notice,
  qnote,
  editButton,
  segmented,
  volumeGroup,
  optionLabel,
  formatDb,
  volumeTexts,
};
