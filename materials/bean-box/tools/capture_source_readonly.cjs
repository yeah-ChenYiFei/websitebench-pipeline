const fs = require('fs');
const path = require('path');
const { chromium } = require('playwright');

const site = path.resolve(__dirname, '..');
const out = path.join(site, 'artifacts', 'offline-clone', 'source-playwright-readonly');
fs.mkdirSync(out, { recursive: true });

const routes = [
  ['home', 'https://beanbox.com/'],
  ['subscription', 'https://beanbox.com/coffee-subscription/configure'],
  ['coffee', 'https://beanbox.com/coffee'],
];
const viewports = [
  ['desktop', { width: 1440, height: 900 }],
  ['mobile', { width: 390, height: 844 }],
];

(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  const observations = [];
  const blockedMutations = [];
  for (const [viewportName, viewport] of viewports) {
    for (const [routeId, url] of routes) {
      const context = await browser.newContext({ viewport, locale: 'en-US' });
      const page = await context.newPage();
      const requests = [];
      await page.route('**/*', async route => {
        const request = route.request();
        if (!['GET', 'HEAD'].includes(request.method())) {
          blockedMutations.push({ routeId, method: request.method(), url: request.url() });
          return route.abort('blockedbyclient');
        }
        return route.continue();
      });
      page.on('requestfinished', request => requests.push({ method: request.method(), url: request.url() }));
      let response;
      let error = null;
      try {
        response = await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 45000 });
        await page.waitForTimeout(2500);
      } catch (caught) {
        error = String(caught);
      }
      const finalUrl = page.url();
      const bodyText = await page.locator('body').innerText().catch(() => '');
      const metrics = await page.evaluate(() => {
        const sample = selector => {
          const element = document.querySelector(selector);
          if (!element) return null;
          const rect = element.getBoundingClientRect();
          const style = getComputedStyle(element);
          return {
            selector,
            box: { x: rect.x, y: rect.y, width: rect.width, height: rect.height },
            color: style.color,
            background: style.backgroundColor,
            fontFamily: style.fontFamily,
            fontSize: style.fontSize,
            fontWeight: style.fontWeight,
            lineHeight: style.lineHeight,
          };
        };
        return {
          title: document.title,
          viewport: { width: innerWidth, height: innerHeight },
          document: { width: document.documentElement.scrollWidth, height: document.documentElement.scrollHeight },
          overflow: document.documentElement.scrollWidth > innerWidth,
          samples: ['header', 'nav', 'main', 'h1', 'footer', 'button', 'input'].map(sample).filter(Boolean),
          links: [...document.querySelectorAll('a[href]')].slice(0, 40).map(a => ({ text: (a.innerText || '').trim(), href: a.getAttribute('href') })),
        };
      }).catch(() => null);
      const id = `${routeId}-${viewportName}`;
      await page.screenshot({ path: path.join(out, `${id}.png`), fullPage: true }).catch(() => {});
      fs.writeFileSync(path.join(out, `${id}.txt`), bodyText.slice(0, 30000));
      observations.push({
        id,
        requestedUrl: url,
        finalUrl,
        status: response ? response.status() : null,
        error,
        metrics,
        requestCount: requests.length,
        remoteOrigins: [...new Set(requests.map(item => new URL(item.url).origin))].sort(),
      });
      await context.close();
    }
  }
  await browser.close();
  const report = {
    schema_version: 'bean-box.source-playwright-readonly.v1',
    provider: 'bundled-playwright-msedge',
    anonymous: true,
    allowed_methods: ['GET', 'HEAD'],
    observations,
    blocked_mutations: blockedMutations,
  };
  fs.writeFileSync(path.join(out, 'report.json'), JSON.stringify(report, null, 2));
  console.log(JSON.stringify({ observations: observations.length, successful: observations.filter(o => o.status === 200).length, blocked_mutations: blockedMutations.length, out }, null, 2));
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
