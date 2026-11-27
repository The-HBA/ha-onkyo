// Browser tests of the Onkyo remote card (custom:onkyo-remote-card) with a fake hass.
// Run from this folder: npm ci, then npm test.

import assert from "node:assert/strict";
import { after, before, describe, test } from "node:test";

import { chromium } from "playwright";

import { fitProblems } from "./fit.mjs";
import { openCard, PHONE, SMALL_PHONE, startServer, TABLET } from "./harness.mjs";

let browser;
let server;

before(async () => {
  server = await startServer();
  browser = await chromium.launch();
});

after(async () => {
  await browser?.close();
  await server?.close();
});

const open = (options) => openCard(browser, server.url, options);
const calls = (page) => page.evaluate(() => window.hass.calls);
const text = (page, selector) => page.locator(`onkyo-remote-card ${selector}`).first().innerText();

async function using(options, body) {
  const { page, errors } = await open(options);
  try {
    await body(page);
    assert.deepEqual(errors, []);
  } finally {
    await page.close();
  }
}

describe("header and tabs", () => {
  test("shows the receiver, its state and the tabs", () =>
    using({ power: "on" }, async (page) => {
      assert.equal(await text(page, ".hname"), "Onkyo TX-RZ50");
      assert.equal(await text(page, ".hsub"), "On · Streaming · Dolby Atmos");
      const tabs = page.locator("onkyo-remote-card [role=tab]");
      assert.deepEqual((await tabs.allInnerTexts()).slice(0, 2), ["Main", "Modes"]);
      assert.equal(await tabs.first().getAttribute("aria-selected"), "true");
    }));

  test("a tab click shows its pane and the arrow keys move between tabs", () =>
    using({ power: "on" }, async (page) => {
      await page.locator("onkyo-remote-card [role=tab]", { hasText: "Modes" }).click();
      assert.equal(await page.locator("onkyo-remote-card .p-modes").count(), 1);
      await page.keyboard.press("ArrowLeft");
      assert.equal(await page.locator("onkyo-remote-card .p-main").count(), 1);
    }));

  test("the power button switches the receiver off and on", () =>
    using({ power: "on" }, async (page) => {
      await page.locator("onkyo-remote-card .power").click();
      assert.equal(await text(page, ".hsub"), "Standby");
      await page.locator("onkyo-remote-card .power").click();
      assert.match(await text(page, ".hsub"), /^On/);
      const services = (await calls(page)).map((c) => c.service);
      assert.deepEqual(services, ["turn_off", "turn_on"]);
    }));

  test("no receiver: one clear line", async () => {
    const page = await browser.newPage({ viewport: PHONE });
    try {
      await page.goto(`${server.url}/`);
      await page.waitForFunction(() => window.cardReady);
      await page.evaluate(() => {
        const card = document.createElement("onkyo-remote-card");
        card.setConfig({ type: "custom:onkyo-remote-card" });
        card.hass = { states: {}, entities: {}, devices: {} };
        document.getElementById("view").replaceChildren(card);
      });
      assert.match(await page.locator("onkyo-remote-card .notice").innerText(), /No Onkyo receiver found/);
    } finally {
      await page.close();
    }
  });

  test("an unavailable receiver says so and disables the controls", () =>
    using({ power: "unavailable" }, async (page) => {
      assert.equal(await text(page, ".hsub"), "Unavailable");
      assert.match(await text(page, ".notice"), /not connected/);
      assert.equal(await page.locator("onkyo-remote-card .mrow").count(), 0);
    }));
});

