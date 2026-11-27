// The rename sheet: rename, hide and (inputs) reorder, for the card's Edit button and the
// sidebar page (DESIGN.md "Rename sheet"). A native <dialog> opened with showModal(), so it
// escapes the card's container; a bottom sheet on a phone, a dialog on a tablet.

// The version of this file's URL goes on its imports, so a release reaches the browser.
const VERSION = new URL(import.meta.url).search;
const { STYLE } = await import(new URL(`./styles.js${VERSION}`, import.meta.url).href);
const { WS_CARD_INFO, WS_SET_NAMES, esc, icon } = await import(new URL(`./shared.js${VERSION}`, import.meta.url).href);

const GROUPS = [
  ["stereo", "Stereo"],
  ["surround", "Surround"],
  ["thx", "THX"],
  ["dsp", "Sound fields"],
  ["other", "Other"],
];
const WIDE_PX = 600;

/**
 * Open the sheet. `host` is the shadow root (or element) the dialog is added to; `kind` is
 * `inputs` or `modes`. Calls `onSaved` after a successful save.
 */
export async function openRenameSheet({ hass, deviceId, host, kind, currentInput = "", currentMode = "", toast, onSaved }) {
  let info;
  try {
    info = await hass.callWS({ type: WS_CARD_INFO, device_id: deviceId });
  } catch (error) {
    toast(error?.message || "Cannot read the receiver's names");
    return;
  }
  const isInputs = kind === "inputs";
  const rows = (isInputs ? info.inputs : info.listening_modes).map((item) => ({ ...item }));
  const current = isInputs ? currentInput : currentMode;

  const dialog = document.createElement("dialog");
  dialog.className = `sheet dlg-root${window.innerWidth >= WIDE_PX ? " wide" : ""}`;
  if (!(host instanceof ShadowRoot)) {
    // Outside a shadow root nothing has the card's styles yet.
    const style = document.createElement("style");
    style.textContent = STYLE;
    dialog.append(style);
  }
  host.append(dialog);

  const shown = (row) => (row.custom.trim() || row.name).trim();
  const rowHtml = (row) => `<div class="rrow ${row.hidden ? "hid" : ""}" data-c="${esc(row.code)}">
      ${isInputs ? `<span class="hnd" aria-label="Drag to reorder" role="img">${icon("drag", 22)}</span>` : ""}
      <div class="rf"><input value="${esc(row.custom)}" placeholder="${esc(row.name)}" aria-label="Name for ${esc(row.name)}" data-c="${esc(row.code)}">
      ${row.code === current ? `<div class="cur">Current ${isInputs ? "input" : "mode"}, always shown</div>` : ""}<div class="err" hidden></div></div>
      <button class="rshow pr" role="switch" aria-checked="${!row.hidden}" data-c="${esc(row.code)}"><span class="sw"></span>${row.hidden ? "Hidden" : "Shown"}</button></div>`;
  const body = isInputs
    ? rows.map(rowHtml).join("")
    : GROUPS.map(([group, title]) => [title, rows.filter((row) => row.group === group)])
        .filter(([, list]) => list.length)
        .map(([title, list]) => `<div class="rsec">${title}</div>${list.map(rowHtml).join("")}`)
        .join("");

  dialog.insertAdjacentHTML(
    "beforeend",
    `<div class="handle"></div><div class="dh"><h2 tabindex="-1">${isInputs ? "Rename inputs" : "Rename listening modes"}</h2>
      <button class="xbtn pr" data-x aria-label="Close">${icon("close")}</button></div>
    <p class="dsub">Rename or hide. Empty uses the receiver's name.${isInputs ? " Drag to change the order." : " Each mode shows only when the signal allows it."}</p>
    <div class="db">${body}</div>
    <div class="df"><button class="lbtn pr" data-reset>Reset all</button><span class="sp"></span>
      <button class="lbtn pr" data-x>Cancel</button><button class="fbtn pr" data-save>Save</button></div>`,
  );
  const byCode = (code) => rows.find((row) => row.code === code);
  const save = dialog.querySelector("[data-save]");

  const validate = () => {
    const counts = new Map();
    for (const row of rows) counts.set(shown(row).toLowerCase(), (counts.get(shown(row).toLowerCase()) ?? 0) + 1);
    let ok = true;
    for (const el of dialog.querySelectorAll(".rrow")) {
      const row = byCode(el.dataset.c);
      const duplicate = counts.get(shown(row).toLowerCase()) > 1;
      el.querySelector("input").classList.toggle("bad", duplicate);
      const err = el.querySelector(".err");
      err.hidden = !duplicate;
      err.textContent = duplicate ? "Another entry has this name" : "";
      if (duplicate) ok = false;
    }
    save.disabled = !ok;
  };

  const close = () => {
    dialog.close();
    dialog.remove();
  };

  dialog.addEventListener("input", (event) => {
    const code = event.target.dataset?.c;
    if (!code) return;
    byCode(code).custom = event.target.value;
    validate();
  });
  dialog.addEventListener("click", async (event) => {
    if (event.target === dialog) return close();
    const button = event.target.closest("button");
    if (!button) return;
    if (button.hasAttribute("data-x")) return close();
    if (button.hasAttribute("data-reset")) {
      for (const row of rows) Object.assign(row, { custom: "", hidden: false });
      for (const input of dialog.querySelectorAll("input")) input.value = "";
      for (const el of dialog.querySelectorAll(".rshow")) setShown(el, true);
      validate();
      return;
    }
    if (button.classList.contains("rshow")) {
      const row = byCode(button.dataset.c);
      row.hidden = !row.hidden;
      setShown(button, !row.hidden);
      return;
    }
    if (button.hasAttribute("data-save")) {
      const names = Object.fromEntries(rows.map((row) => [row.code, { name: row.custom.trim(), hidden: row.hidden }]));
      const message = { type: WS_SET_NAMES, device_id: deviceId, kind, names };
      if (isInputs) message.order = [...dialog.querySelectorAll(".rrow")].map((el) => el.dataset.c);
      save.disabled = true;
      try {
        await hass.callWS(message);
      } catch (error) {
        save.disabled = false;
        toast(error?.message || "The names were not saved");
        return;
      }
      close();
      toast(isInputs ? "Inputs saved" : "Listening modes saved");
      onSaved?.();
    }
  });
  dialog.addEventListener("cancel", () => dialog.remove());

  if (isInputs) bindDrag(dialog);
  validate();
  dialog.showModal();
}

