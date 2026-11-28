// Browser tests of the sidebar page (onkyo-panel) with a fake hass.

import assert from "node:assert/strict";
import { after, before, describe, test } from "node:test";

import { chromium } from "playwright";

import { DESKTOP, openPanel, PHONE, startServer } from "./harness.mjs";

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

async function using(options, body) {
  const { page, errors } = await openPanel(browser, server.url, options);
  try {
    await body(page);
    assert.deepEqual(errors, []);
  } finally {
    await page.close();
  }
}

const titles = (page) => page.locator("onkyo-panel .right .rs .gt").allInnerTexts();
const leftTitles = (page) => page.locator("onkyo-panel .leftx .gt").allInnerTexts();
const calls = (page) => page.evaluate(() => window.hass.calls);

describe("sidebar page", () => {
  test("shows the card and the settings the model has", () =>
    using({}, async (page) => {
      assert.equal(await page.locator("onkyo-panel h1").innerText(), "Onkyo");
      assert.equal(await page.locator("onkyo-panel onkyo-remote-card .hname").innerText(), "Onkyo TX-RZ50");
      assert.deepEqual(await titles(page), ["Tone", "Levels", "Sound", "Setup"]);
      // Wide screen: names and receiver info sit under the card.
      assert.deepEqual(await leftTitles(page), ["Names", "Receiver"]);
    }));

  test("a smaller model shows only what it has (RULES.md 4)", () =>
    using({ model: "small" }, async (page) => {
      const gt = await titles(page);
      assert.ok(gt.includes("Tone") && gt.includes("Levels") && gt.includes("Setup"));
      assert.ok(!gt.includes("Sound"));
      assert.equal(await page.locator("onkyo-panel .right .step", { hasText: "Vocal enhancer" }).count(), 0);
    }));

  test("a stepper sets a number; one the receiver refuses reads Not available", () =>
    using({}, async (page) => {
      await page.locator("onkyo-panel [aria-label='Bass up']").click();
      assert.deepEqual((await calls(page))[0], {
        domain: "number",
        service: "set_value",
        data: { entity_id: "number.onkyo_tx_rz50_bass", value: -1 },
      });
      assert.equal(await page.locator("onkyo-panel [data-value='number.bass']").innerText(), "-1 dB");
      assert.equal(await page.locator("onkyo-panel [data-value='number.center_level']").innerText(), "Not available");
    }));

  test("a select and a switch call their services", () =>
    using({}, async (page) => {
      await page.locator("onkyo-panel .rowsel", { hasText: "Equalizer" }).locator(".opt", { hasText: "Preset 2" }).click();
      await page.locator("onkyo-panel .tgl", { hasText: "Cinema filter" }).click();
      const done = (await calls(page)).map((c) => `${c.domain}.${c.service}`);
      assert.deepEqual(done, ["select.select_option", "switch.turn_on"]);
      assert.equal(await page.locator("onkyo-panel .tgl", { hasText: "Cinema filter" }).getAttribute("aria-checked"), "true");
    }));

  test("an administrator renames from the page; a user is told why not", async () => {
    await using({}, async (page) => {
      await page.locator("onkyo-panel .setlink", { hasText: "Rename, hide and order inputs" }).click();
      const sheet = page.locator("onkyo-panel dialog.sheet");
      await sheet.waitFor();
      assert.equal(await sheet.locator("h2").innerText(), "Rename inputs");
    });
    await using({ admin: false }, async (page) => {
      assert.equal(await page.locator("onkyo-panel .setlink", { hasText: "Rename" }).count(), 0);
      assert.match(await page.locator("onkyo-panel .leftx").innerText(), /Only an administrator/);
    });
  });

  test("two receivers: a picker switches between them", () =>
    using({ otherReceiver: true }, async (page) => {
      const picker = page.locator("onkyo-panel select[data-device]");
      assert.equal(await picker.locator("option").count(), 2);
    }));

  test("standby says some settings need the receiver on", () =>
    using({ power: "standby" }, async (page) => {
      assert.match(await page.locator("onkyo-panel .right .notice").innerText(), /standby/);
    }));

  test("a phone shows one column and the menu button opens Home Assistant's sidebar", () =>
    using({ viewport: PHONE }, async (page) => {
      await page.locator("onkyo-panel .menu").click();
      assert.equal(await page.evaluate(() => window.menuToggles), 1);
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true);
      const left = await page.locator("onkyo-panel .left").boundingBox();
      const right = await page.locator("onkyo-panel .right").boundingBox();
      assert.ok(right.y >= left.y + left.height - 1, "settings sit below the card");
      // One column: names and receiver info come last, after the settings.
      assert.deepEqual(await leftTitles(page), []);
      assert.deepEqual((await titles(page)).slice(-2), ["Names", "Receiver"]);
    }));

  test("a desktop shows the card beside the settings", () =>
    using({ viewport: DESKTOP }, async (page) => {
      const left = await page.locator("onkyo-panel .left").boundingBox();
      const right = await page.locator("onkyo-panel .right").boundingBox();
      assert.ok(right.x >= left.x + left.width - 1, "settings sit to the right of the card");
      // The two columns end near the same height (no long right column beside empty space).
      assert.ok(Math.abs(left.y + left.height - (right.y + right.height)) < right.height * 0.4, `${left.height} vs ${right.height}`);
    }));

  test("a part that fails to load shows a message with Reload, not a blank page", async () => {
    const page = await browser.newPage({ viewport: DESKTOP });
    try {
      await page.route("**/styles.js*", (route) => route.abort());
      await page.goto(`${server.url}/panel.html`);
      await page.waitForFunction(() => window.panelReady);
      await page.evaluate(() => window.mountPanel({}));
      await page.waitForFunction(() => document.querySelector("onkyo-panel")?.shadowRoot?.textContent?.includes("could not load"), null, { timeout: 5000 });
      assert.equal(await page.locator("onkyo-panel button", { hasText: "Reload" }).count(), 1);
    } finally {
      await page.close();
    }
  });

  test("holding a stepper counts from the last value sent", () =>
    using({}, async (page) => {
      await page.evaluate(() => { window.hass.callService = async (d, s, data) => { window.hass.calls.push({ d, s, data }); await new Promise((r) => setTimeout(r, 400)); }; });
      const up = page.locator("onkyo-panel [aria-label='Bass up']");
      const box = await up.boundingBox();
      await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
      await page.mouse.down();
      await page.waitForTimeout(900);
      await page.mouse.up();
      const values = (await calls(page)).map((c) => c.data.value);
      assert.ok(values.length >= 3, `${values}`);
      assert.deepEqual(values, [...values].sort((a, b) => a - b));
      assert.equal(new Set(values).size, values.length, `repeats: ${values}`);
    }));
});

