// A small stand-in for the `hass` object Home Assistant gives a card: states, the entity
// registry as the frontend sees it, devices, callService, callWS and formatEntityState.
// It also plays the part of the receiver: a service call changes the state, as the real
// integration would after the receiver confirms. Data follows ARCHITECTURE.md C5 and the
// design round's data (Hattan's TX-RZ50 and a smaller model).

export const DEVICE_ID = "device_rz50";
export const OTHER_DEVICE_ID = "device_small";
export const PLAYER = "media_player.onkyo_tx_rz50_main";

const MODEL_RZ50 = {
  label: "Onkyo TX-RZ50",
  dirac: ["off", "slot_1", "slot_2", "slot_3"],
  zones: ["main", "zone2", "zone3"],
  volumeMax: 164,
  dbStep: 0.5,
  inputs: [
    ["10", "Movie"], ["02", "PS5"], ["01", "Wii U"], ["11", "Streaming"], ["05", "HTPC"], ["03", "AUX"],
    ["23", "CD"], ["22", "PHONO"], ["25", "AM"], ["24", "FM"], ["2B", "NET"], ["2E", "BLUETOOTH"], ["12", "Projector"],
  ],
  modes: ["82", "84", "85", "8B", "8C", "89", "8A", "08", "09", "0A", "0B", "03", "05", "06", "0E", "0C", "13", "0D", "11", "01", "00", "0F", "80", "40"],
};
const MODEL_SMALL = {
  label: "Onkyo TX-SR494",
  dirac: null,
  zones: ["main"],
  volumeMax: 80,
  dbStep: null,
  inputs: [["10", "BD/DVD"], ["01", "CBL/SAT"], ["02", "GAME"], ["11", "STRM BOX"], ["23", "CD"], ["24", "TV"], ["2B", "NET"], ["2E", "BLUETOOTH"]],
  modes: ["00", "01", "0C", "80", "82", "40", "08", "0A", "0B", "0D", "11", "0F"],
};

// Clean, unique names (lib/commands.py LISTENING_MODES) and groups (card_info listening_mode_groups).
const MODE_TABLE = {
  "00": ["Stereo", "stereo"], "01": ["Direct", "stereo"], "11": ["Pure Audio", "stereo"],
  "0C": ["All Ch Stereo", "stereo"], "0F": ["Mono", "stereo"], "13": ["Mono Music", "stereo"],
  "80": ["Dolby Surround", "surround"], "82": ["DTS Neural:X", "surround"], "40": ["Straight Decode", "surround"],
  "84": ["THX Cinema (Dolby Surround)", "thx"], "85": ["THX Cinema (Neural:X)", "thx"],
  "8B": ["THX Music (Dolby Surround)", "thx"], "8C": ["THX Music (Neural:X)", "thx"],
  "89": ["THX Games (Dolby Surround)", "thx"], "8A": ["THX Games (Neural:X)", "thx"],
  "08": ["Orchestra", "dsp"], "09": ["Unplugged", "dsp"], "0A": ["Studio-Mix", "dsp"], "0B": ["TV Logic", "dsp"],
  "0D": ["Theater-Dimensional", "dsp"], "03": ["Game-RPG", "dsp"], "05": ["Game-Action", "dsp"],
  "06": ["Game-Rock", "dsp"], "0E": ["Game-Sports", "dsp"],
};

const PCM_MODES = ["82", "84", "85", "8B", "8C", "89", "8A", "08", "09", "0A", "0B", "03", "05", "06", "0E", "0C", "13", "0D", "11", "01", "00", "0F", "80"];
const ATMOS_MODES = ["80", "08", "09", "0A", "0B", "03", "05", "06", "0E", "0C", "13", "0D", "11", "01", "00"];
const SIGNALS = {
  pcm: { modes: PCM_MODES, mode: "00", iaName: null, format: "PCM", rate: "44.1 kHz", channels: "2.0 ch", port: "ANALOG", out: "2.1 ch", video: null },
  atmos: {
    modes: ATMOS_MODES, mode: "80", iaName: "Dolby Atmos", format: "Dolby Atmos/TrueHD", rate: "48 kHz", channels: "", port: "HDMI 1", out: "6.1 ch",
    video: { port: "HDMI 1", res: "4K (3840x2160) 23 Hz", color: "RGB", depth: "24 bit", hdr: "HDR10", outRes: "4K (3840x2160) 23 Hz" },
  },
  dtsx: {
    modes: null, mode: "82", iaName: "DTS:X", format: "DTS:X", rate: "48 kHz", channels: "7.1 ch", port: "HDMI 1", out: "6.1 ch",
    video: { port: "HDMI 1", res: "4K (3840x2160) 24 Hz", color: "YCbCr 4:2:0", depth: "30 bit", hdr: "Dolby Vision", outRes: "4K (3840x2160) 24 Hz" },
  },
  none: { modes: PCM_MODES, mode: "0C", iaName: null, format: "", rate: "", channels: "", port: "ANALOG", out: "6.1 ch", video: null },
};

