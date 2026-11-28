// Serves the card files and a test page, and opens the card in Chromium.

import { readFile } from "node:fs/promises";
import { createServer } from "node:http";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const WWW = path.resolve(HERE, "../../custom_components/onkyo_eiscp/www");
const BASE = "/onkyo_eiscp_static/";

export const PHONE = { width: 390, height: 844 };
export const SMALL_PHONE = { width: 360, height: 844 };
export const TABLET = { width: 820, height: 1180 };
export const DESKTOP = { width: 1280, height: 800 };

const TEST_FILES = {
  "/": path.join(HERE, "page.html"),
  "/panel.html": path.join(HERE, "panel.html"),
  "/fake-hass.js": path.join(HERE, "fake-hass.js"),
  "/ci-ws.json": path.join(HERE, "ci-ws.json"),
};

/** Start a web server on 127.0.0.1; returns its base URL and a close function. */
export async function startServer() {
  const server = createServer(async (request, response) => {
    const pathname = new URL(request.url, "http://127.0.0.1").pathname;
    let file = TEST_FILES[pathname];
    if (!file && pathname.startsWith(BASE)) {
      const relative = path.normalize(pathname.slice(BASE.length));
      if (!relative.startsWith("..")) file = path.join(WWW, relative);
    }
    let body;
    try {
      body = file ? await readFile(file) : null;
    } catch {
      body = null;
    }
    if (!body) {
      response.writeHead(404).end();
      return;
    }
    const type = file.endsWith(".html") ? "text/html" : file.endsWith(".json") ? "application/json" : "text/javascript";
    response.writeHead(200, { "content-type": `${type}; charset=utf-8` });
    response.end(body);
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  return {
    url: `http://127.0.0.1:${server.address().port}`,
    close: () => new Promise((resolve) => server.close(resolve)),
  };
}

/**
 * Open a page with the card mounted. Options: theme ("light" or "dark"), model, power,
 * signal, admin, viewport, wide, config, deviceScaleFactor. Script errors on the page are
 * collected in `errors`.
 */
export async function openCard(browser, baseUrl, options = {}) {
  const { theme = "light", viewport = PHONE, wide = false, config = {}, deviceScaleFactor = 1, ...receiver } = options;
  // Reduced motion turns transitions off, so styles are final at once.
  const page = await browser.newPage({ viewport, deviceScaleFactor, colorScheme: theme, reducedMotion: "reduce" });
  const errors = [];
  page.on("pageerror", (error) => errors.push(error));
  await page.goto(`${baseUrl}/?theme=${theme}${wide ? "&wide=1" : ""}`);
  await page.waitForFunction(() => window.cardReady);
  await page.evaluate(([opts, cfg]) => window.mountCard(opts, cfg), [receiver, config]);
  await page.locator("onkyo-remote-card .hname").waitFor();
  return { page, errors };
}

/** Open the sidebar page. Options as `openCard`, plus `narrow`. */
export async function openPanel(browser, baseUrl, options = {}) {
  const { theme = "light", viewport = DESKTOP, narrow = viewport.width < 870, deviceScaleFactor = 1, ...receiver } = options;
  const page = await browser.newPage({ viewport, deviceScaleFactor, colorScheme: theme, reducedMotion: "reduce" });
  const errors = [];
  page.on("pageerror", (error) => errors.push(error));
  await page.goto(`${baseUrl}/panel.html?theme=${theme}`);
  await page.waitForFunction(() => window.panelReady);
  await page.evaluate((opts) => window.mountPanel(opts), { narrow, ...receiver });
  await page.locator("onkyo-panel onkyo-remote-card .hname").waitFor();
  return { page, errors };
}
