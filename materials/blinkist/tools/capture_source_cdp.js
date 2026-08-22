const fs = require('node:fs/promises');
const path = require('node:path');
const { chromium } = require('../../../.tmp-node-playwright/node_modules/playwright');

const ROOT = path.resolve(__dirname, '..');
const OUT = path.join(ROOT, 'source-current', '2026-08-22-auth');
const ORIGIN = 'https://www.blinkist.com';
const VIEWPORTS = [
  { id: 'desktop-1440x900', width: 1440, height: 900 },
  { id: 'tablet-768x1024', width: 768, height: 1024 },
  { id: 'mobile-390x844', width: 390, height: 844 },
];

function safeName(value) {
  return value.replace(/[^a-z0-9_-]+/gi, '-').replace(/^-|-$/g, '').toLowerCase();
}

async function sanitizeDom(page) {
  return page.evaluate(() => {
    const clone = document.documentElement.cloneNode(true);
    clone.querySelectorAll('script, style, noscript').forEach((node) => node.remove());
    clone.querySelectorAll('input, textarea').forEach((node) => {
      node.removeAttribute('value');
      node.textContent = '';
    });
    clone.querySelectorAll('*').forEach((node) => {
      for (const attribute of [...node.attributes]) {
        if (/token|auth|cookie|session|password|secret/i.test(attribute.name)) {
          node.removeAttribute(attribute.name);
        }
      }
    });
    return clone.outerHTML
      .replace(/[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/gi, '[redacted-email]')
      .replace(/([?&](?:token|code|session|auth)[^=]*=)[^&#"']+/gi, '$1[redacted]');
  });
}

async function stateSummary(page, id, viewport) {
  const summary = await page.evaluate(() => {
    const text = (selector) => [...document.querySelectorAll(selector)]
      .map((node) => (node.textContent || '').replace(/\s+/g, ' ').trim())
      .filter(Boolean);
    const links = [...document.querySelectorAll('a[href]')].map((anchor) => ({
      text: (anchor.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 240),
      href: new URL(anchor.getAttribute('href'), location.href).pathname,
    })).filter((item) => item.href.startsWith('/'));
    const buttons = text('button').slice(0, 80);
    const inputs = [...document.querySelectorAll('input')].map((input) => ({
      type: input.type,
      placeholder: input.placeholder,
      name: input.name,
      ariaLabel: input.getAttribute('aria-label'),
    }));
    const images = [...document.images].map((image) => ({
      alt: image.alt,
      src: image.currentSrc || image.src,
      width: image.naturalWidth,
      height: image.naturalHeight,
    })).filter((image) => /^https?:/.test(image.src));
    return {
      urlPath: location.pathname,
      title: document.title,
      lang: document.documentElement.lang,
      headings: text('h1,h2,h3').slice(0, 100),
      buttons,
      inputs,
      links: links.slice(0, 500),
      images: images.slice(0, 500),
      bodyText: (document.body.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 30000),
      documentSize: { width: document.documentElement.scrollWidth, height: document.documentElement.scrollHeight },
    };
  });
  return { id, viewport, observedAt: new Date().toISOString(), ...summary };
}

async function capture(page, id, viewport, frames = 3) {
  const dir = path.join(OUT, safeName(id), viewport.id);
  await fs.mkdir(dir, { recursive: true });
  await page.waitForTimeout(1800);
  await page.evaluate(() => window.scrollTo(0, 0));
  const summary = await stateSummary(page, id, viewport);
  await fs.writeFile(path.join(dir, 'summary.json'), JSON.stringify(summary, null, 2));
  await fs.writeFile(path.join(dir, 'dom.html'), await sanitizeDom(page));
  for (let frame = 1; frame <= frames; frame += 1) {
    await page.screenshot({ path: path.join(dir, `frame-${frame}.png`), fullPage: true, animations: 'disabled' });
    await page.waitForTimeout(450);
  }
  return summary;
}

async function gotoGet(page, route) {
  const response = await page.goto(`${ORIGIN}${route}`, { waitUntil: 'domcontentloaded', timeout: 45000 });
  await page.waitForTimeout(2200);
  if (page.url().startsWith(ORIGIN) === false) throw new Error(`left approved origin: ${page.url()}`);
  return response ? response.status() : null;
}

async function main() {
  await fs.mkdir(OUT, { recursive: true });
  const browser = await chromium.connectOverCDP('http://127.0.0.1:9222');
  const context = browser.contexts()[0];
  if (!context) throw new Error('no Edge CDP context');
  const pages = context.pages();
  const page = pages.find((item) => item.url().startsWith(ORIGIN));
  if (!page) throw new Error('no page on approved Blinkist origin');
  const originalViewport = await page.evaluate(() => ({ width: outerWidth, height: outerHeight }));
  const findings = [];
  page.on('request', (request) => {
    if (!['GET', 'HEAD', 'OPTIONS'].includes(request.method())) {
      findings.push({ kind: 'observed-background-non-read-request', method: request.method(), origin: new URL(request.url()).origin });
    }
  });

  for (const viewport of VIEWPORTS) {
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    const forYouStatus = await gotoGet(page, '/en/app/for-you');
    await capture(page, 'for-you', viewport);

    const exploreStatus = await gotoGet(page, '/app/explore');
    await page.evaluate(async () => {
      for (let y = 0; y < document.documentElement.scrollHeight; y += Math.max(500, innerHeight - 100)) {
        window.scrollTo(0, y);
        await new Promise((resolve) => setTimeout(resolve, 120));
      }
      window.scrollTo(0, 0);
    });
    await capture(page, 'explore', viewport);

    const search = page.locator('input[placeholder*="Blinks"], input[placeholder*="Search"]').first();
    let searchStatus = 'input-unavailable';
    if (await search.count()) {
      await search.fill('Atomic Habits');
      await page.waitForTimeout(2400);
      searchStatus = 'filled-read-only';
      await capture(page, 'search-atomic-habits', viewport);
    }

    let detailStatus = null;
    const atomicLink = page.locator('a[href*="atomic-habits"]').first();
    if (await atomicLink.count()) {
      const href = await atomicLink.getAttribute('href');
      detailStatus = await gotoGet(page, new URL(href, ORIGIN).pathname);
      await capture(page, 'book-atomic-habits', viewport);
    } else {
      findings.push({ kind: 'atomic-habits-detail-link-unavailable', viewport: viewport.id });
    }

    const libraryStatus = await gotoGet(page, '/app/library');
    await capture(page, 'library', viewport);
    findings.push({ viewport: viewport.id, statuses: { forYouStatus, exploreStatus, searchStatus, detailStatus, libraryStatus } });
  }

  await page.setViewportSize(originalViewport);
  await gotoGet(page, '/en/app/for-you');
  const uniqueFindings = [...new Map(findings.map((item) => [JSON.stringify(item), item])).values()];
  await fs.writeFile(path.join(OUT, 'capture-report.json'), JSON.stringify({
    schemaVersion: 'websitebench.blinkist.auth-capture.v1',
    authority: 'source-evidence-only',
    credentialSegment: 'not-recorded',
    allowedOrigin: ORIGIN,
    viewports: VIEWPORTS,
    findings: uniqueFindings,
  }, null, 2));
  await browser.close();
}

main().catch((error) => {
  console.error(error.message);
  process.exitCode = 2;
});
