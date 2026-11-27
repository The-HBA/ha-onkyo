// Browser tests of the Remote and Playing tabs of the Onkyo remote card.
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

const calls = (page) => page.evaluate(() => window.hass.calls);
const card = (page, selector) => page.locator(`onkyo-remote-card ${selector}`);
const goTo = (page, label) => card(page, "[role=tab]").filter({ hasText: label }).click();

async function using(options, tab, body) {
  const { page, errors } = await openCard(browser, server.url, options);
  try {
    if (tab) await goTo(page, tab);
    await body(page);
    assert.deepEqual(errors, []);
  } finally {
    await page.close();
  }
}

describe("tab row", () => {
  test("a full model has Main, Modes, Remote and Playing, in that order", () =>
    using({}, null, async (page) => {
      assert.deepEqual(await card(page, "[role=tab]").allInnerTexts(), ["Main", "Modes", "Remote", "Playing"]);
    }));

  test("Zones is not built here: no Zones tab even on a model with zones", () =>
    using({}, null, async (page) => {
      assert.equal(await card(page, "[role=tab]").filter({ hasText: "Zones" }).count(), 0);
    }));
});

describe("remote tab", () => {
  test("shows the D-pad, Enter, six keys and the volume group", () =>
    using({}, "Remote", async (page) => {
      assert.equal(await card(page, ".p-remote .dk").count(), 5);
      assert.deepEqual(await card(page, ".p-remote .key").allInnerTexts(), ["Back", "Home", "Menu", "Quick menu", "Audio", "Video"]);
      assert.equal(await card(page, ".p-remote .gt", ).filter({ hasText: "Volume" }).count(), 1);
      assert.match(await card(page, ".p-remote .vread").innerText(), /dB/);
    }));

  test("each key sends its command through the remote entity", () =>
    using({}, "Remote", async (page) => {
      await card(page, ".dk.ok").click();
      await card(page, ".key", ).filter({ hasText: "Back" }).click();
      await card(page, ".key").filter({ hasText: "Quick menu" }).click();
      await card(page, ".dk.up").click();
      const sent = (await calls(page)).filter((c) => c.domain === "remote");
      assert.deepEqual(
        sent.map((c) => [c.service, c.data.command]),
        [["send_command", ["enter"]], ["send_command", ["exit"]], ["send_command", ["quick"]], ["send_command", ["up"]]],
      );
      assert.ok(sent.every((c) => c.data.entity_id === "remote.onkyo_tx_rz50_remote"));
    }));

  test("an arrow repeats while held", () =>
    using({}, "Remote", async (page) => {
      const arrow = card(page, ".dk.down");
      const box = await arrow.boundingBox();
      await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
      await page.mouse.down();
      await page.waitForTimeout(900);
      await page.mouse.up();
      const count = (await calls(page)).filter((c) => c.data.command?.[0] === "down").length;
      assert.ok(count >= 3, `only ${count} presses`);
    }));

  test("the volume buttons work here too", () =>
    using({}, "Remote", async (page) => {
      await card(page, "[data-a=mute]").click();
      assert.deepEqual((await calls(page)).map((c) => c.service), ["volume_mute"]);
    }));

  test("standby: a notice and keys that cannot be pressed", () =>
    using({ power: "standby" }, "Remote", async (page) => {
      assert.match(await card(page, ".notice").innerText(), /standby/);
      assert.equal(await card(page, ".p-remote .grp").first().evaluate((el) => getComputedStyle(el).pointerEvents), "none");
    }));

  test("no remote entity, no Remote tab (RULES.md 4)", () =>
    using({}, null, async (page) => {
      await page.evaluate(() => {
        delete window.hass.entities["remote.onkyo_tx_rz50_remote"];
        window.hass.set({});
      });
      assert.equal(await card(page, "[role=tab]").filter({ hasText: "Remote" }).count(), 0);
    }));
});

