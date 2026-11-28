// Advanced settings of the sidebar page: the receiver's configuration (input and output assign,
// speaker levels, distances, crossovers, equalizer, per-input audio, power, zones and more).
// They come from the integration's websocket commands onkyo_eiscp/ci_info, ci_read, ci_set and
// ci_restore (ci_api.py); a model that does not answer them shows nothing (RULES.md 4).
// Calibration families can be restored; the speaker layout and the network are read-only.

const VERSION = new URL(import.meta.url).search;
const { esc, icon } = await import(new URL(`./shared.js${VERSION}`, import.meta.url).href);

const WS = {
  info: "onkyo_eiscp/ci_info",
  read: "onkyo_eiscp/ci_read",
  set: "onkyo_eiscp/ci_set",
  restore: "onkyo_eiscp/ci_restore",
};

/** The groups on the page, in order; each lists the families it holds. */
export const GROUPS = [
  { id: "assign", title: "Input assign", note: "Which physical jack each input uses", families: ["SLC", "HIC", "DIC", "AAC", "VIC", "ISC"] },
  { id: "names", title: "Input names and volume", note: "The receiver's own names and the volume an input starts at", families: ["NMC", "IVC"] },
  { id: "audio", title: "Per-input audio and HDMI", note: "Defaults each input uses", families: ["AKC", "HLC"] },
  { id: "tv", title: "TV out and HDMI", note: "CEC, ARC, standby through, screen saver", families: ["TOC", "HDC"] },
  { id: "speakers", title: "Speaker levels, distances and crossover", note: "Part of the Dirac calibration: every change can be restored", families: ["LCC", "SDC", "COC"], calibration: true },
  { id: "eq", title: "Equalizer", note: "Manual equalizer and subwoofer equalizer", families: ["EQC", "SWC"] },
  { id: "power", title: "Power and volume", note: "Auto standby, volume display and limits", families: ["APC", "VLC"] },
  { id: "zones", title: "Multi-zone", note: "Zone volume limits and 12 V triggers", families: ["MZC", "TGC"] },
  { id: "other", title: "Other options", note: "Smaller options; the meaning of some is not documented", families: ["SCC", "DSC", "TXC", "SVC", "MMC", "DLC", "DTC", "BTC", "PZC", "RMC", "UDC", "WSC"] },
  { id: "readonly", title: "Read only", note: "Speaker layout and network: shown, never changed from here", families: ["CFC", "NTC", "N2C", "LLC", "TNC", "LKC"], readonly: true },
];

// Selector keys (the SL field) and the short keys inside HIC, VIC, DIC, AAC, ISC and TGC.
const SELECTOR_INPUT = { BD: "10", GAM: "02", CBL: "01", STB: "11", PC: "05", AUX: "03", CD: "23", TV: "12", PHO: "22", TUN: "24", NET: "2B", BLT: "2E" };
const SELECTOR_NAME = { BD: "BD/DVD", GAM: "Game", CBL: "Cable/Sat", STB: "Stream box", PC: "PC", AUX: "Aux", CD: "CD", TV: "TV", PHO: "Phono", TUN: "Tuner", NET: "Network", BLT: "Bluetooth" };
const SHORT_SELECTOR = { BD: "BD", CB: "CBL", GM: "GAM", ST: "STB", PC: "PC", AX: "AUX", CD: "CD", TV: "TV", PH: "PHO", TN: "TUN", NT: "NET", BT: "BLT" };
const PER_INPUT_FIELDS = new Set(["HIC", "VIC", "DIC", "AAC", "ISC", "TGC"]);

