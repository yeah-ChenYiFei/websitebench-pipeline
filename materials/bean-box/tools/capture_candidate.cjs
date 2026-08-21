const fs = require('fs');
const path = require('path');
const { chromium } = require('playwright');

const site = path.resolve(__dirname, '..');
const out = path.join(site, 'artifacts', 'offline-clone', 'candidate-capture');
const base = process.env.BEAN_BOX_BASE_URL || 'http://127.0.0.1:8476';
const allowedOrigin = new URL(base).origin;
fs.mkdirSync(out, { recursive: true });

const network = [];
const ledger = [];
const blockedExternal = [];

async function enforceLocalOnly(context, checkpoint) {
  await context.route('**/*', async route => {
    const request = route.request();
    const origin = new URL(request.url()).origin;
    if (origin !== allowedOrigin) {
      blockedExternal.push({ checkpoint, method: request.method(), url: request.url() });
      await route.abort('blockedbyclient');
      return;
    }
    await route.continue();
  });
}

async function observe(page, checkpoint) {
  const external = [];
  page.on('request', request => {
    const url = new URL(request.url());
    network.push({ checkpoint, method: request.method(), origin: url.origin, path: url.pathname });
    if (!['127.0.0.1', 'localhost'].includes(url.hostname)) external.push(request.url());
  });
  return external;
}

async function shot(browser, id, route, viewport) {
  const context = await browser.newContext({ viewport });
  await enforceLocalOnly(context, id);
  const page = await context.newPage();
  const external = await observe(page, id);
  const response = await page.goto(base + route, { waitUntil: 'networkidle' });
  if (!response || response.status() < 200 || response.status() >= 400) {
    throw new Error(`${id} navigation failed with ${response ? response.status() : 'no response'}`);
  }
  await page.screenshot({ path: path.join(out, `${id}.png`), fullPage: true });
  const result = { id, route, viewport, status: response.status(), title: await page.title(), external_requests: external };
  await context.close();
  return result;
}

(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  const captures = [];
  for (const viewport of [{ name: 'desktop', width: 1440, height: 900 }, { name: 'mobile', width: 390, height: 844 }]) {
    for (const [id, route] of [['home','/'],['subscription','/coffee-subscription/configure'],['coffee','/coffee']]) {
      captures.push(await shot(browser, `${id}-${viewport.name}`, route, viewport));
    }
  }

  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  await enforceLocalOnly(context, 'p0-journey');
  const page = await context.newPage();
  const external = await observe(page, 'p0-journey');
  await page.goto(base + '/coffee-subscription/configure', { waitUntil: 'networkidle' });
  await page.locator('[data-cookie-close]').first().click();
  const act = async (selector, visible, raw, formAction, action = 'click') => {
    await page.locator('.cookie-layer').evaluateAll(nodes => nodes.forEach(node => node.classList.add('hidden')));
    if (action === 'check') await page.locator(selector).check({ force: true });
    else if (action === 'select') await page.locator(selector).selectOption(formAction.value, { force: true });
    else await page.locator(selector).click({ force: true });
    ledger.push({ clone_url: page.url(), selector, visible_text_proof: visible, raw_markup_proof: raw, form_action: typeof formAction === 'string' ? formAction : formAction.action, action });
  };
  await act('select[name="preparation"]', 'Freshly Ground', 'name="preparation"', { action: '/coffee-subscription/configure', value: 'freshly-ground' }, 'select');
  await act('input[value="curators-choice"]', "CURATOR'S CHOICE™", 'value="curators-choice"', '/coffee-subscription/configure', 'check');
  await act('button:has-text("CONTINUE TO QUANTITY")', 'CONTINUE TO QUANTITY', 'name="action" value="to-quantity"', '/coffee-subscription/configure');
  await act('input[value="trace-six-cup"]', '6-Cup Size', 'value="trace-six-cup"', '/coffee-subscription/configure', 'check');
  await act('input[name="cadence"][value="4"]', 'Every 4 weeks · Monthly', 'name="cadence" value="4"', '/coffee-subscription/configure', 'check');
  await act('button:has-text("CONTINUE TO REVIEW")', 'CONTINUE TO REVIEW', 'name="action" value="to-review"', '/coffee-subscription/configure');
  await act('input[value="pay-per-delivery"]', 'Pay-Per-Delivery', 'value="pay-per-delivery"', '/coffee-subscription/configure', 'check');
  await page.screenshot({ path: path.join(out, 'subscription-review-desktop.png'), fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: path.join(out, 'subscription-review-mobile.png'), fullPage: true });
  await page.setViewportSize({ width: 1440, height: 900 });
  await act('button:has-text("CHECKOUT")', 'CHECKOUT', 'name="action" value="checkout"', '/coffee-subscription/configure');
  await page.waitForURL('**/checkout*');
  await act('[data-fill-fixture]', 'Fill synthetic fixture', 'data-fill-fixture', '/checkout');
  await page.screenshot({ path: path.join(out, 'checkout-synthetic-filled-desktop.png'), fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: path.join(out, 'checkout-synthetic-filled-mobile.png'), fullPage: true });
  await page.setViewportSize({ width: 1440, height: 900 });
  await act('select[name="scenario_id"]', 'Simulated decline', 'name="scenario_id"', { action: '/checkout', value: 'sandbox-declined' }, 'select');
  await act('button:has-text("CONFIRM LOCAL ORDER")', 'CONFIRM LOCAL ORDER', 'type="submit"', '/checkout');
  await page.screenshot({ path: path.join(out, 'checkout-declined-desktop.png'), fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: path.join(out, 'checkout-declined-mobile.png'), fullPage: true });
  await page.setViewportSize({ width: 1440, height: 900 });
  await act('select[name="scenario_id"]', 'Simulated approval', 'name="scenario_id"', { action: '/checkout', value: 'sandbox-approved' }, 'select');
  await act('button:has-text("CONFIRM LOCAL ORDER")', 'CONFIRM LOCAL ORDER', 'type="submit"', '/checkout');
  await page.screenshot({ path: path.join(out, 'checkout-success-desktop.png'), fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: path.join(out, 'checkout-success-mobile.png'), fullPage: true });
  captures.push({ id: 'p0-journey', route: '/coffee-subscription/configure -> /checkout', viewport: { width: 1440, height: 900 }, status: 200, title: await page.title(), external_requests: external });
  await context.close();
  await browser.close();

  fs.writeFileSync(path.join(out, 'capture-summary.json'), JSON.stringify({ schema_version: 'bean-box.candidate-capture.v1', base_url: base, captures }, null, 2));
  const externalRequestCount = network.filter(item => item.origin !== allowedOrigin).length;
  fs.writeFileSync(path.join(out, 'network-audit.json'), JSON.stringify({ schema_version: 'bean-box.network-audit.v1', requests: network, blocked_external_requests: blockedExternal, external_request_count: externalRequestCount }, null, 2));
  fs.writeFileSync(path.join(site, 'tools', 'interaction-ledger.json'), JSON.stringify({ schema_version: 'bean-box.interaction-ledger.v1', human_trace_text_id: 'ht-697', entries: ledger }, null, 2));
  if (blockedExternal.length || externalRequestCount) {
    throw new Error(`candidate attempted ${Math.max(blockedExternal.length, externalRequestCount)} external request(s)`);
  }
  console.log(JSON.stringify({ captures: captures.length, ledger_entries: ledger.length, external_request_count: externalRequestCount, out }, null, 2));
})().catch(error => { console.error(error.stack || error); process.exit(1); });