describe("main tab", () => {
  test("lists every input by its clean name and selects one", () =>
    using({}, async (page) => {
      const inputs = await page.locator("onkyo-remote-card .in3 .opt").allInnerTexts();
      assert.equal(inputs.length, 13);
      assert.deepEqual(inputs.slice(0, 4), ["Movie", "PS5", "Wii U", "Streaming"]);
      assert.equal(await page.locator("onkyo-remote-card .in3 .opt.sel").innerText(), "Streaming");
      await page.locator("onkyo-remote-card .in3 .opt", { hasText: "PS5" }).click();
      assert.deepEqual(await calls(page), [
        { domain: "media_player", service: "select_source", data: { entity_id: "media_player.onkyo_tx_rz50_main", source: "PS5" } },
      ]);
      assert.equal(await page.locator("onkyo-remote-card .in3 .opt.sel").innerText(), "PS5");
      assert.match(await text(page, ".hsub"), /PS5/);
    }));

  test("a renamed and reordered list shows as the receiver reports it", () =>
    using({}, async (page) => {
      await page.evaluate(() => window.hass.set({ inputNames: { "02": { name: "Console" }, "01": { hidden: true } }, order: ["02"] }));
      const inputs = await page.locator("onkyo-remote-card .in3 .opt").allInnerTexts();
      assert.equal(inputs[0], "Console");
      assert.ok(!inputs.includes("Wii U"));
    }));

  test("the listening mode row shows the mode and opens the Modes tab", () =>
    using({}, async (page) => {
      assert.equal(await text(page, ".mrow b"), "Dolby Atmos");
      assert.equal(await text(page, ".mrow .gv"), "15 modes");
      await page.locator("onkyo-remote-card .mrow").click();
      assert.equal(await page.locator("onkyo-remote-card .p-modes").count(), 1);
    }));

  test("Dirac Live offers Off and the filled slots and selects one", () =>
    using({}, async (page) => {
      const options = await page.locator("onkyo-remote-card .grp:has(.gt:text('Dirac Live')) .opt").allInnerTexts();
      assert.deepEqual(options, ["Off", "Slot 1", "Slot 2", "Slot 3"]);
      await page.locator("onkyo-remote-card .grp:has(.gt:text('Dirac Live')) .opt", { hasText: "Slot 1" }).click();
      const [call] = await calls(page);
      assert.equal(call.service, "select_option");
      assert.equal(call.data.option, "slot_1");
    }));

  test("a model without Dirac shows no Dirac group (RULES.md 4)", () =>
    using({ model: "small" }, async (page) => {
      assert.equal(await page.locator("onkyo-remote-card .gt", { hasText: "Dirac Live" }).count(), 0);
      assert.equal(await text(page, ".hname"), "Onkyo TX-SR494");
    }));

  test("standby: a notice, no mode row, no Dirac, controls not clickable", () =>
    using({ power: "standby" }, async (page) => {
      assert.match(await text(page, ".notice"), /standby/);
      assert.equal(await page.locator("onkyo-remote-card .mrow").count(), 0);
      assert.equal(await page.locator("onkyo-remote-card .gt", { hasText: "Dirac Live" }).count(), 0);
      assert.equal(await page.locator("onkyo-remote-card .grp.ctl").first().evaluate((el) => getComputedStyle(el).pointerEvents), "none");
    }));

  test("a failed service call shows Home Assistant's toast", () =>
    using({}, async (page) => {
      await page.evaluate(() => { window.hass.failNext = "Not available"; });
      await page.locator("onkyo-remote-card .in3 .opt", { hasText: "CD" }).click();
      await page.waitForFunction(() => window.toasts.length > 0);
      assert.deepEqual(await page.evaluate(() => window.toasts), ["Not available"]);
    }));
});