const WORDS = { NON: "None", OFF: "Off", LST: "Last used", AUT: "Auto", REL: "Relative (0 to 100)", ABS: "Absolute (dB)", HDM: "HDMI", ANA: "Analog", ARC: "ARC", DIG: "Digital", PHO: "Phono", ENG: "English" };
const FIXED = {
  HIC: Object.fromEntries(["NON", ...Array.from({ length: 8 }, (_, i) => `HI${i + 1}`)].map((v) => [v, v === "NON" ? "None" : `HDMI ${v.slice(2)}`])),
  DIC: { NON: "None", C1N: "Coaxial 1", C2N: "Coaxial 2", O1N: "Optical 1", O2N: "Optical 2" },
  AAC: { NON: "None", AI1: "Analog 1", AI2: "Analog 2", AI3: "Analog 3", AI4: "Analog 4", AI5: "Analog 5", AI6: "Analog 6", PHO: "Phono" },
};

const SPEAKERS = { FL: "Front left", CT: "Center", FR: "Front right", HL: "Height left", HR: "Height right", "2L": "Height 2 left", "2R": "Height 2 right", SR: "Surround right", BR: "Surround back right", BL: "Surround back left", SL: "Surround left", SW: "Subwoofer", S2: "Subwoofer 2" };
const CROSSOVER = { FR: "Front", CT: "Center", H1: "Height 1", H2: "Height 2", SR: "Surround", SB: "Surround back", LF: "Subwoofer low pass" };

/** Field labels by family; a field not listed shows as "Option XX". `bit` = on/off. */
const LABELS = {
  NMC: { NM: "Name" },
  SLC: { AS: "Audio source" },
  ISC: {},
  TOC: { LG: "OSD language", SS: "Screen saver", HS: "Option HS" },
  IVC: { IV: "Volume when selected" },
  AKC: { MO: "Music Optimizer", DF: "Digital filter", EQ: "Equalizer" },
  HDC: { CE: "HDMI CEC", AR: "ARC", HT: "HDMI standby through", AO: "Audio to TV" },
  APC: { AP: "Auto standby" },
  VLC: { VD: "Volume display", MV: "Maximum volume", PV: "Power-on volume", HP: "Headphone volume", ML: "Minimum level" },
  MZC: { MV: "Maximum volume", PV: "Power-on volume" },
  LCC: SPEAKERS,
  SDC: { ...SPEAKERS, UN: "Unit" },
  COC: { ...CROSSOVER, DB: "Dirac Bass Control", XT: "Option XT", DL: "Option DL" },
  SWC: { F1: "Band 1 frequency (Hz)", L1: "Band 1 level", F2: "Band 2 frequency (Hz)", L2: "Band 2 level", F3: "Band 3 frequency (Hz)", L3: "Band 3 level" },
  CFC: { SC: "Layout", SW: "Subwoofers", H1: "Height 1", H2: "Height 2", IM: "Impedance" },
  NTC: { IP: "IP address", SN: "Subnet mask", GW: "Gateway", DS: "DNS", MA: "MAC address" },
  N2C: { FN: "Friendly name", AN: "Name" },
};
const BITS = { HDC: ["CE", "AR", "AO"], AKC: ["MO"], ISC: "all", BTC: [], APC: [] };
/** Fields shown in tenths of a dB and the ones that are plain signed steps. */
const TENTHS = new Set(["LCC"]);
const FAMILY_NOTES = {
  SDC: "Distances in the receiver's own units (the Unit field says metres or feet).",
  COC: "Frequencies in Hz.",
  EQC: "Band levels in the receiver's steps.",
  VIC: "The TX-RZ50 ignores changes to video assign, so they are shown only.",
  ISC: "On means the input is skipped when you cycle through the inputs.",
};
/** Shown, never written from the page (the TX-RZ50 ignores the writes). */
const SHOWN_ONLY = new Set(["VIC"]);

const isAdminUser = (hass) => hass.user?.is_admin === true;

