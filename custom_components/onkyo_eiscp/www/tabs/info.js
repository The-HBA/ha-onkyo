// The Playing tab: what the receiver plays (audio and video information) and the quick
// settings (late night, sleep timer, Music Optimizer), then a link to the sidebar page.

const LATE_NIGHT = ["off", "low", "high", "auto"];
const SLEEP_MINUTES = [0, 30, 60, 90];

const present = (state) => state && !["unavailable", "unknown"].includes(state.state);

export default {
  id: "info",
  label: "Playing",
  icon: "info",
  order: 40,

  available: () => true,

  render(ctx) {
    const { h } = ctx;
    return `${nowPlaying(ctx)}${quickSettings(ctx)}
      <button class="setlink pr wide" data-a="settings">${h.icon("cog", 22)}<span class="n">Receiver settings<small>Tone, levels, setup and names</small></span>${h.icon("right", 22)}</button>`;
  },

  action(ctx, action, value, key) {
    if (action === "late") {
      ctx.callOn("select.late_night", "select", "select_option", { option: value });
      return true;
    }
    if (action === "sleep") {
      ctx.callOn("number.sleep_timer", "number", "set_value", { value: Number(value) });
      return true;
    }
    if (action === "toggle" && key === "music_optimizer") {
      ctx.callOn("switch.music_optimizer", "switch", value === "on" ? "turn_on" : "turn_off");
      return true;
    }
    return false;
  },
};

/* ------------------------------------------------------------------ now playing */

/** "4K (3840x2160) 23 Hz" becomes "4K 23 Hz". */
const shortResolution = (text) => String(text ?? "").replace(/ \([^)]*\)/, "");

const join = (parts) => parts.filter(Boolean).join(" · ");

function audioColumn(ctx, on) {
  const { h, remote } = ctx;
  const attrs = remote.state("sensor.audio_input")?.attributes ?? {};
  const format = String(attrs.input_format ?? "");
  const out = attrs.output_channels ? `out ${attrs.output_channels}` : "";
  if (!on) return { big: "No signal", lines: ["Receiver in standby"] };
  if (!format) return { big: "No signal", lines: [join([attrs.input_port, out])] };
  const [main, ...rest] = format.split("/");
  return {
    big: main,
    lines: [join([rest.join("/"), attrs.sample_rate, attrs.input_channels]), join([attrs.input_port, out])],
  };
}

function videoColumn(ctx, on) {
  const { remote } = ctx;
  const attrs = remote.state("sensor.video_input")?.attributes ?? {};
  if (!on) return { big: "No video", lines: ["Receiver in standby"] };
  if (!attrs.input_resolution) return { big: "No video", lines: ["Audio-only input"] };
  const out = attrs.output_resolution ? `out ${shortResolution(attrs.output_resolution)}` : "";
  return {
    big: shortResolution(attrs.input_resolution),
    lines: [attrs.hdr, join([attrs.input_color_format, attrs.input_depth]), join([attrs.input_port, out])],
  };
}

function nowPlaying(ctx) {
  const { remote, h } = ctx;
  const hasAudio = Boolean(remote.entityId("sensor.audio_input"));
  const hasVideo = Boolean(remote.entityId("sensor.video_input"));
  if (!hasAudio && !hasVideo) return "";
  const on = remote.power === "on";
  const column = (title, data) =>
    `<div><div class="k">${title}</div><div class="big">${h.esc(data.big)}</div>${data.lines
      .filter(Boolean)
      .map((line) => `<div class="s">${h.esc(line)}</div>`)
      .join("")}</div>`;
  const columns = [hasAudio && column("Audio", audioColumn(ctx, on)), hasVideo && column("Video", videoColumn(ctx, on))].filter(Boolean);
  return `<div class="grp wide"><div class="gh"><span class="gt">Now playing</span><span class="gv">${on ? h.esc(remote.source) : ""}</span></div>
    <div class="np" style="--n:${columns.length}">${columns.join("")}</div></div>`;
}

/* ------------------------------------------------------------------ quick settings */

function quickSettings(ctx) {
  const { remote, h, hass } = ctx;
  const on = remote.power === "on";
  const parts = [];
  const notes = [];

  const late = remote.state("select.late_night");
  if (late) {
    if (on && !present(late)) {
      notes.push("Late night is not available with this signal");
    } else {
      const options = (late.attributes?.options ?? LATE_NIGHT).map((value) => ({
        value,
        label: h.optionLabel(hass, late, value),
        selected: present(late) && late.state === value,
      }));
      parts.push(`<div class="lbl">Late night</div>${h.segmented(options, { action: "late", cols: Math.min(4, options.length) })}`);
    }
  }

  const sleep = remote.state("number.sleep_timer");
  if (sleep) {
    const max = Number(sleep.attributes?.max ?? 90);
    const options = SLEEP_MINUTES.filter((minutes) => minutes <= max).map((minutes) => ({
      value: String(minutes),
      label: minutes ? `${minutes} min` : "Off",
      selected: present(sleep) && Number(sleep.state) === minutes,
    }));
    if (options.length > 1) parts.push(`<div class="lbl">Sleep timer</div>${h.segmented(options, { action: "sleep", cols: options.length })}`);
  }

  const optimizer = remote.state("switch.music_optimizer");
  if (optimizer) {
    if (on && !present(optimizer)) {
      notes.push("Music Optimizer works in Stereo only");
    } else {
      const checked = present(optimizer) && optimizer.state === "on";
      parts.push(`<button class="tgl pr" role="switch" aria-checked="${checked}" data-a="toggle" data-k="music_optimizer" data-v="${checked ? "off" : "on"}">
        <span class="n">Music Optimizer<small>Improves compressed music</small></span><span class="sw"></span></button>`);
    }
  }

  if (parts.length === 0 && notes.length === 0) return "";
  const note = notes.length ? `<div class="qnote">${h.icon("alertO", 18)}<span>${notes.map(h.esc).join(". ")}</span></div>` : "";
  return `<div class="grp ctl wide"><div class="gh"><span class="gt">Quick settings</span></div>${parts.join("")}${note}</div>`;
}