describe("volume (RULES.md 16)", () => {
  test("shows dB large and percent small, and a tap switches them for this browser", () =>
    using({}, async (page) => {
      assert.equal(await text(page, ".vread"), "−30.0 dB\n63 %");
      await page.locator("onkyo-remote-card .vread").click();
      assert.equal(await text(page, ".vread"), "63 %\n−30.0 dB");
      assert.equal(await page.evaluate(() => localStorage.getItem("onkyo_eiscp.volume_unit")), "percent");
    }));

  test("the card option volume_unit sets the default", () =>
    using({ config: { volume_unit: "percent" } }, async (page) => {
      assert.equal(await text(page, ".vread"), "63 %\n−30.0 dB");
    }));

  test("a receiver without a dB scale shows its own units and percent", () =>
    using({ model: "small" }, async (page) => {
      assert.equal(await text(page, ".vread"), "52 / 80\n65 %");
    }));

  test("plus and minus step one receiver unit through volume_set", () =>
    using({}, async (page) => {
      await page.locator("onkyo-remote-card [aria-label='Volume up']").click();
      await page.locator("onkyo-remote-card [aria-label='Volume down']").click();
      const levels = (await calls(page)).filter((c) => c.service === "volume_set").map((c) => c.data.volume_level);
      assert.equal(levels.length, 2);
      assert.ok(Math.abs(levels[0] - 105 / 164) < 1e-9);
      assert.ok(Math.abs(levels[1] - 104 / 164) < 1e-9);
      assert.equal(await text(page, ".vread"), "−30.0 dB\n63 %");
    }));

  test("holding plus repeats", () =>
    using({}, async (page) => {
      const plus = page.locator("onkyo-remote-card [aria-label='Volume up']");
      const box = await plus.boundingBox();
      await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
      await page.mouse.down();
      await page.waitForTimeout(900);
      await page.mouse.up();
      const levels = (await calls(page)).filter((c) => c.service === "volume_set");
      assert.ok(levels.length >= 3, `only ${levels.length} calls`);
      await page.waitForTimeout(200);
      const settled = (await calls(page)).length;
      await page.waitForTimeout(400);
      assert.equal((await calls(page)).length, settled, "calls go on after release");
    }));

  test("the slider sets the volume where it is pressed", () =>
    using({}, async (page) => {
      const slider = page.locator("onkyo-remote-card [data-slider]");
      const box = await slider.boundingBox();
      await page.mouse.click(box.x + box.width * 0.5, box.y + box.height / 2);
      const set = (await calls(page)).filter((c) => c.service === "volume_set");
      assert.ok(set.length >= 1);
      const level = set.at(-1).data.volume_level;
      assert.ok(level > 0.4 && level < 0.6, `level ${level}`);
    }));

  test("mute toggles and the readout says Muted", () =>
    using({}, async (page) => {
      await page.locator("onkyo-remote-card [aria-label='Mute']").click();
      assert.equal(await text(page, ".vread"), "Muted\n−30.0 dB");
      assert.deepEqual((await calls(page)).map((c) => [c.service, c.data.is_volume_muted]), [["volume_mute", true]]);
    }));
});

describe("modes tab", () => {
  const openModes = async (page) => page.locator("onkyo-remote-card [role=tab]", { hasText: "Modes" }).click();

  test("groups the modes the signal allows", () =>
    using({ signal: "atmos" }, async (page) => {
      await openModes(page);
      const titles = await page.locator("onkyo-remote-card .p-modes .lbl").allInnerTexts();
      assert.deepEqual(titles, ["Stereo", "Surround", "Sound fields"]);
      assert.equal(await page.locator("onkyo-remote-card .p-modes .opt").count(), 15);
      assert.equal(await page.locator("onkyo-remote-card .p-modes .opt.sel").innerText(), "Dolby Atmos");
      assert.match(await text(page, ".p-modes .gv"), /Dolby Atmos/);
    }));

  test("PCM adds the THX group; a THX name shows its upmixer as a second line", () =>
    using({ signal: "pcm" }, async (page) => {
      await openModes(page);
      const titles = await page.locator("onkyo-remote-card .p-modes .lbl").allInnerTexts();
      assert.deepEqual(titles, ["Stereo", "Surround", "THX", "Sound fields"]);
      const thx = page.locator("onkyo-remote-card .p-modes .opt", { hasText: "THX Cinema" }).first();
      assert.equal(await thx.locator("small").innerText(), "Dolby Surround");
    }));

  test("a tapped mode pulses until the receiver confirms, then is selected", () =>
    using({ signal: "pcm" }, async (page) => {
      await openModes(page);
      await page.locator("onkyo-remote-card .p-modes .opt", { hasText: "Orchestra" }).click();
      assert.equal(await page.locator("onkyo-remote-card .p-modes .opt.pend").innerText(), "Orchestra");
      assert.equal(await page.locator("onkyo-remote-card ha-card.sending").count(), 1);
      await page.waitForSelector("onkyo-remote-card .p-modes .opt.sel:has-text('Orchestra')");
      assert.equal(await page.locator("onkyo-remote-card .p-modes .opt.pend").count(), 0);
      assert.equal(await page.locator("onkyo-remote-card ha-card.sending").count(), 0);
      const [call] = await calls(page);
      assert.equal(call.service, "select_sound_mode");
      assert.equal(call.data.sound_mode, "Orchestra");
    }));

  test("standby says when the modes appear", () =>
    using({ power: "standby" }, async (page) => {
      await openModes(page);
      assert.match(await text(page, ".p-modes .notice"), /appear when the receiver is on/);
    }));
});