/** How a field is shown, from its pattern: bit, select, mixed (words or a number), signed, number, text. */
export function kindOf(code, name, pattern) {
  if (!pattern) return "text";
  if (FIXED[code]) return "select";
  if (pattern === "00[01]" || (BITS[code] === "all") || (BITS[code] ?? []).includes(name)) return "bit";
  const parts = pattern.split("|");
  const literal = (part) => /^[A-Z0-9]+$/.test(part);
  if (parts.every(literal)) return "select";
  if (parts.some((part) => part === "\\d{3}") && parts.filter((part) => part !== "\\d{3}").every(literal)) return parts.length === 1 ? "number" : "mixed";
  if (parts.some((part) => part.includes("[+-]") || part.startsWith("-"))) return "signed";
  if (pattern === "[A-Z]{3}") return "text3";
  return "text";
}

export class CiSettings {
  constructor({ hass, deviceId, info, toast, host }) {
    this.hass = hass;
    this.deviceId = deviceId;
    this.cardInfo = info;
    this.toast = toast;
    this.root = document.createElement("div");
    this.root.className = "ci";
    this.state = "idle"; // idle, loading, ready, none (the model has no CI settings), error
    this.families = {};
    this.open = new Set();
    this.openBlocks = new Set();
    this.data = {};
    this.busy = new Set();
    this.errors = {};
    this.root.addEventListener("click", (event) => this._onClick(event));
    this.root.addEventListener("change", (event) => this._onChange(event));
    void host;
  }

  /** Fetch the family list once; until then (and for a model without CI) nothing shows. */
  async start() {
    if (this.state !== "idle") return;
    this.state = "loading";
    try {
      const result = await this.hass.callWS({ type: WS.info, device_id: this.deviceId });
      this.families = Object.fromEntries(result.families.map((family) => [family.code, family]));
      this.state = result.supported ? "ready" : "none";
    } catch (error) {
      console.debug("onkyo-panel: ci_info failed", error);
      this.state = "error";
    }
    this._schedule();
  }

  setInfo(info) {
    this.cardInfo = info;
  }

  // ------------------------------------------------------------------ labels

  _inputLabel(selector) {
    const code = SELECTOR_INPUT[selector];
    const found = this.cardInfo?.inputs?.find((item) => item.code === code);
    return found?.custom || found?.name || SELECTOR_NAME[selector] || selector;
  }

  _keyTitle(family, key) {
    const parts = [];
    for (const [name, value] of Object.entries(key)) {
      if (name === "SL") parts.push(this._inputLabel(value));
      else if (name === "MM") parts.push(value === "OFF" ? "Dirac off" : `Dirac slot ${value.slice(2)}`);
      else if (name === "XM") parts.push(value === "DBC" ? "with Dirac Bass Control" : "independent");
      else if (name === "PS") parts.push(`Preset ${Number(value)}`);
      else if (name === "CH") parts.push({ FRT: "Front", CTR: "Center", HI1: "Height 1", HI2: "Height 2", SUR: "Surround", SBK: "Surround back", SWF: "Subwoofer" }[value] ?? value);
      else if (name === "ZN") parts.push(`Zone ${Number(value)}`);
      else if (name === "SO") parts.push(`Option set ${Number(value) + 1}`);
      else parts.push(value);
    }
    return parts.join(", ") || family.title;
  }

  _fieldLabel(code, name) {
    if (PER_INPUT_FIELDS.has(code) && SHORT_SELECTOR[name]) return this._inputLabel(SHORT_SELECTOR[name]);
    if (code === "EQC") return `Band ${parseInt(name.slice(1), 16)}`;
    return LABELS[code]?.[name] ?? `Option ${name}`;
  }

  // ------------------------------------------------------------------ data

  async _load(group) {
    for (const code of group.families) {
      if (!this.families[code] || this.data[code] || this.busy.has(code)) continue;
      this.busy.add(code);
      this._schedule();
      try {
        const result = await this.hass.callWS({ type: WS.read, device_id: this.deviceId, code });
        this.data[code] = result.records;
        delete this.errors[code];
      } catch (error) {
        this.errors[code] = error?.message || String(error);
      }
      this.busy.delete(code);
      this._schedule();
    }
  }

