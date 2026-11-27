// The Main tab: input, listening mode, Dirac Live and volume (DESIGN.md "Tabs").
// A tab module exports one object; the shell (onkyo-remote-card.js) calls render, action, after.

export default {
  id: "main",
  label: "Main",
  icon: "play",
  order: 10,

  available: () => true,

  render(ctx) {
    const { remote, h, ui } = ctx;
    const on = remote.power === "on";
    const standby = on
      ? ""
      : h.notice(
          remote.power === "standby"
            ? "The receiver is in standby. Turn it on to use the controls."
            : "The receiver is not connected.",
        );
    return `${standby}<div class="col">${inputGroup(ctx)}</div>
      <div class="col">${on ? modeRow(ctx) + diracGroup(ctx) : ""}${h.volumeGroup(ctx)}</div>`;
  },

  action(ctx, action, value) {
    if (action === "input") {
      ctx.callOn("media_player.main", "media_player", "select_source", { source: value });
      return true;
    }
    if (action === "dirac") {
      ctx.callOn("select.dirac_slot", "select", "select_option", { option: value });
      return true;
    }
    return false;
  },

  /** Share the free height between the groups: gap 12 to 28 px, Volume stays at the bottom. */
  after(ctx, pane) {
    pane.style.removeProperty("--mgap");
    if (getComputedStyle(pane).display !== "flex") return;
    const items = [...pane.querySelectorAll(":scope > .notice, :scope > .col > .grp")];
    if (items.length < 2) return;
    const used = items.reduce((total, el) => total + el.getBoundingClientRect().height, 0);
    const free = pane.clientHeight - used - 12 * (items.length - 1);
    pane.style.setProperty("--mgap", `${Math.min(28, 12 + Math.max(0, free) / (items.length - 1))}px`);
  },
};

function inputGroup(ctx) {
  const { remote, h } = ctx;
  const current = remote.source;
  const options = remote.sources.map((name) => ({ value: name, label: name, selected: name === current }));
  return `<div class="grp ctl"><div class="gh"><span class="gt">Input</span>${h.editButton(ctx, "inputs")}</div>
    ${h.segmented(options, { action: "input", cols: 3, extra: "in3" })}</div>`;
}

function modeRow(ctx) {
  const { remote, h, ui } = ctx;
  const name = ui.pendingMode?.name ?? remote.mode;
  return `<div class="grp ctl tight"><button class="mrow pr" data-a="tab" data-v="modes">
      <div class="n"><small>Listening mode</small><b>${h.esc(name || "No mode")}</b></div>
      <span class="gv">${remote.modes.length} modes</span>${h.icon("right", 22)}</button></div>`;
}

function diracGroup(ctx) {
  const { remote, h, hass } = ctx;
  const select = remote.state("select.dirac_slot");
  if (!select || ["unavailable", "unknown"].includes(select.state)) return "";
  const options = (select.attributes.options ?? []).map((value) => ({
    value,
    label: h.optionLabel(hass, select, value),
    selected: value === select.state,
  }));
  if (options.length === 0) return "";
  return `<div class="grp ctl"><div class="gh"><span class="gt">Dirac Live</span><span class="gv">Room correction</span></div>
    ${h.segmented(options, { action: "dirac", cols: options.length })}</div>`;
}
