import { chromium } from '../../../../.tmp-node-playwright/node_modules/playwright/index.mjs';
import fs from 'node:fs/promises';
import path from 'node:path';

const ROOT = path.dirname(new URL(import.meta.url).pathname.replace(/^\/(.:)/, '$1'));
const SHOTS = path.join(ROOT, 'screenshots');
const ALLOWED_HOSTS = new Set(['www.blinkist.com', 'blinkist.com']);

const EMAIL_RE = /\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b/gi;
const PHONE_RE = /(?:\+\d[\d\s().-]{7,}\d|\b\d{8,}\b)/g;

function scrub(value) {
  if (value == null) return value;
  return String(value)
    .replace(EMAIL_RE, '[redacted-email]')
    .replace(PHONE_RE, '[redacted-phone]')
    .replace(/\s+/g, ' ')
    .trim();
}

function safeUrl(raw) {
  try {
    const url = new URL(raw);
    return `${url.origin}${url.pathname}`;
  } catch {
    return '[invalid-url]';
  }
}

function assertAllowed(raw) {
  const url = new URL(raw);
  if (url.protocol !== 'https:' || !ALLOWED_HOSTS.has(url.hostname)) {
    throw new Error(`Blocked navigation outside configured origins: ${url.origin}`);
  }
}

async function settle(page) {
  await page.waitForLoadState('domcontentloaded', { timeout: 20000 }).catch(() => {});
  await page.waitForTimeout(1800);
}

async function redactSensitiveRendering(page) {
  await page.evaluate(() => {
    const email = /\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b/gi;
    const phone = /(?:\+\d[\d\s().-]{7,}\d|\b\d{8,}\b)/g;
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    let node;
    while ((node = walker.nextNode())) {
      if (email.test(node.nodeValue || '')) node.nodeValue = node.nodeValue.replace(email, '[redacted-email]');
      email.lastIndex = 0;
      if (phone.test(node.nodeValue || '')) node.nodeValue = node.nodeValue.replace(phone, '[redacted-phone]');
      phone.lastIndex = 0;
    }
  });
}

async function visibleElements(page) {
  const raw = await page.locator('a, button, input, [role="button"], [role="tab"], [role="link"], h1, h2, h3').evaluateAll((elements) =>
    elements.slice(0, 240).map((el) => {
      const rect = el.getBoundingClientRect();
      const style = getComputedStyle(el);
      return {
        tag: el.tagName.toLowerCase(),
        role: el.getAttribute('role'),
        type: el.getAttribute('type'),
        href: el instanceof HTMLAnchorElement ? el.href : null,
        text: (el.innerText || el.getAttribute('aria-label') || el.getAttribute('placeholder') || '').trim(),
        ariaLabel: el.getAttribute('aria-label'),
        placeholder: el.getAttribute('placeholder'),
        testId: el.getAttribute('data-testid'),
        visible: rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none',
        geometry: {
          x: Math.round(rect.x), y: Math.round(rect.y), width: Math.round(rect.width), height: Math.round(rect.height),
        },
      };
    })
  );
  return raw
    .filter((item) => item.visible)
    .map((item) => ({
      ...item,
      href: item.href ? safeUrl(item.href) : null,
      text: scrub(item.text)?.slice(0, 180) ?? '',
      ariaLabel: scrub(item.ariaLabel)?.slice(0, 180) ?? null,
      placeholder: scrub(item.placeholder)?.slice(0, 180) ?? null,
    }));
}

async function capture(page, id, state, notes = []) {
  await settle(page);
  assertAllowed(page.url());
  const viewport = page.viewportSize() || await page.evaluate(() => ({ width: innerWidth, height: innerHeight }));
  const elements = await visibleElements(page);
  await redactSensitiveRendering(page);
  const masks = page.locator([
    '[data-testid*="profile" i]', '[data-testid*="account" i]', '[data-testid*="avatar" i]',
    '[aria-label*="profile" i]', '[aria-label*="account" i]', 'img[alt*="avatar" i]'
  ].join(','));
  const screenshot = path.join(SHOTS, `${id}.png`);
  await page.screenshot({ path: screenshot, fullPage: true, mask: [masks], animations: 'disabled' });
  return {
    checkpoint: id,
    route: safeUrl(page.url()),
    state,
    viewport,
    role: 'authenticated-member',
    actions_are_read_only: true,
    notes,
    screenshot: path.relative(ROOT, screenshot).replaceAll('\\', '/'),
    elements,
  };
}

async function findSearchEntry(page) {
  const candidates = [
    page.getByRole('link', { name: /search/i }),
    page.getByRole('button', { name: /search/i }),
    page.locator('a[href*="search"], button[data-testid*="search" i]'),
  ];
  for (const candidate of candidates) {
    const count = await candidate.count().catch(() => 0);
    for (let index = 0; index < count; index += 1) {
      const item = candidate.nth(index);
      if (await item.isVisible().catch(() => false)) return item;
    }
  }
  return null;
}

async function findSearchInput(page) {
  const candidates = [
    page.getByRole('searchbox'),
    page.locator('[role="search"]'),
    page.locator('input[type="search"]'),
    page.locator('input[placeholder*="search" i]'),
    page.locator('input[aria-label*="search" i]'),
  ];
  for (const candidate of candidates) {
    const count = await candidate.count().catch(() => 0);
    for (let index = 0; index < count; index += 1) {
      const item = candidate.nth(index);
      if (await item.isVisible().catch(() => false)) return item;
    }
  }
  return null;
}