  async _change(code, key, field, value) {
    const id = `${code}/${JSON.stringify(key)}/${field}`;
    if (this.busy.has(id)) return;
    this.busy.add(id);
    this._schedule();
    try {
      const result = await this.hass.callWS({ type: WS.set, device_id: this.deviceId, code, key, changes: { [field]: value } });
      this._store(code, result);
    } catch (error) {
      this.toast(error?.message || String(error));
    }
    this.busy.delete(id);
    this._schedule();
  }

  _store(code, result) {
    const records = this.data[code] ?? [];
    const family = this.families[code];
    const same = (record) => JSON.stringify(record.key) === JSON.stringify(result.key ?? {});
    const index = records.findIndex(same);
    if (index >= 0) records[index] = { key: result.key, fields: result.fields, restorable: result.restorable ?? [] };
    // Shared fields repeat in every record of the family.
    for (const record of records) {
      for (const name of family?.shared ?? []) if (name in result.fields) record.fields[name] = result.fields[name];
    }
    this.data[code] = records;
  }

  async _restore(code, key, keep) {
    const id = `${code}/${JSON.stringify(key)}/restore`;
    if (this.busy.has(id)) return;
    this.busy.add(id);
    this._schedule();
    try {
      const result = await this.hass.callWS({ type: WS.restore, device_id: this.deviceId, code, key, ...(keep ? { keep: true } : {}) });
      if (keep) {
        const record = this.data[code]?.find((item) => JSON.stringify(item.key) === JSON.stringify(key));
        if (record) record.restorable = [];
      } else {
        this._store(code, result);
      }
    } catch (error) {
      this.toast(error?.message || String(error));
    }
    this.busy.delete(id);
    this._schedule();
  }

  // ------------------------------------------------------------------ events

  _onClick(event) {
    const button = event.target.closest("[data-ci]");
    if (!button) return;
    const { ci, group, code } = button.dataset;
    if (ci === "group") {
      if (this.open.has(group)) this.open.delete(group);
      else {
        this.open.add(group);
        void this._load(GROUPS.find((item) => item.id === group));
      }
      this._schedule();
    } else if (ci === "block") {
      const id = button.dataset.block;
      if (this.openBlocks.has(id)) this.openBlocks.delete(id);
      else this.openBlocks.add(id);
      this._schedule();
    } else if (ci === "retry") {
      delete this.errors[code];
      void this._load(GROUPS.find((item) => item.id === group));
    } else if (ci === "restore" || ci === "keep") {
      void this._restore(code, JSON.parse(button.dataset.key), ci === "keep");
    } else if (ci === "toggle") {
      void this._change(code, JSON.parse(button.dataset.key), button.dataset.field, button.getAttribute("aria-checked") === "true" ? "000" : "001");
    }
  }

  _onChange(event) {
    const control = event.target.closest("[data-ci-field]");
    if (!control) return;
    const { code, field, kind } = control.dataset;
    if (kind === "mixed" && control.dataset.part === "word" && control.value === "#") {
      // "Level" chosen: ask for the number first, then set.
      const number = control.closest("[data-cell]").querySelector("input[data-part=number]");
      number.hidden = false;
      number.focus();
      return;
    }
    const key = JSON.parse(control.dataset.key);
    const family = this.families[code];
    const spec = family.fields[field];
    const cell = control.closest("[data-cell]");
    let value = control.value;
    try {
      value = this._encode(kind, cell, control, spec);
    } catch (error) {
      this.toast(error.message);
      this._schedule();
      return;
    }
    void this._change(code, key, field, value);
  }