const LABELS = { on: "On", off: "Off", standby: "Standby", unavailable: "Unavailable" };
const PRETTY = { off: "Off", slot_1: "Slot 1", slot_2: "Slot 2", slot_3: "Slot 3" };

const mkState = (entity_id, state, attributes = {}) => ({ entity_id, state, attributes, last_changed: "", last_updated: "" });

/**
 * A fresh hass object. Options: model ("rz50" or "small"), power ("on", "standby" or
 * "unavailable"), signal ("pcm", "atmos", "dtsx", "none"), admin, otherReceiver (adds a second
 * receiver for the panel's picker).
 */
export function makeHass({ model = "rz50", power = "on", signal = "atmos", admin = true, otherReceiver = false } = {}) {
  const spec = model === "small" ? MODEL_SMALL : MODEL_RZ50;
  const rx = {
    spec,
    power: power === "unavailable" ? "off" : power,
    available: power !== "unavailable",
    signal,
    input: spec.inputs.find(([, n]) => n === "Streaming" || n === "STRM BOX")[0],
    mode: SIGNALS[signal].mode,
    raw: Math.round(spec.volumeMax * (model === "small" ? 0.65 : 104 / 164)),
    muted: false,
    inputNames: {}, // code -> { name, hidden }
    modeNames: {},
    order: null,
    dirac: "slot_3",
    numbers: { bass: -2, treble: 0, subwoofer_level: -5, center_level: 0, vocal_enhancer: 0, dialog_level: 0, av_sync: 0, sleep_timer: 0 },
    selects: { equalizer: "off", dimmer: "bright", digital_filter: "auto", hdmi_output: "main", late_night: "off" },
    switches: { cinema_filter: false, music_optimizer: false },
    keys: [],
    // Zone 2 powers on with a fixed output level (no volume); zone 3 refuses power on (TX-RZ50).
    zones: { zone2: { power: "off", source: "80", raw: 40, muted: false, volume: false }, zone3: { power: "off", source: "10", raw: 30, muted: false, volume: false, refuses: true } },
  };
  const calls = [];
  const wsCalls = [];
  const toasts = [];

  const reg = (entity_id, translation_key, device_id = DEVICE_ID) => ({ entity_id, device_id, platform: "onkyo_eiscp", translation_key });
  const hass = {
    calls,
    wsCalls,
    toasts,
    rx,
    user: { is_admin: admin, name: "Test" },
    entities: {},
    devices: {
      [DEVICE_ID]: { id: DEVICE_ID, name: spec.label, name_by_user: null },
      ...(otherReceiver ? { [OTHER_DEVICE_ID]: { id: OTHER_DEVICE_ID, name: "Onkyo TX-SR494", name_by_user: null } } : {}),
    },
    states: {},
    failNext: null,
    modeDelay: 250,
  };

  const entities = [reg(PLAYER, "main")];
  if (spec.dirac) entities.push(reg("select.onkyo_tx_rz50_dirac_live", "dirac_slot"));
  entities.push(reg("sensor.onkyo_tx_rz50_audio_input", "audio_input"));
  for (const key of Object.keys(rx.numbers)) {
    if (model === "small" && !["bass", "treble", "subwoofer_level", "center_level"].includes(key)) continue;
    entities.push(reg(`number.onkyo_tx_rz50_${key}`, key));
  }
  for (const key of Object.keys(rx.selects)) {
    if (model === "small" && !["dimmer", "late_night"].includes(key)) continue;
    entities.push(reg(`select.onkyo_tx_rz50_${key}`, key));
  }
  if (model !== "small") {
    entities.push(reg("switch.onkyo_tx_rz50_cinema_filter", "cinema_filter"));
    entities.push(reg("switch.onkyo_tx_rz50_music_optimizer", "music_optimizer"));
    entities.push(reg("sensor.onkyo_tx_rz50_video_input", "video_input"));
  }
  entities.push(reg("remote.onkyo_tx_rz50_remote", "remote"));
  for (const zone of spec.zones.slice(1)) entities.push(reg(`media_player.onkyo_tx_rz50_${zone}`, zone));
  entities.push(reg("sensor.onkyo_tx_rz50_temperature", "temperature"));
  for (const item of entities) hass.entities[item.entity_id] = item;
  hass.entities["light.ceiling"] = { entity_id: "light.ceiling", device_id: "device_light", platform: "hue" };
  hass.states["light.ceiling"] = mkState("light.ceiling", "on");
  if (otherReceiver) {
    hass.entities["media_player.onkyo_tx_sr494_main"] = reg("media_player.onkyo_tx_sr494_main", "main", OTHER_DEVICE_ID);
    hass.states["media_player.onkyo_tx_sr494_main"] = mkState("media_player.onkyo_tx_sr494_main", "off", { friendly_name: "Onkyo TX-SR494" });
  }

  const orderedInputs = () => {
    const codes = spec.inputs.map(([code]) => code);
    const wanted = (rx.order ?? []).filter((code) => codes.includes(code));
    return [...wanted, ...codes.filter((code) => !wanted.includes(code))];
  };
  const inputName = (code) => rx.inputNames[code]?.name || spec.inputs.find(([c]) => c === code)[1];
  const modeName = (code) => {
    if (rx.modeNames[code]?.name) return rx.modeNames[code].name;
    const sig = SIGNALS[rx.signal];
    if (code === rx.mode && sig.iaName && code === sig.mode) return sig.iaName;
    return MODE_TABLE[code][0];
  };
  const modeCodes = () =>
    (SIGNALS[rx.signal].modes ?? spec.modes).filter(
      (code) => spec.modes.includes(code) && (!rx.modeNames[code]?.hidden || code === rx.mode),
    );
  const sourceCodes = () => orderedInputs().filter((code) => !rx.inputNames[code]?.hidden || code === rx.input);

  const build = () => {
    const on = rx.power === "on";
    const states = hass.states;
    const unavailable = !rx.available;
    const level = rx.raw / spec.volumeMax;
    const attrs = unavailable ? {} : {
      friendly_name: spec.label,
      ...(on ? {
        source: inputName(rx.input),
        source_list: sourceCodes().map(inputName),
        sound_mode: modeName(rx.mode),
        sound_mode_list: modeCodes().map(modeName),
        sound_mode_codes: modeCodes(),
        source_code: rx.input,
        sound_mode_code: rx.mode,
        volume_level: level,
        is_volume_muted: rx.muted,
        ...(spec.dbStep ? { volume_db: rx.raw * spec.dbStep - 82 } : {}),
      } : { source_list: sourceCodes().map(inputName), source_code: rx.input }),
    };
    states[PLAYER] = mkState(PLAYER, unavailable ? "unavailable" : on ? "on" : "off", attrs);
    if (spec.dirac) {
      states["select.onkyo_tx_rz50_dirac_live"] = mkState("select.onkyo_tx_rz50_dirac_live", unavailable || !on ? "unavailable" : rx.dirac, { options: spec.dirac });
    }
    const sig = SIGNALS[rx.signal];
    const hasSignal = on && sig.format;
    states["sensor.onkyo_tx_rz50_audio_input"] = mkState(
      "sensor.onkyo_tx_rz50_audio_input",
      !on ? "unavailable" : hasSignal ? `${sig.format} ${sig.rate}`.trim() : "unknown",
      on ? { input_port: sig.port, input_format: sig.format, sample_rate: sig.rate, input_channels: sig.channels, listening_mode: modeName(rx.mode), output_channels: sig.out } : {},
    );
    const video = sig.video;
    states["sensor.onkyo_tx_rz50_video_input"] = mkState(
      "sensor.onkyo_tx_rz50_video_input",
      !on ? "unavailable" : video ? `${video.res} ${video.hdr}` : "unknown",
      on && video
        ? { input_port: video.port, input_resolution: video.res, input_color_format: video.color, input_depth: video.depth, output: "Main", output_resolution: video.outRes, output_color_format: video.color, output_depth: video.depth, hdr: video.hdr }
        : {},
    );
    for (const zone of spec.zones.slice(1)) {
      const z = rx.zones[zone];
      const zid = `media_player.onkyo_tx_rz50_${zone}`;
      const zonOn = z.power === "on";
      const zcodes = ["80", ...spec.inputs.map(([c]) => c).slice(0, 8)];
      const names = zcodes.map((c) => (c === "80" ? "Source" : inputName(c)));
      states[zid] = mkState(zid, unavailable ? "unavailable" : z.power, unavailable ? {} : {
        friendly_name: `${spec.label} ${zone}`,
        source_list: names.slice(1).concat(["Source"]),
        source_codes: zcodes.slice(1).concat(["80"]),
        source_code: z.source,
        ...(zonOn ? { source: names[zcodes.indexOf(z.source)] ?? "Source", is_volume_muted: z.muted } : {}),
        ...(zonOn && z.volume ? { volume_level: z.raw / 80, volume_db: z.raw - 80 } : {}),
      });
    }
    const mot = "switch.onkyo_tx_rz50_music_optimizer";
    states[mot] = mkState(mot, !on || rx.mode !== "00" ? "unavailable" : rx.switches.music_optimizer ? "on" : "off");
    states["remote.onkyo_tx_rz50_remote"] = mkState("remote.onkyo_tx_rz50_remote", unavailable ? "unavailable" : on ? "on" : "off");
    const ranges = { bass: [-10, 10, 1, "dB"], treble: [-10, 10, 1, "dB"], subwoofer_level: [-15, 12, 0.5, "dB"], center_level: [-12, 12, 0.5, "dB"], vocal_enhancer: [0, 5, 1, ""], dialog_level: [0, 6, 1, ""], av_sync: [-100, 500, 5, "ms"], sleep_timer: [0, 90, 1, "min"] };
    for (const [key, value] of Object.entries(rx.numbers)) {
      const id = `number.onkyo_tx_rz50_${key}`;
      if (!hass.entities[id]) continue;
      const [min, max, step, unit] = ranges[key];
      const refused = model !== "small" && ["center_level", "dialog_level"].includes(key);
      states[id] = mkState(id, unavailable || !on || refused ? "unavailable" : String(value), { min, max, step, ...(unit ? { unit_of_measurement: unit } : {}) });
    }
    const options = { late_night: ["off", "low", "high", "auto"], equalizer: ["off", "preset_1", "preset_2", "preset_3"], dimmer: ["bright", "dim", "dark"], digital_filter: ["slow", "sharp", "auto"], hdmi_output: ["off", "main", "sub", "both"] };
    for (const [key, value] of Object.entries(rx.selects)) {
      const id = `select.onkyo_tx_rz50_${key}`;
      if (hass.entities[id]) states[id] = mkState(id, unavailable ? "unavailable" : value, { options: options[key] });
    }
    if (hass.entities["switch.onkyo_tx_rz50_cinema_filter"]) {
      states["switch.onkyo_tx_rz50_cinema_filter"] = mkState("switch.onkyo_tx_rz50_cinema_filter", unavailable ? "unavailable" : rx.switches.cinema_filter ? "on" : "off");
    }
    states["sensor.onkyo_tx_rz50_temperature"] = mkState("sensor.onkyo_tx_rz50_temperature", on ? "41" : "unavailable", { unit_of_measurement: "°C" });
  };

  const info = () => ({
    entry_id: "entry1",
    device_id: DEVICE_ID,
    model: spec.label.replace("Onkyo ", ""),
    version: "0.0.3",
    zones: spec.zones,
    volume_max: spec.volumeMax,
    volume_db_step: spec.dbStep,
    dirac_slots: spec.dirac ? spec.dirac.slice(1) : [],
    // The TX-RZ50 does not support Home; the other fake models support every key.
    remote_keys: ["up", "down", "left", "right", "enter", "exit", "menu", "home", "quick", "audio", "video"].filter((key) => spec.label !== "Onkyo TX-RZ50" || key !== "home"),
    listening_mode_groups: Object.fromEntries(spec.modes.map((code) => [code, MODE_TABLE[code][1]])),
    inputs: orderedInputs().map((code) => ({
      code,
      name: spec.inputs.find(([c]) => c === code)[1],
      custom: rx.inputNames[code]?.name ?? "",
      hidden: !!rx.inputNames[code]?.hidden,
      zones: spec.zones,
    })),
    listening_modes: spec.modes.map((code) => ({
      code,
      name: MODE_TABLE[code][0],
      custom: rx.modeNames[code]?.name ?? "",
      hidden: !!rx.modeNames[code]?.hidden,
      group: MODE_TABLE[code][1],
    })),
  });

  const commit = () => {
    build();
    hass.onChange?.();
  };

  const mainPlayerCall = (service, data) => {
    switch (service) {
      case "turn_on": rx.power = "on"; break;
      case "turn_off": rx.power = "standby"; break;
      case "volume_set": rx.raw = Math.round(data.volume_level * spec.volumeMax); break;
      case "volume_up": rx.raw = Math.min(spec.volumeMax, rx.raw + 2); break;
      case "volume_down": rx.raw = Math.max(0, rx.raw - 2); break;
      case "volume_mute": rx.muted = data.is_volume_muted; break;
      case "select_source": {
        const code = spec.inputs.find(([c]) => inputName(c) === data.source)?.[0];
        if (code) rx.input = code;
        break;
      }
      default:
    }
  };

  hass.callService = async (domain, service, data = {}) => {
    calls.push({ domain, service, data });
    if (hass.failNext) {
      const message = hass.failNext;
      hass.failNext = null;
      throw new Error(message);
    }
    const key = `${domain}.${service}`;
    switch (key) {
      case "media_player.turn_on":
      case "media_player.turn_off":
      case "media_player.select_source":
      case "media_player.volume_up":
      case "media_player.volume_down":
      case "media_player.volume_mute":
      case "media_player.volume_set": {
        const zone = Object.keys(rx.zones).find((id) => data.entity_id.endsWith(`_${id}`));
        if (zone) {
          const z = rx.zones[zone];
          if (service === "turn_on") {
            if (z.refuses) throw new Error("The receiver refused to switch this zone on. Some models cannot power this zone from the network.");
            z.power = "on";
          } else if (service === "turn_off") z.power = "off";
          else if (service === "select_source") {
            const names = { Source: "80" };
            z.source = names[data.source] ?? spec.inputs.find(([c]) => inputName(c) === data.source)?.[0] ?? z.source;
          } else if (service === "volume_up") z.raw = Math.min(80, z.raw + 1);
          else if (service === "volume_down") z.raw = Math.max(0, z.raw - 1);
          else if (service === "volume_mute") z.muted = data.is_volume_muted;
          break;
        }
        mainPlayerCall(service, data);
        break;
      }
      case "media_player.select_sound_mode": {
        await new Promise((resolve) => setTimeout(resolve, hass.modeDelay));
        const code = modeCodes().find((c) => modeName(c) === data.sound_mode);
        if (code) rx.mode = code;
        break;
      }
      case "select.select_option": {
        if (data.option === "high" && data.entity_id.endsWith("late_night") && ["pcm", "none"].includes(rx.signal)) {
          throw new Error("Late night High is not available with this signal");
        }
        const name = data.entity_id.split("onkyo_tx_rz50_")[1];
        if (name === "dirac_live") rx.dirac = data.option; else rx.selects[name] = data.option;
        break;
      }
      case "number.set_value": rx.numbers[data.entity_id.split("onkyo_tx_rz50_")[1]] = data.value; break;
      case "switch.turn_on": rx.switches[data.entity_id.split("onkyo_tx_rz50_")[1]] = true; break;
      case "switch.turn_off": rx.switches[data.entity_id.split("onkyo_tx_rz50_")[1]] = false; break;
      case "remote.send_command": rx.keys.push(...data.command); break;
      default:
    }
    commit();
  };

  hass.callWS = async (message) => {
    wsCalls.push(message);
    if (hass.failNext) {
      const text = hass.failNext;
      hass.failNext = null;
      throw Object.assign(new Error(text), { code: "name_in_use" });
    }
    if (message.type === "onkyo_eiscp/card_info") return info();
    if (message.type === "onkyo_eiscp/set_names") {
      const target = message.kind === "inputs" ? rx.inputNames : rx.modeNames;
      for (const key of Object.keys(target)) delete target[key];
      for (const [code, value] of Object.entries(message.names)) {
        if (value.name || value.hidden) target[code] = { name: value.name, hidden: value.hidden };
      }
      if (message.kind === "inputs" && message.order) rx.order = message.order;
      commit();
      return null;
    }
    throw new Error(`unexpected websocket message ${message.type}`);
  };

  hass.formatEntityState = (stateObj, value) =>
    value !== undefined ? (PRETTY[value] ?? value.replaceAll("_", " ").replace(/^./, (c) => c.toUpperCase())) : (LABELS[stateObj.state] ?? stateObj.state);

  /** Change the receiver from a test, then tell the card. */
  hass.set = (changes) => {
    Object.assign(rx, changes);
    if ("signal" in changes && !("mode" in changes)) rx.mode = SIGNALS[rx.signal].mode;
    commit();
  };

  build();
  return hass;
}