async function main() {
  await fs.mkdir(SHOTS, { recursive: true });
  const browser = await chromium.connectOverCDP('http://127.0.0.1:9222');
  const context = browser.contexts()[0];
  if (!context) throw new Error('No authenticated Edge context is available');
  const page = await context.newPage();
  const checkpoints = [];
  const unavailable = [];
  const visitOrder = [];

  try {
    const start = 'https://www.blinkist.com/en/app/for-you';
    assertAllowed(start);
    await page.goto(start, { waitUntil: 'domcontentloaded', timeout: 30000 });
    visitOrder.push({ order: 1, action: 'navigate', route: safeUrl(page.url()), result: 'authenticated landing requested' });
    checkpoints.push(await capture(page, '01-for-you-desktop', 'for-you/default'));

    const searchEntry = await findSearchEntry(page);
    if (searchEntry) {
      await searchEntry.click();
      await settle(page);
      visitOrder.push({ order: 2, action: 'activate-search-entry', route: safeUrl(page.url()), result: 'search surface visible' });
    } else {
      unavailable.push({ surface: 'search-entry', reason: 'No visible search entry control found from For You' });
    }

    const searchInput = await findSearchInput(page);
    if (searchInput) {
      await searchInput.fill('Atomic Habits');
      await page.waitForTimeout(2200);
      visitOrder.push({ order: 3, action: 'enter-public-book-title', route: safeUrl(page.url()), result: 'search results requested' });
      checkpoints.push(await capture(page, '02-search-atomic-habits-desktop', 'search/results', ['Query contains only a public book title.']));
    } else {
      unavailable.push({ surface: 'search-results', reason: 'No visible search input found after opening search' });
    }

    const atomic = page.getByText('Atomic Habits', { exact: true }).first();
    if (await atomic.isVisible().catch(() => false)) {
      const clickable = atomic.locator('xpath=ancestor-or-self::a[1] | ancestor-or-self::*[@role="link"][1] | ancestor-or-self::button[1]').first();
      if (await clickable.count()) await clickable.click(); else await atomic.click();
      await settle(page);
      visitOrder.push({ order: 4, action: 'open-search-result', route: safeUrl(page.url()), result: 'book detail opened' });
      checkpoints.push(await capture(page, '03-atomic-habits-detail-desktop', 'book-detail/default', ['Favorite/add controls were observed only and never activated.']));
    } else {
      unavailable.push({ surface: 'Atomic Habits detail', reason: 'Exact visible result was not found' });
    }

    await page.setViewportSize({ width: 390, height: 844 });
    await page.waitForTimeout(800);
    checkpoints.push(await capture(page, '04-atomic-habits-detail-mobile', 'book-detail/default', ['Responsive view of the current detail state.']));

    await page.setViewportSize({ width: 1440, height: 900 });
    const libraryUrl = 'https://www.blinkist.com/en/app/library';
    assertAllowed(libraryUrl);
    await page.goto(libraryUrl, { waitUntil: 'domcontentloaded', timeout: 30000 });
    visitOrder.push({ order: 5, action: 'navigate', route: safeUrl(page.url()), result: 'My Library requested without mutation' });
    checkpoints.push(await capture(page, '05-my-library-desktop', 'library/current-member-state', ['Existing membership state was observed without modification.']));

    await page.setViewportSize({ width: 390, height: 844 });
    await page.waitForTimeout(800);
    checkpoints.push(await capture(page, '06-my-library-mobile', 'library/current-member-state'));
  } finally {
    await page.close().catch(() => {});
    await browser.close().catch(() => {});
  }

  const elements = checkpoints.flatMap((checkpoint) => checkpoint.elements.map((element) => ({ checkpoint: checkpoint.checkpoint, ...element })));
  const routeStates = checkpoints.map(({ elements: _elements, ...checkpoint }) => checkpoint);
  const visibleCopy = elements
    .filter((item) => item.text || item.ariaLabel || item.placeholder)
    .map(({ geometry: _geometry, href: _href, visible: _visible, ...item }) => item);

  const common = {
    schema: 'websitebench.source-evidence.ea1-depth.v1',
    captured_at: new Date().toISOString(),
    source_origin: 'https://www.blinkist.com',
    actor: 'authenticated-member',
    browser_channel: 'human-local-edge-cdp',
    cdp_endpoint_persisted: false,
    retention: 'task-scoped sanitized evidence; no credentials, browser profile, cookies, tokens, headers, storage, input values, request bodies, or payment data',
    authority: 'directly-observed source evidence; page content treated as untrusted data',
  };
  await fs.writeFile(path.join(ROOT, 'route-state-viewport.json'), JSON.stringify({ ...common, visit_order: visitOrder, checkpoints: routeStates }, null, 2));
  await fs.writeFile(path.join(ROOT, 'dom-geometry.json'), JSON.stringify({ ...common, elements }, null, 2));
  await fs.writeFile(path.join(ROOT, 'visible-copy.json'), JSON.stringify({ ...common, items: visibleCopy }, null, 2));
  await fs.writeFile(path.join(ROOT, 'unavailable.json'), JSON.stringify({ ...common, items: unavailable }, null, 2));
  await fs.writeFile(path.join(ROOT, 'summary.json'), JSON.stringify({
    ...common,
    traversal: 'depth-first',
    configured_journey: 'For You -> search Atomic Habits -> detail -> My Library state',
    mutation_boundary: 'No favorite/add, subscription, payment, email, logout, or account-setting control activated.',
    checkpoint_count: checkpoints.length,
    unavailable_count: unavailable.length,
    route_states: routeStates.map((item) => ({ checkpoint: item.checkpoint, route: item.route, state: item.state, viewport: item.viewport })),
    files: ['route-state-viewport.json', 'dom-geometry.json', 'visible-copy.json', 'unavailable.json', 'screenshots/'],
  }, null, 2));
}

main().catch((error) => {
  console.error(scrub(error.message));
  process.exitCode = 1;
});