describe("edit names (RULES.md 14)", () => {
  test("only an administrator sees Edit", async () => {
    await using({ admin: false }, async (page) => {
      assert.equal(await page.locator("onkyo-remote-card .tbtn").count(), 0);
    });
    await using({ admin: true }, async (page) => {
      assert.equal(await page.locator("onkyo-remote-card .tbtn").count(), 1);
    });
  });

  test("rename an input, hide another, drag one to the top, save", () =>
    using({}, async (page) => {
      await page.locator("onkyo-remote-card .tbtn").click();
      const sheet = page.locator("onkyo-remote-card dialog.sheet");
      await sheet.waitFor();
      assert.equal(await sheet.locator("h2").innerText(), "Rename inputs");
      assert.equal(await sheet.locator(".rrow").count(), 13);
      assert.match(await sheet.locator(".cur").innerText(), /Current input, always shown/);
      await sheet.locator("input[data-c='02']").fill("Console");
      await sheet.locator(".rshow[data-c='01']").click();
      // Drag Projector (last, below the fold) to the top: the list scrolls while the pointer is at its edge.
      await sheet.locator(".rrow[data-c='12']").scrollIntoViewIfNeeded();
      const handle = await sheet.locator(".rrow[data-c='12'] .hnd").boundingBox();
      const list = await sheet.locator(".db").boundingBox();
      await page.mouse.move(handle.x + handle.width / 2, handle.y + handle.height / 2);
      await page.mouse.down();
      await page.mouse.move(handle.x + 10, list.y + 10, { steps: 6 });
      await page.waitForTimeout(1500);
      await page.mouse.up();
      await sheet.locator("[data-save]").click();
      await page.waitForFunction(() => window.toasts.includes("Inputs saved"));
      const save = (await page.evaluate(() => window.hass.wsCalls)).find((c) => c.type === "onkyo_eiscp/set_names");
      assert.ok(save);
      assert.equal(save.kind, "inputs");
      assert.deepEqual(save.names["02"], { name: "Console", hidden: false });
      assert.deepEqual(save.names["01"], { name: "", hidden: true });
      assert.equal(save.order[0], "12");
      assert.equal(await page.locator("onkyo-remote-card dialog").count(), 0);
      const inputs = await page.locator("onkyo-remote-card .in3 .opt").allInnerTexts();
      assert.equal(inputs[0], "Projector");
      assert.ok(inputs.includes("Console") && !inputs.includes("Wii U"));
    }));

  test("two entries with one name disable Save", () =>
    using({}, async (page) => {
      await page.locator("onkyo-remote-card .tbtn").click();
      const sheet = page.locator("onkyo-remote-card dialog.sheet");
      await sheet.locator("input[data-c='02']").fill("movie");
      assert.equal(await sheet.locator("[data-save]").isDisabled(), true);
      assert.equal(await sheet.locator(".err:visible").count(), 2);
      await sheet.locator("input[data-c='02']").fill("");
      assert.equal(await sheet.locator("[data-save]").isDisabled(), false);
    }));

  test("the Modes tab edits the listening modes in their sections", () =>
    using({ signal: "pcm" }, async (page) => {
      await page.locator("onkyo-remote-card [role=tab]", { hasText: "Modes" }).click();
      await page.locator("onkyo-remote-card .tbtn").click();
      const sheet = page.locator("onkyo-remote-card dialog.sheet");
      assert.equal(await sheet.locator("h2").innerText(), "Rename listening modes");
      assert.deepEqual(await sheet.locator(".rsec").allInnerTexts(), ["Stereo", "Surround", "THX", "Sound fields"]);
      assert.equal(await sheet.locator(".hnd").count(), 0);
      await sheet.locator(".rshow[data-c='08']").click();
      await sheet.locator("[data-save]").click();
      await page.waitForFunction(() => window.toasts.includes("Listening modes saved"));
      assert.equal(await page.locator("onkyo-remote-card .p-modes .opt", { hasText: "Orchestra" }).count(), 0);
    }));

  test("Reset all clears names and hidden flags; Cancel closes without saving", () =>
    using({}, async (page) => {
      await page.evaluate(() => window.hass.set({ inputNames: { "02": { name: "Console" } } }));
      await page.locator("onkyo-remote-card .tbtn").click();
      const sheet = page.locator("onkyo-remote-card dialog.sheet");
      assert.equal(await sheet.locator("input[data-c='02']").inputValue(), "Console");
      await sheet.locator("[data-reset]").click();
      assert.equal(await sheet.locator("input[data-c='02']").inputValue(), "");
      await sheet.locator("[data-x]").first().click();
      assert.equal(await page.locator("onkyo-remote-card dialog").count(), 0);
      const saves = (await page.evaluate(() => window.hass.wsCalls)).filter((c) => c.type === "onkyo_eiscp/set_names");
      assert.equal(saves.length, 0);
    }));

  test("a refused save shows the reason and keeps the sheet open", () =>
    using({}, async (page) => {
      await page.locator("onkyo-remote-card .tbtn").click();
      const sheet = page.locator("onkyo-remote-card dialog.sheet");
      await sheet.locator("input[data-c='02']").fill("Console");
      await page.evaluate(() => { window.hass.failNext = "Another entry is already named"; });
      await sheet.locator("[data-save]").click();
      await page.waitForFunction(() => window.toasts.length > 0);
      assert.equal(await sheet.isVisible(), true);
      assert.equal(await sheet.locator("[data-save]").isDisabled(), false);
    }));
});

