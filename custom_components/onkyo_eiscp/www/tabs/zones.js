// The Zones tab (only on models with zone 2 or zone 3): one group per zone with a power
// switch row, the source grid while the zone is on and the volume while the zone reports one.

const ZONES = [
  ["zone2", "Zone 2"],
  ["zone3", "Zone 3"],
];
// Source code 80 is the receiver's "follow the main zone" input; its name is not shown as is.
const FOLLOWS_MAIN = "80";

const key = (zone) => `media_player.${zone}`;
const usable = (state) => Boolean(state) && !["unavailable", "unknown"].includes(state.state);
const present = (ctx) => ZONES.filter(([zone]) => ctx.remote.entityId(key(zone)));
const sourceLabel = (code, name) => (code === FOLLOWS_MAIN ? "Same as main" : name);

export default {
  id: "zones",
  label: "Zones",
  icon: "grid",
  order: 50,

  available: (ctx) => present(ctx).length > 0,

  render(ctx) {
    return `<div class="col">${present(ctx)
      .map(([zone, label]) => zoneGroup(ctx, zone, label))
      .join("")}</div>`;
  },

  action(ctx, action, value, zone) {
    const { remote, ui } = ctx;
    if (!zone || !remote.entityId(key(zone))) return false;
    if (action === "zpower") {
      const turnOn = value === "on";
      ui.zoneNote = { ...ui.zoneNote };
      delete ui.zoneNote[zone];
      const label = ZONES.find(([id]) => id === zone)?.[1] ?? zone;
      call(ctx, zone, turnOn ? "turn_on" : "turn_off").then((ok) => {
        if (!ok && turnOn) {
          ui.zoneNote = { ...ui.zoneNote, [zone]: `The receiver refused to switch ${label.toLowerCase()} on` };
          ctx.refresh();
        }
      });
      return true;
    }
    if (action === "zsource") {
      call(ctx, zone, "select_source", { source: value });
      return true;
    }
    if (action === "zvol") {
      call(ctx, zone, Number(value) > 0 ? "volume_up" : "volume_down");
      return true;
    }
    if (action === "zmute") {
      const muted = remote.state(key(zone))?.attributes?.is_volume_muted === true;
      call(ctx, zone, "volume_mute", { is_volume_muted: !muted });
      return true;
    }
    return false;
  },
};

/** Service call on a zone player; resolves true when it worked, false (and a toast) when not. */
async function call(ctx, zone, service, data = {}) {
  try {
    await ctx.hass.callService("media_player", service, { entity_id: ctx.remote.entityId(key(zone)), ...data });
    return true;
  } catch (error) {
    ctx.toast(error?.message || String(error));
    return false;
  }
}

function zoneGroup(ctx, zone, label) {
  const { remote, h, ui } = ctx;
  const player = remote.state(key(zone));
  const attrs = player?.attributes ?? {};
  const known = usable(player);
  const on = player?.state === "on";
  const source = on && attrs.source ? sourceLabel(attrs.source_code, attrs.source) : "";
  const sub = !known ? "Unavailable" : on ? (source ? `On, ${source}` : "On") : "Off";
  const head = `<button class="zhead pr" role="switch" aria-checked="${on}" data-a="zpower" data-k="${zone}" data-v="${on ? "off" : "on"}">
      <span class="n"><b>${label}</b><small>${h.esc(sub)}</small></span><span class="sw"></span></button>`;
  const parts = [head];

  if (on) {
    const codes = attrs.source_codes ?? [];
    const options = (attrs.source_list ?? []).map((name, index) => ({
      value: name,
      label: sourceLabel(codes[index], name),
      selected: name === attrs.source,
    }));
    if (options.length) parts.push(h.segmented(options, { action: "zsource", key: zone, cols: 3, dense: true, extra: "zs" }));
    parts.push(attrs.volume_level === undefined || attrs.volume_level === null ? h.qnote(`Volume is fixed on this receiver's ${label.toLowerCase()} output`) : volumeRow(ctx, zone, player));
  }
  const note = ui.zoneNote?.[zone];
  if (note && !on) parts.push(h.qnote(note));
  const style = known ? "" : ' style="opacity:.35;pointer-events:none"';
  return `<div class="grp"${style}>${parts.join("")}</div>`;
}

function volumeRow(ctx, zone, player) {
  const { h, ui } = ctx;
  const volume = readZoneVolume(player);
  const muted = player.attributes.is_volume_muted === true;
  const texts = h.volumeTexts(volume, ui.volumeUnit);
  const read = muted ? `Muted<small>${h.esc(texts.main)}</small>` : `${h.esc(texts.main)}<small>${h.esc(texts.small)}</small>`;
  return `<div class="srow"><button class="ibtn pr ${muted ? "sel" : ""}" data-a="zmute" data-k="${zone}" aria-label="Mute" aria-pressed="${muted}">${h.icon(muted ? "volOff" : "volHigh")}</button>
    <button class="ibtn pr" data-a="zvol" data-k="${zone}" data-v="-1" data-rep aria-label="Volume down">${h.icon("minus")}</button>
    <div class="vread zv">${read}</div>
    <button class="ibtn pr" data-a="zvol" data-k="${zone}" data-v="1" data-rep aria-label="Volume up">${h.icon("plus")}</button></div>`;
}

function readZoneVolume(player) {
  const attrs = player.attributes;
  const level = Number(attrs.volume_level);
  const db = attrs.volume_db !== undefined && attrs.volume_db !== null ? Number(attrs.volume_db) : null;
  return { level, percent: Math.round(level * 100), db, hasDb: db !== null && Number.isFinite(db), raw: null, max: null };
}