  /** Turn what the controls of one field hold into the receiver's value text. */
  _encode(kind, cell, control, spec) {
    const width = spec.width;
    const pick = cell.querySelector("select[data-part=word]");
    const number = cell.querySelector("input[data-part=number]");
    if (kind === "select") return control.value;
    if (kind === "mixed") {
      if (pick.value !== "#") return pick.value;
      return pad(number.value, width);
    }
    if (kind === "number") return pad(control.value, width);
    if (kind === "signed") {
      const tenths = control.dataset.scale === "tenths";
      const raw = Number(control.value);
      if (control.value === "" || Number.isNaN(raw)) throw new Error("Enter a number");
      const steps = Math.round(tenths ? raw * 10 : raw);
      if (Math.abs(steps) > 99) throw new Error("The value is out of range");
      return steps === 0 ? "000" : `${steps > 0 ? "+" : "-"}${String(Math.abs(steps)).padStart(2, "0")}`;
    }
    if (kind === "text") return control.value;
    return control.value.toUpperCase();
  }

  // ------------------------------------------------------------------ render

  /** Draw after the event that asked for it has finished (a control must not vanish mid-event). */
  _schedule() {
    if (this._queued) return;
    this._queued = true;
    queueMicrotask(() => {
      this._queued = false;
      this.render();
    });
  }

  render() {
    if (this.state === "idle" || this.state === "loading" || this.state === "none" || this.state === "error") {
      this.root.innerHTML = "";
      return;
    }
    const admin = isAdminUser(this.hass);
    const groups = GROUPS.map((group) => this._groupHtml(group, admin)).filter(Boolean);
    if (!groups.length) {
      this.root.innerHTML = "";
      return;
    }
    const note = admin ? "" : `<div class="qnote">${icon("alertO", 18)}<span>Only an administrator can change these settings.</span></div>`;
    this.root.innerHTML = `<div class="grp cig"><div class="gh"><span class="gt">Advanced settings</span></div>${note}${groups.join("")}</div>`;
  }

  _groupHtml(group, admin) {
    const present = group.families.filter((code) => this.families[code]);
    const loaded = present.filter((code) => this.data[code] !== undefined);
    // A family the model does not answer is gone; a group without any family is gone with them.
    const missing = present.filter((code) => this.data[code]?.length === 0);
    if (!present.length || (loaded.length === present.length && missing.length === present.length)) return "";
    const open = this.open.has(group.id);
    const head = `<button class="setlink pr cih" data-ci="group" data-group="${group.id}" aria-expanded="${open}">
      <span class="n">${esc(group.title)}<small>${esc(group.note)}</small></span>${icon(open ? "up" : "right", 22)}</button>`;
    if (!open) return `<div class="cigroup">${head}</div>`;
    const body = present.map((code) => this._familyHtml(group, code, admin)).join("");
    const intro = group.calibration
      ? `<div class="notice">${icon("alertO", 22)}<span>These hold your Dirac calibration. The first change to a record saves its old values; Restore puts them back.</span></div>`
      : "";
    return `<div class="cigroup open">${head}<div class="cibody">${intro}${body}</div></div>`;
  }

  _familyHtml(group, code, admin) {
    const family = this.families[code];
    if (this.busy.has(code)) return `<div class="empty">Reading ${esc(family.title.toLowerCase())}</div>`;
    if (this.errors[code]) {
      return `<div class="qnote">${icon("alertO", 18)}<span>${esc(family.title)}: ${esc(this.errors[code])}</span>
        <button class="pill pr" data-ci="retry" data-group="${group.id}" data-code="${code}">Try again</button></div>`;
    }
    const records = this.data[code];
    if (!records) return "";
    if (!records.length) return "";
    // Video assign with every input on None means the model has no analog video: nothing to show.
    if (code === "VIC" && records.every((record) => Object.values(record.fields).every((item) => item === "NON"))) return "";
    const canWrite = admin && family.writable && !group.readonly && !SHOWN_ONLY.has(code);
    const note = FAMILY_NOTES[code] ? `<div class="qnote">${esc(FAMILY_NOTES[code])}</div>` : "";
    const sharedNames = family.shared.filter((name) => name in (records[0]?.fields ?? {}));
    const shared = sharedNames.length ? this._blockHtml(family, `${code}/shared`, Object.keys(records[0].key).includes("SL") ? "All inputs" : "All records", records[0].key, sharedNames, records[0], canWrite, false) : "";
    const blocks = records.map((record) => {
      const names = Object.keys(record.fields).filter((name) => !sharedNames.includes(name));
      if (!names.length) return "";
      const title = Object.keys(record.key).length ? this._keyTitle(family, record.key) : family.title;
      return this._blockHtml(family, `${code}/${JSON.stringify(record.key)}`, title, record.key, names, record, canWrite, family.calibration);
    });
    const withHeader = records.length > 1 || sharedNames.length;
    const header = withHeader ? `<div class="cifam">${esc(family.title)}</div>` : "";
    return `<div class="cifamily">${header}${note}${shared}${blocks.join("")}</div>`;
  }