describe("editor", () => {
  test("offers the receiver and the volume unit", async () => {
    const { page, errors } = await open({});
    try {
      const form = await page.evaluate(async () => {
        const element = await window.card.constructor.getConfigElement();
        document.body.append(element);
        element.setConfig({ type: "custom:onkyo-remote-card", device_id: "device_rz50" });
        const ha = element.querySelector("ha-form");
        const seen = [];
        element.addEventListener("config-changed", (event) => seen.push(event.detail.config));
        ha.dispatchEvent(new CustomEvent("value-changed", { detail: { value: { device_id: "device_rz50", volume_unit: "percent" } } }));
        return { schema: ha.schema.map((f) => f.name), integration: ha.schema[0].selector.device.integration, data: ha.data, seen, label: ha.computeLabel(ha.schema[1]) };
      });
      assert.deepEqual(form.schema, ["device_id", "volume_unit"]);
      assert.equal(form.integration, "onkyo_eiscp");
      assert.equal(form.data.volume_unit, "db");
      assert.deepEqual(form.seen, [{ type: "custom:onkyo-remote-card", device_id: "device_rz50", volume_unit: "percent" }]);
      assert.equal(form.label, "Main volume unit");
      assert.deepEqual(errors, []);
    } finally {
      await page.close();
    }
  });

  test("an invalid volume_unit is refused", async () => {
    const { page } = await open({});
    try {
      const message = await page.evaluate(() => {
        try {
          window.card.setConfig({ type: "custom:onkyo-remote-card", volume_unit: "bels" });
          return null;
        } catch (error) {
          return error.message;
        }
      });
      assert.match(message, /volume_unit/);
    } finally {
      await page.close();
    }
  });
});