describe("playing tab", () => {
  test("Atmos from HDMI: audio and video columns, as the receiver reports them", () =>
    using({ signal: "atmos" }, "Playing", async (page) => {
      const audio = await card(page, ".np > div").nth(0).innerText();
      assert.match(audio, /Dolby Atmos/);
      assert.match(audio, /TrueHD · 48 kHz/);
      assert.match(audio, /HDMI 1 · out 6\.1 ch/);
      const video = await card(page, ".np > div").nth(1).innerText();
      assert.match(video, /4K 23 Hz/);
      assert.match(video, /HDR10/);
      assert.match(video, /RGB · 24 bit/);
      assert.ok(!video.includes("3840"));
      assert.equal(await card(page, ".grp .gv").first().innerText(), "Streaming");
    }));

  test("no signal and no video say so", () =>
    using({ signal: "none" }, "Playing", async (page) => {
      const columns = await card(page, ".np > div").allInnerTexts();
      assert.match(columns[0], /No signal/);
      assert.match(columns[1], /No video/);
    }));

  test("PCM from an analog input: audio only", () =>
    using({ signal: "pcm" }, "Playing", async (page) => {
      assert.match(await card(page, ".np > div").nth(0).innerText(), /PCM\s+44\.1 kHz · 2\.0 ch/);
      assert.match(await card(page, ".np > div").nth(1).innerText(), /No video[\s\S]*Audio-only input/);
    }));

  test("a model without a video sensor shows the audio column only", () =>
    using({ model: "small", signal: "pcm" }, "Playing", async (page) => {
      assert.equal(await card(page, ".np > div").count(), 1);
      assert.equal(await card(page, ".np .k").innerText(), "Audio");
    }));

  test("standby: both columns say the receiver is off", () =>
    using({ power: "standby" }, "Playing", async (page) => {
      assert.match(await card(page, ".np").innerText(), /Receiver in standby[\s\S]*Receiver in standby/);
    }));

  test("late night: four choices, the current one selected, a tap selects", () =>
    using({}, "Playing", async (page) => {
      const grid = card(page, ".grp:has(.gt:text('Quick settings')) .seg").first();
      assert.deepEqual(await grid.locator(".opt").allInnerTexts(), ["Off", "Low", "High", "Auto"]);
      assert.equal(await grid.locator(".opt.sel").innerText(), "Off");
      await grid.locator(".opt").filter({ hasText: "Low" }).click();
      const [call] = await calls(page);
      assert.deepEqual([call.domain, call.service, call.data.option], ["select", "select_option", "low"]);
      assert.match(call.data.entity_id, /late_night$/);
      assert.equal(await grid.locator(".opt.sel").innerText(), "Low");
    }));

  test("a refused late night choice shows the receiver's message as a toast", () =>
    using({ signal: "pcm" }, "Playing", async (page) => {
      const toasts = [];
      await page.exposeFunction("onToast", (message) => toasts.push(message));
      await page.evaluate(() => window.card.addEventListener("hass-notification", (e) => window.onToast(e.detail.message)));
      await card(page, ".opt").filter({ hasText: "High" }).click();
      await page.waitForTimeout(100);
      assert.deepEqual(toasts, ["Late night High is not available with this signal"]);
      assert.equal(await card(page, ".grp .seg .opt.sel").first().innerText(), "Off");
    }));

  test("late night unavailable while on: hidden, with one grey line", () =>
    using({}, "Playing", async (page) => {
      await page.evaluate(() => {
        const id = "select.onkyo_tx_rz50_late_night";
        window.hass.states[id] = { ...window.hass.states[id], state: "unavailable" };
        window.hass.onChange();
      });
      assert.equal(await card(page, ".lbl", ).filter({ hasText: "Late night" }).count(), 0);
      assert.match(await card(page, ".qnote").innerText(), /Late night is not available with this signal/);
    }));

  test("sleep timer: Off, 30, 60, 90 min; a tap sets minutes", () =>
    using({}, "Playing", async (page) => {
      const grid = card(page, ".grp:has(.gt:text('Quick settings')) .seg").nth(1);
      assert.deepEqual(await grid.locator(".opt").allInnerTexts(), ["Off", "30 min", "60 min", "90 min"]);
      assert.equal(await grid.locator(".opt.sel").innerText(), "Off");
      await grid.locator(".opt").filter({ hasText: "60 min" }).click();
      const [call] = await calls(page);
      assert.deepEqual([call.domain, call.service, call.data.value], ["number", "set_value", 60]);
      assert.equal(await grid.locator(".opt.sel").innerText(), "60 min");
    }));

  test("sleep timer unavailable while on: hidden, with one grey line", () =>
    using({}, "Playing", async (page) => {
      await page.evaluate(() => {
        const id = "number.onkyo_tx_rz50_sleep_timer";
        window.hass.states[id] = { ...window.hass.states[id], state: "unavailable" };
        window.hass.onChange();
      });
      assert.equal(await card(page, ".lbl").filter({ hasText: "Sleep timer" }).count(), 0);
      assert.match(await card(page, ".qnote").innerText(), /Sleep timer is not available/);
    }));

  test("an unavailable video sensor while on hides the Video column", () =>
    using({}, "Playing", async (page) => {
      await page.evaluate(() => {
        const id = "sensor.onkyo_tx_rz50_video_input";
        window.hass.states[id] = { ...window.hass.states[id], state: "unavailable" };
        window.hass.onChange();
      });
      assert.equal(await card(page, ".np > div").count(), 1);
    }));

  test("Music Optimizer in Stereo is a switch that toggles", () =>
    using({ signal: "pcm" }, "Playing", async (page) => {
      const toggle = card(page, ".tgl");
      assert.equal(await toggle.getAttribute("aria-checked"), "false");
      await toggle.click();
      const [call] = await calls(page);
      assert.deepEqual([call.domain, call.service], ["switch", "turn_on"]);
      assert.equal(await toggle.getAttribute("aria-checked"), "true");
      await toggle.click();
      assert.equal((await calls(page)).at(-1).service, "turn_off");
    }));

  test("Music Optimizer outside Stereo: no switch, one grey line", () =>
    using({ signal: "atmos" }, "Playing", async (page) => {
      assert.equal(await card(page, ".tgl").count(), 0);
      assert.match(await card(page, ".qnote").innerText(), /Music Optimizer works in Stereo only/);
    }));

  test("a model without Music Optimizer or sleep timer shows neither and no note (RULES.md 4)", () =>
    using({ model: "small", signal: "pcm" }, "Playing", async (page) => {
      assert.equal(await card(page, ".tgl").count(), 0);
      assert.equal(await card(page, ".qnote").count(), 0);
      assert.equal(await card(page, ".lbl").filter({ hasText: "Sleep timer" }).count(), 0);
      assert.equal(await card(page, ".lbl").filter({ hasText: "Late night" }).count(), 1);
    }));

  test("standby: quick settings are dimmed and cannot be pressed", () =>
    using({ power: "standby" }, "Playing", async (page) => {
      const group = card(page, ".grp:has(.gt:text('Quick settings'))");
      assert.equal(await group.evaluate((el) => getComputedStyle(el).pointerEvents), "none");
      assert.equal(await card(page, ".qnote").count(), 0);
    }));

  test("Receiver settings opens the sidebar page", () =>
    using({}, "Playing", async (page) => {
      await card(page, ".setlink").click();
      assert.equal(new URL(page.url()).pathname, "/onkyo");
    }));
});

describe("fit and layout", () => {
  test("the new tabs on a tablet use two columns and fit", async () => {
    const { page, errors } = await openCard(browser, server.url, { viewport: TABLET, wide: true });
    try {
      for (const label of ["Remote", "Playing"]) {
        await goTo(page, label);
        assert.deepEqual(await fitProblems(page), [], label);
      }
      assert.deepEqual(errors, []);
    } finally {
      await page.close();
    }
  });

  for (const viewport of [PHONE, SMALL_PHONE]) {
    test(`${viewport.width}px: Remote and Playing stay inside the tab area, light and dark`, async () => {
      for (const theme of ["light", "dark"]) {
        const { page, errors } = await openCard(browser, server.url, { viewport, theme, signal: "dtsx" });
        try {
          for (const label of ["Remote", "Playing"]) {
            await goTo(page, label);
            assert.deepEqual(await fitProblems(page), [], `${label} ${theme}`);
          }
          assert.deepEqual(errors, []);
        } finally {
          await page.close();
        }
      }
    });
  }
});