// ---------------------------------------------------------------------------------------
// Advanced settings (CI): onkyo_eiscp/ci_info, ci_read, ci_set, ci_restore

const ci = (page) => page.locator("onkyo-panel .cig");
const group = (page, title) => ci(page).locator(".cigroup", { hasText: title });
const openGroup = async (page, title) => {
  await group(page, title).locator("[data-ci=group]").click();
  await group(page, title).locator(".cibody").waitFor();
  await page.waitForFunction(() => !document.querySelector("onkyo-panel").shadowRoot.querySelector(".cibody .empty"));
};
const row = (scope, label) => scope.locator(".cirow").filter({ has: scope.page().locator(".n", { hasText: new RegExp(`^${label}$`) }) });
const ciWrites = (page) => page.evaluate(() => window.hass.ciWrites);

describe("advanced settings", () => {
  test("a receiver that answers shows the groups; every one is closed at first", () =>
    using({}, async (page) => {
      await ci(page).waitFor();
      const titles = await ci(page).locator(".cigroup > .cih .n").evaluateAll((nodes) => nodes.map((node) => node.firstChild.textContent));
      assert.deepEqual(titles, [
        "Input assign",
        "Input names and volume",
        "Per-input audio and HDMI",
        "TV out and HDMI",
        "Speaker levels, distances and crossover",
        "Equalizer",
        "Power and volume",
        "Multi-zone",
        "Other options",
        "Read only",
      ]);
      assert.equal(await ci(page).locator(".cibody").count(), 0);
    }));

  test("a model that does not answer shows no advanced settings (RULES.md 4)", () =>
    using({ model: "small" }, async (page) => {
      await page.waitForTimeout(100);
      assert.equal(await page.locator("onkyo-panel .cig").count(), 0);
    }));

  test("input assign shows the jacks with names and sets one", () =>
    using({}, async (page) => {
      await openGroup(page, "Input assign");
      const hdmi = group(page, "Input assign").locator(".cifamily", { hasText: "HDMI input assign" });
      // The names are the receiver's input names from card_info; the CD row is None.
      const cd = row(hdmi, "CD");
      assert.equal(await cd.locator("select").inputValue(), "NON");
      await cd.locator("select").selectOption("HI6");
      await page.waitForFunction(() => window.hass.ciWrites.length === 1);
      assert.deepEqual((await ciWrites(page))[0], { code: "HIC", key: {}, changes: { CD: "HI6" } });
      assert.equal(await row(hdmi, "CD").locator("select").inputValue(), "HI6");
      // Video assign is all None on this model, so it does not show at all.
      assert.equal(await group(page, "Input assign").locator(".cifamily", { hasText: "Video input assign" }).count(), 0);
    }));

  test("a bit is a switch; a skipped input says on", () =>
    using({}, async (page) => {
      await openGroup(page, "Input assign");
      const skip = group(page, "Input assign").locator(".cifamily", { hasText: "Input skip" });
      const aux = row(skip, "AUX").locator("[role=switch]");
      assert.equal(await aux.getAttribute("aria-checked"), "false");
      await aux.click();
      await page.waitForFunction(() => window.hass.ciWrites.length === 1);
      assert.deepEqual((await ciWrites(page))[0].changes, { AX: "001" });
      assert.equal(await row(skip, "AUX").locator("[role=switch]").getAttribute("aria-checked"), "true");
    }));

  test("speaker levels show tenths of a dB, set one and restore", () =>
    using({}, async (page) => {
      await openGroup(page, "Speaker levels");
      assert.match(await group(page, "Speaker levels").locator(".notice").innerText(), /calibration/);
      const levels = group(page, "Speaker levels").locator(".cifamily", { hasText: "Channel levels" });
      await levels.locator(".ciblock", { hasText: "Dirac slot 1" }).locator("[data-ci=block]").click();
      const block = () => levels.locator(".ciblock", { hasText: "Dirac slot 1" });
      const sub = () => row(block(), "Subwoofer").locator("input");
      assert.equal(await sub().inputValue(), "-3.0");
      await sub().fill("-2.9");
      await sub().blur();
      await page.waitForFunction(() => window.hass.ciWrites.length === 1);
      assert.deepEqual((await ciWrites(page))[0], { code: "LCC", key: { MM: "MM1" }, changes: { SW: "-29" } });
      assert.equal(await sub().inputValue(), "-2.9");
      assert.match(await block().locator(".ciact").innerText(), /1 changed/);
      await block().locator("[data-ci=restore]").click();
      await page.waitForFunction(() => document.querySelector("onkyo-panel").shadowRoot.querySelector(".ciact") === null);
      assert.equal(await sub().inputValue(), "-3.0");
      // Only the calibration families offer it.
      assert.equal(await group(page, "Power and volume").count(), 1);
    }));

  test("Keep forgets the saved values and leaves the new ones", () =>
    using({}, async (page) => {
      await openGroup(page, "Speaker levels");
      const dist = group(page, "Speaker levels").locator(".cifamily", { hasText: "Speaker distances" });
      await dist.locator(".ciblock", { hasText: "Dirac slot 2" }).locator("[data-ci=block]").click();
      const fr = row(dist.locator(".ciblock", { hasText: "Dirac slot 2" }), "Front right").locator("input");
      await fr.fill("4");
      await fr.blur();
      await page.waitForFunction(() => window.hass.ciWrites.length === 1);
      assert.deepEqual((await ciWrites(page))[0].changes, { FR: "004" });
      await dist.locator("[data-ci=keep]").click();
      await page.waitForFunction(() => document.querySelector("onkyo-panel").shadowRoot.querySelector(".ciact") === null);
      assert.equal(await row(dist.locator(".ciblock", { hasText: "Dirac slot 2" }), "Front right").locator("input").inputValue(), "4");
    }));

  test("the unit of distance is read only", () =>
    using({}, async (page) => {
      await openGroup(page, "Speaker levels");
      const dist = group(page, "Speaker levels").locator(".cifamily", { hasText: "Speaker distances" });
      const unit = row(dist.locator(".ciblock", { hasText: "All records" }), "Unit").locator("select");
      assert.equal(await unit.isDisabled(), true);
    }));

  test("the layout and the network are shown and never writable", () =>
    using({}, async (page) => {
      await openGroup(page, "Read only");
      const body = group(page, "Read only");
      assert.match(await body.innerText(), /Speaker layout/);
      assert.match(await body.innerText(), /Network/);
      const enabled = await body.locator("input:not([disabled]), select:not([disabled]), [role=switch]:not([disabled])").count();
      assert.equal(enabled, 0);
    }));

  test("a volume that is a word or a level", () =>
    using({}, async (page) => {
      await openGroup(page, "Power and volume");
      const vol = group(page, "Power and volume").locator(".cifamily", { hasText: "Volume" });
      const power = () => row(vol, "Power-on volume");
      assert.equal(await power().locator("select").inputValue(), "#");
      assert.equal(await power().locator("input").inputValue(), "124");
      await power().locator("input").fill("90");
      await power().locator("input").blur();
      await page.waitForFunction(() => window.hass.ciWrites.length === 1);
      assert.deepEqual((await ciWrites(page))[0].changes, { PV: "090" });
      await power().locator("select").selectOption("LST");
      await page.waitForFunction(() => window.hass.ciWrites.length === 2);
      assert.deepEqual((await ciWrites(page))[1].changes, { PV: "LST" });
    }));

  test("a non administrator reads the settings but cannot change them", () =>
    using({ admin: false }, async (page) => {
      await ci(page).waitFor();
      assert.match(await ci(page).innerText(), /Only an administrator/);
      await openGroup(page, "Input assign");
      const enabled = await group(page, "Input assign").locator("select:not([disabled]), [role=switch]:not([disabled])").count();
      assert.equal(enabled, 0);
    }));

  test("an equalizer band has plain steps; zones follow the model", () =>
    using({}, async (page) => {
      await openGroup(page, "Equalizer");
      const eq = group(page, "Equalizer").locator(".cifamily", { hasText: "Manual equalizer" });
      await eq.locator(".ciblock", { hasText: "Preset 1, Front" }).locator("[data-ci=block]").click();
      const band = row(eq.locator(".ciblock", { hasText: "Preset 1, Front" }), "Band 1").locator("input");
      await band.fill("2");
      await band.blur();
      await page.waitForFunction(() => window.hass.ciWrites.length === 1);
      assert.deepEqual((await ciWrites(page))[0], { code: "EQC", key: { PS: "001", CH: "FRT" }, changes: { B1: "+02" } });
    }));

  test("nothing writes until a value changes, and a refused value shows a message", () =>
    using({}, async (page) => {
      await openGroup(page, "Power and volume");
      assert.deepEqual(await ciWrites(page), []);
      const apc = group(page, "Power and volume").locator(".cifamily", { hasText: "Auto standby" });
      const field = row(apc, "Option ST").locator("input");
      await field.fill("1000");
      await field.blur();
      await page.waitForFunction(() => window.toasts.length === 1);
      assert.deepEqual(await ciWrites(page), []);
    }));

  test("the phone shows the groups in one column", () =>
    using({ viewport: PHONE }, async (page) => {
      await openGroup(page, "Input assign");
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true);
      const box = await ci(page).boundingBox();
      assert.ok(box.width <= PHONE.width);
    }));
});
