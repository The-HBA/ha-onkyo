// The Remote tab: the on-screen menu keys of the receiver (the remote entity) and the volume.
// Arrows repeat while held (the shell's data-rep); the other keys send on release.

const KEYS = [
  ["exit", "back", "Back"],
  ["home", "home", "Home"],
  ["menu", "menu", "Menu"],
  ["quick", "dots", "Quick menu"],
  ["audio", "note", "Audio"],
  ["video", "monitor", "Video"],
];
const ARROWS = ["up", "down", "left", "right"];
const KNOWN = new Set([...ARROWS, "enter", ...KEYS.map(([key]) => key)]);

export default {
  id: "remote",
  label: "Remote",
  icon: "remote",
  order: 30,

  available: (ctx) => Boolean(ctx.remote.entityId("remote.remote")),

  render(ctx) {
    const { h, remote } = ctx;
    const on = remote.power === "on";
    const standby = on ? "" : h.notice(remote.power === "standby" ? "The receiver is in standby. Turn it on to use the keys." : "The receiver is not connected.");
    const arrows = ARROWS.map(
      (key) => `<button class="dk ${key} pr" data-a="key" data-v="${key}" data-rep aria-label="${key[0].toUpperCase()}${key.slice(1)}">${h.icon(key)}</button>`,
    ).join("");
    const keys = KEYS.map(
      ([key, icon, label]) => `<button class="key pr" data-a="key" data-v="${key}" aria-label="${label}">${h.icon(icon)}<span>${label}</span></button>`,
    ).join("");
    return `${standby}<div class="col"><div class="grp ctl"><div class="gh"><span class="gt">On-screen menu</span><span class="gv">On the TV or projector</span></div>
        <div class="dpad">${arrows}<button class="dk ok pr" data-a="key" data-v="enter" aria-label="Enter">Enter</button></div>
        <div class="keys">${keys}</div></div></div>
      <div class="col">${h.volumeGroup(ctx)}</div>`;
  },

  action(ctx, action, value) {
    if (action !== "key" || !KNOWN.has(value)) return false;
    ctx.callOn("remote.remote", "remote", "send_command", { command: [value] });
    return true;
  },
};
