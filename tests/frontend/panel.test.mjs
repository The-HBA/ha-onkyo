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

const titles = (page) => page.locator("onkyo-panel .right .gt").allInnerTexts();
const calls = (page) => page.evaluate(() => window.hass.calls);

describe("sidebar page", () => {
  test("shows the card and the settings the model has", () =>
    using({}, async (page) => {
      assert.equal(await page.locator("onkyo-panel h1").innerText(), "Onkyo");
      assert.equal(await page.locator("onkyo-panel onkyo-remote-card .hname").innerText(), "Onkyo TX-RZ50");
      assert.deepEqual(await titles(page), ["Tone", "Levels", "Sound", "Setup", "Names", "Receiver"]);
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
      assert.match(await page.locator("onkyo-panel .right").innerText(), /Only an administrator/);
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
    }));

  test("a desktop shows the card beside the settings", () =>
    using({ viewport: DESKTOP }, async (page) => {
      const left = await page.locator("onkyo-panel .left").boundingBox();
      const right = await page.locator("onkyo-panel .right").boundingBox();
      assert.ok(right.x >= left.x + left.width - 1, "settings sit to the right of the card");
    }));
});
