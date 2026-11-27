// The Modes tab: the listening modes the current signal allows, in groups (DESIGN.md "Tabs").

const GROUPS = [
  ["stereo", "Stereo"],
  ["surround", "Surround"],
  ["thx", "THX"],
  ["dsp", "Sound fields"],
  ["other", "Other"],
];

export default {
  id: "modes",
  label: "Modes",
  icon: "note",
  order: 20,

  available: () => true,

  render(ctx) {
    const { remote, h, ui } = ctx;
    if (remote.power !== "on") return h.notice("Listening modes appear when the receiver is on.");
    const current = ui.pendingMode?.code ?? remote.modeCode;
    const modes = remote.modes;
    const signal = signalLabel(ctx);
    const sections = GROUPS.map(([group, title]) => [title, modes.filter((m) => remote.groupOf(m.code) === group)])
      .filter(([, list]) => list.length)
      .map(
        ([title, list]) => `<div class="lbl" style="margin:2px 0 -4px 2px">${title}</div>
        ${h.segmented(
          list.map((m) => ({
            value: m.code,
            html: modeLabel(h, m.name),
            selected: m.code === current,
            pending: ui.pendingMode?.code === m.code,
          })),
          { action: "mode", cols: 3, dense: true, extra: "m3" },
        )}`,
      )
      .join("");
    return `<div class="grp wide ctl" style="gap:8px"><div class="gh"><span class="gt">Listening modes</span>
      <span class="gv" style="flex:1">${signal ? `for ${h.esc(signal)}` : ""}</span>${h.editButton(ctx, "modes")}</div>${sections}</div>`;
  },

  action(ctx, action, value) {
    if (action !== "mode") return false;
    const { remote } = ctx;
    if (ctx.ui.pendingMode || value === remote.modeCode) return true;
    const mode = remote.modes.find((m) => m.code === value);
    if (!mode) return true;
    ctx.ui.pendingMode = { code: value, name: mode.name };
    ctx.refresh();
    ctx
      .callOn("media_player.main", "media_player", "select_sound_mode", { sound_mode: mode.name })
      .finally(() => {
        ctx.ui.pendingMode = null;
        ctx.refresh();
      });
    return true;
  },
};

/** "THX Cinema (Neural:X)" shows "(Neural:X)" as a small second line. */
function modeLabel(h, name) {
  const match = name.match(/^(.*) \((.*)\)$/);
  return match
    ? `<span class="t">${h.esc(match[1])}</span><small>${h.esc(match[2])}</small>`
    : `<span class="t">${h.esc(name)}</span>`;
}

function signalLabel(ctx) {
  const sensor = ctx.remote.state("sensor.audio_input");
  if (!sensor) return "";
  const format = String(sensor.attributes?.input_format ?? "");
  if (!format) return "no signal";
  if (/atmos/i.test(format)) return "Dolby Atmos";
  if (/^pcm$/i.test(format)) return "PCM stereo";
  return format.split("/")[0];
}