describe("fit (DESIGN.md Review)", () => {
  const tabs = ["Main", "Modes", "Remote", "Playing", "Zones"];
  for (const viewport of [PHONE, SMALL_PHONE]) {
    for (const model of ["rz50", "small"]) {
      for (const signal of ["pcm", "atmos", "dtsx", "none"]) {
        for (const power of ["on", "standby"]) {
          test(`${viewport.width}px ${model} ${signal} ${power}: every tab fits`, async () => {
            const { page, errors } = await open({ viewport, model, signal, power, theme: "dark" });
            try {
              for (const label of tabs) {
                const tab = page.locator("onkyo-remote-card [role=tab]", { hasText: label });
                if (label === "Zones" && model === "small") {
                  assert.equal(await tab.count(), 0);
                  continue;
                }
                await tab.click();
                assert.deepEqual(await fitProblems(page), [], `${label}`);
              }
              assert.deepEqual(errors, []);
            } finally {
              await page.close();
            }
          });
        }
      }
    }
  }

  test("the rename sheet fits a phone", async () => {
    const { page } = await open({});
    try {
      await page.locator("onkyo-remote-card .tbtn").click();
      const box = await page.locator("onkyo-remote-card dialog.sheet").boundingBox();
      assert.ok(box.x >= 0 && box.x + box.width <= PHONE.width + 1);
      assert.ok(box.y >= 0 && box.y + box.height <= PHONE.height + 1);
    } finally {
      await page.close();
    }
  });

  test("a tablet width puts Main in two columns", async () => {
    const { page } = await open({ viewport: TABLET, wide: true });
    try {
      const columns = await page.evaluate(() => getComputedStyle(window.card.shadowRoot.querySelector(".pane")).gridTemplateColumns.split(" ").length);
      assert.equal(columns, 2);
      assert.deepEqual(await fitProblems(page), []);
    } finally {
      await page.close();
    }
  });
});

describe("long names and keys", () => {
  test("a long unbroken name keeps Main and Modes inside the card", async () => {
    for (const viewport of [PHONE, SMALL_PHONE]) {
      const { page } = await open({ viewport, signal: "pcm" });
      try {
        await page.evaluate(() => window.hass.set({ inputNames: { "02": { name: "ABCDEFGHIJKLMNOPQRSTUVWX" } }, modeNames: { "08": { name: "ABCDEFGHIJKLMNOPQRSTUVWX" } } }));
        assert.deepEqual(await fitProblems(page), []);
        await page.locator("onkyo-remote-card [role=tab]", { hasText: "Modes" }).click();
        assert.deepEqual(await fitProblems(page), []);
      } finally {
        await page.close();
      }
    }
  });

  test("Home and End work on the tab row and the slider", () =>
    using({}, async (page) => {
      await page.locator("onkyo-remote-card [role=tab]").first().focus();
      await page.keyboard.press("End");
      assert.equal(await page.locator("onkyo-remote-card .p-zones").count(), 1);
      await page.keyboard.press("Home");
      assert.equal(await page.locator("onkyo-remote-card .p-main").count(), 1);
      await page.locator("onkyo-remote-card [data-slider]").focus();
      await page.keyboard.press("End");
      await page.keyboard.press("Home");
      const levels = (await calls(page)).filter((c) => c.service === "volume_set").map((c) => c.data.volume_level);
      assert.deepEqual(levels, [1, 0]);
    }));

  test("a second tap on a pending mode sends nothing", () =>
    using({ signal: "pcm" }, async (page) => {
      await page.locator("onkyo-remote-card [role=tab]", { hasText: "Modes" }).click();
      const mode = page.locator("onkyo-remote-card .p-modes .opt", { hasText: "Orchestra" });
      await mode.click();
      await mode.click();
      await page.waitForSelector("onkyo-remote-card .p-modes .opt.sel:has-text('Orchestra')");
      assert.equal((await calls(page)).filter((c) => c.service === "select_sound_mode").length, 1);
    }));
});