  _blockHtml(family, id, title, key, names, record, canWrite, calibration) {
    const code = family.code;
    const single = Object.keys(key).length === 0 && id.endsWith(`/${JSON.stringify(key)}`);
    const expanded = single || this.openBlocks.has(id) || names.length <= 2;
    const keyText = esc(JSON.stringify(key));
    const restorable = calibration && record.restorable?.length;
    const actions = restorable
      ? `<div class="ciact"><span>${record.restorable.length} changed</span>
          <button class="pill pr" data-ci="restore" data-code="${code}" data-key="${keyText}">Restore</button>
          <button class="pill pr" data-ci="keep" data-code="${code}" data-key="${keyText}">Keep</button></div>`
      : "";
    const rows = names.map((name) => this._fieldHtml(family, key, name, record.fields[name], canWrite)).join("");
    const head = single || names.length <= 2
      ? `<div class="cih2">${esc(title)}</div>`
      : `<button class="cih2 tog" data-ci="block" data-block="${esc(id)}" aria-expanded="${expanded}"><span>${esc(title)}</span>${icon(expanded ? "up" : "right", 20)}</button>`;
    return `<div class="ciblock">${head}${actions}${expanded ? `<div class="cirows">${rows}</div>` : ""}</div>`;
  }

  _fieldHtml(family, key, name, value, canWrite) {
    const code = family.code;
    const spec = family.fields[name] ?? { width: 3, pattern: null, writable: false };
    const label = this._fieldLabel(code, name);
    const editable = canWrite && spec.writable;
    const kind = kindOf(code, name, spec.pattern);
    const busy = this.busy.has(`${code}/${JSON.stringify(key)}/${name}`);
    const keyText = esc(JSON.stringify(key));
    const data = `data-ci-field data-code="${code}" data-key="${keyText}" data-field="${name}" data-kind="${kind}"`;
    const disabled = !editable || busy ? "disabled" : "";
    let control;
    if (kind === "bit") {
      const on = value === "001";
      control = `<button class="tgl pr cit" role="switch" aria-checked="${on}" aria-label="${esc(label)}" data-ci="toggle" data-code="${code}" data-key="${keyText}" data-field="${name}" ${disabled}><span class="n">${on ? "On" : "Off"}</span><span class="sw"></span></button>`;
    } else if (kind === "select") {
      control = `<select ${data} aria-label="${esc(label)}" ${disabled}>${this._options(code, spec, value)}</select>`;
    } else if (kind === "mixed") {
      const words = spec.pattern.split("|").filter((part) => /^[A-Z0-9]+$/.test(part));
      const isNumber = /^\d{3}$/.test(value);
      control = `<span data-cell class="cimix"><select data-part="word" ${data} aria-label="${esc(label)}" ${disabled}>${words.map((word) => `<option value="${word}" ${word === value ? "selected" : ""}>${esc(WORDS[word] ?? word)}</option>`).join("")}<option value="#" ${isNumber ? "selected" : ""}>Level</option></select>
        <input data-part="number" ${data} type="number" min="0" max="999" step="1" value="${isNumber ? Number(value) : ""}" ${isNumber ? "" : "hidden"} ${disabled} aria-label="${esc(label)} level"></span>`;
    } else if (kind === "number") {
      control = `<input ${data} type="number" min="0" max="999" step="1" value="${/^\d+$/.test(value) ? Number(value) : esc(value)}" ${disabled} aria-label="${esc(label)}">`;
    } else if (kind === "signed") {
      const tenths = TENTHS.has(code);
      const steps = value === "000" ? 0 : Number(value);
      const shown = tenths ? (steps / 10).toFixed(1) : String(steps);
      control = `<input ${data} data-scale="${tenths ? "tenths" : "steps"}" type="number" step="${tenths ? "0.1" : "1"}" min="${tenths ? -9.9 : -99}" max="${tenths ? 9.9 : 99}" value="${shown}" ${disabled} aria-label="${esc(label)}">${tenths ? '<span class="ciu">dB</span>' : ""}`;
    } else {
      const text = kind === "text" ? value.trimEnd() : value;
      control = `<input ${data} type="text" maxlength="${spec.width}" value="${esc(text)}" ${disabled} aria-label="${esc(label)}">`;
    }
    const wrapped = kind === "mixed" ? control : `<span data-cell class="cicell">${control}</span>`;
    return `<div class="cirow"><span class="n">${esc(label)}</span>${wrapped}</div>`;
  }