function setShown(button, isShown) {
  button.setAttribute("aria-checked", String(isShown));
  button.lastChild.textContent = isShown ? "Shown" : "Hidden";
  button.closest(".rrow").classList.toggle("hid", !isShown);
}

/** Drag a row by its handle; works with mouse and touch (pointer events). */
function bindDrag(dialog) {
  const EDGE = 48;
  const SPEED = 14;
  dialog.addEventListener("pointerdown", (event) => {
    const handle = event.target.closest(".hnd");
    if (!handle) return;
    const row = handle.closest(".rrow");
    const body = dialog.querySelector(".db");
    let y = event.clientY;
    row.classList.add("drag");
    const place = () => {
      for (const other of dialog.querySelectorAll(".rrow")) {
        if (other === row) continue;
        const box = other.getBoundingClientRect();
        if (y >= box.top && y <= box.bottom) {
          other.parentNode.insertBefore(row, y < box.top + box.height / 2 ? other : other.nextSibling);
          break;
        }
      }
    };
    // The list scrolls inside the sheet: near its top or bottom edge the drag scrolls it.
    const scroller = setInterval(() => {
      const box = body.getBoundingClientRect();
      if (y < box.top + EDGE) body.scrollTop -= SPEED;
      else if (y > box.bottom - EDGE) body.scrollTop += SPEED;
      else return;
      place();
    }, 16);
    const move = (ev) => {
      y = ev.clientY;
      place();
    };
    // On the window, not on the handle: moving the row in the DOM releases a captured pointer.
    const end = () => {
      clearInterval(scroller);
      row.classList.remove("drag");
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", end);
      window.removeEventListener("pointercancel", end);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", end);
    window.addEventListener("pointercancel", end);
  });
}
