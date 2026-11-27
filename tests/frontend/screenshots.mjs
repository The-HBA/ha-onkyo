// Screenshots of the card and the sidebar page from the fake hass, into ./shots/.
// Run from this folder: npm run screenshots.

import { mkdir } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { chromium } from "playwright";

import { DESKTOP, openCard, openPanel, PHONE, SMALL_PHONE, startServer, TABLET } from "./harness.mjs";

const OUT = path.join(path.dirname(fileURLToPath(import.meta.url)), "shots");
await mkdir(OUT, { recursive: true });
const server = await startServer();
const browser = await chromium.launch();
const shot = (page, name) => page.screenshot({ path: path.join(OUT, `${name}.png`) });
const tab = (page, label) => page.locator("onkyo-remote-card [role=tab]", { hasText: label }).click();

for (const theme of ["dark", "light"]) {
  let { page } = await openCard(browser, server.url, { theme, signal: theme === "dark" ? "atmos" : "pcm" });
  await shot(page, `card-main-${theme}`);
  await tab(page, "Modes");
  await shot(page, `card-modes-${theme}`);
  await page.close();
}

for (const [theme, signal] of [["dark", "atmos"], ["light", "pcm"]]) {
  const { page } = await openCard(browser, server.url, { theme, signal });
  await tab(page, "Remote");
  await shot(page, `card-remote-${theme}`);
  await tab(page, "Playing");
  await shot(page, `card-playing-${theme}`);
  await page.close();
}

{
  const { page } = await openCard(browser, server.url, { theme: "dark", power: "standby" });
  await tab(page, "Playing");
  await shot(page, "card-playing-standby");
  await page.close();
}

{
  const { page } = await openCard(browser, server.url, { theme: "dark", viewport: SMALL_PHONE, signal: "dtsx" });
  await tab(page, "Playing");
  await shot(page, "card-playing-360");
  await tab(page, "Remote");
  await shot(page, "card-remote-360");
  await page.close();
}

{
  const { page } = await openCard(browser, server.url, { theme: "dark", model: "small", signal: "pcm" });
  await tab(page, "Playing");
  await shot(page, "card-playing-small-model");
  await page.close();
}

{
  const { page } = await openCard(browser, server.url, { theme: "light", viewport: TABLET, wide: true });
  await tab(page, "Remote");
  await shot(page, "card-remote-tablet");
  await tab(page, "Playing");
  await shot(page, "card-playing-tablet");
  await page.close();
}

let { page } = await openCard(browser, server.url, { theme: "dark", power: "standby" });
await shot(page, "card-main-standby");
await page.close();

({ page } = await openCard(browser, server.url, { theme: "dark", model: "small", signal: "pcm" }));
await shot(page, "card-main-small-model");
await page.locator("onkyo-remote-card .vread").click();
await shot(page, "card-main-small-model-percent");
await page.close();

({ page } = await openCard(browser, server.url, { theme: "dark" }));
await page.locator("onkyo-remote-card .tbtn").click();
await page.locator("onkyo-remote-card dialog.sheet").waitFor();
await shot(page, "card-rename-inputs");
await page.close();

({ page } = await openCard(browser, server.url, { theme: "dark", signal: "pcm" }));
await tab(page, "Modes");
await page.locator("onkyo-remote-card .tbtn").click();
await page.locator("onkyo-remote-card dialog.sheet").waitFor();
await shot(page, "card-rename-modes");
await page.close();

({ page } = await openCard(browser, server.url, { theme: "light", viewport: TABLET, wide: true }));
await shot(page, "card-main-tablet");
await page.close();

({ page } = await openPanel(browser, server.url, { theme: "dark", viewport: DESKTOP }));
await shot(page, "panel-desktop");
await page.close();

({ page } = await openPanel(browser, server.url, { theme: "dark", viewport: { ...PHONE, height: 1400 } }));
await shot(page, "panel-phone");
await page.close();

await browser.close();
await server.close();
console.log(`Screenshots in ${OUT}`);