  _options(code, spec, value) {
    const fixed = FIXED[code];
    const values = fixed ? Object.keys(fixed) : spec.pattern.split("|");
    const list = values.includes(value) ? values : [...values, value];
    return list.map((item) => `<option value="${esc(item)}" ${item === value ? "selected" : ""}>${esc(fixed?.[item] ?? WORDS[item] ?? item)}</option>`).join("");
  }
}

function pad(text, width) {
  const digits = String(text).trim();
  if (!/^\d+$/.test(digits)) throw new Error("Enter a whole number");
  if (digits.length > width) throw new Error("The value is too large");
  return digits.padStart(width, "0");
}

export const CI_STYLE = `
  .ci:empty{display:none}
  .cig{background:var(--card-background-color)}
  .cigroup{display:flex;flex-direction:column;gap:8px}
  .cih{min-height:56px}
  .cibody{display:flex;flex-direction:column;gap:12px;padding:4px 0 8px}
  .cifamily{display:flex;flex-direction:column;gap:8px}
  .cifam{font-size:13px;font-weight:500;color:var(--secondary-text-color);text-transform:none}
  .ciblock{border:1px solid var(--divider-color);border-radius:var(--r);padding:8px 12px;display:flex;flex-direction:column;gap:6px}
  .cih2{font-size:14px;font-weight:500;display:flex;align-items:center;justify-content:space-between;gap:8px;min-height:32px;background:none;border:0;color:inherit;font-family:inherit;text-align:left;width:100%;padding:0}
  .cih2.tog{cursor:pointer}
  .cirows{display:flex;flex-direction:column;gap:4px}
  .cirow{display:flex;align-items:center;gap:12px;min-height:44px}
  .cirow .n{flex:1;min-width:0;font-size:14px}
  .cicell,.cimix{display:flex;align-items:center;gap:6px;flex:none;max-width:60%}
  .cirow select,.cirow input[type=number],.cirow input[type=text]{font:inherit;color:inherit;background:var(--ctl);border:0;border-radius:var(--ir);min-height:40px;padding:0 10px;min-width:0;max-width:100%}
  .cirow input[type=number]{width:96px;text-align:right}
  .cirow input[type=text]{width:150px}
  .cirow select:disabled,.cirow input:disabled{opacity:.6}
  .cit{min-height:40px;padding:0 10px;gap:8px;min-width:96px}
  .ciu{color:var(--secondary-text-color);font-size:13px}
  .ciact{display:flex;align-items:center;gap:8px;font-size:13px;color:var(--secondary-text-color)}
  .ciact span{flex:1}
  .pill{min-height:36px;padding:0 14px;border-radius:18px;background:var(--ctl);color:var(--primary-color);border:0;font:inherit;cursor:pointer}
`;
