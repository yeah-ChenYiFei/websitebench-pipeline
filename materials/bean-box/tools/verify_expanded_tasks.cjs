const fs = require('fs');
const path = require('path');
const { chromium } = require('playwright');

const base = process.env.BEAN_BOX_BASE_URL || 'http://127.0.0.1:8488';
const allowedOrigin = new URL(base).origin;
const out = path.resolve(__dirname, '..', 'artifacts', 'offline-clone', 'expanded-task-evidence.json');
const results = [];
const network = [];
const syntheticEmail = `expanded-${Date.now()}@example.test`;
const password = 'local-password-123';

function check(id, task, condition, evidence) {
  if (!condition) throw new Error(`${id} failed: ${evidence}`);
  results.push({ id, task, status: 'complete', evidence });
}

async function localContext(browser, viewport = { width: 1440, height: 900 }) {
  const context = await browser.newContext({ viewport });
  await context.route('**/*', async route => {
    const request = route.request();
    const origin = new URL(request.url()).origin;
    network.push({ method: request.method(), url: request.url(), local: origin === allowedOrigin });
    if (origin !== allowedOrigin) return route.abort('blockedbyclient');
    return route.continue();
  });
  return context;
}

(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  try {
    const context = await localContext(browser);
    const page = await context.newPage();

    let response = await page.goto(`${base}/`, { waitUntil: 'networkidle' });
    check('WB016-T01', 'Public Entry / Primary Navigation', response.status() === 200 && await page.locator('nav.nav').isVisible(), 'HTTP 200; primary navigation visible');
    await page.locator('[data-cookie-close]').first().click();

    response = await page.goto(`${base}/coffee`);
    await page.fill('#catalog-search', 'Morning');
    await page.locator('.searchbar button').click();
    await page.locator('.product-card a').first().click();
    check('WB016-T03', 'Browse', response.status() === 200 && await page.locator('.detail h1').isVisible(), 'searched catalogue and opened a coffee detail');

    response = await page.goto(`${base}/account/signin`);
    check('WB016-T16', 'Authentication / Sign-In Entry', response.status() === 200 && await page.locator('input[type=password]').isVisible(), 'sign-in form rendered');
    response = await page.goto(`${base}/account/register`);
    check('WB016-T17', 'Authentication / Registration Entry', response.status() === 200 && await page.locator('input[name=display_name]').isVisible(), 'registration form rendered');

    await page.fill('input[name=display_name]', 'Expanded Task Student');
    await page.fill('input[name=email]', syntheticEmail);
    await page.fill('input[name=password]', password);
    await page.locator('button[type=submit]').click();
    const registrationCode = (await page.locator('[data-local-code]').innerText()).trim();
    await page.fill('input[name=code]', registrationCode);
    await page.locator('button[type=submit]').click();
    await page.waitForURL(`${base}/account`);
    const registeredAccountText = await page.locator('main').innerText();
    check('WB016-T06', 'Register', registeredAccountText.toLowerCase().includes('welcome, expanded task student'), `local-only registration terminal: ${registeredAccountText.slice(0, 180)}`);

    await page.goto(`${base}/coffee-subscription/configure`);
    if (await page.locator('[data-cookie-close]').first().isVisible()) await page.locator('[data-cookie-close]').first().click();
    await page.selectOption('select[name=preparation]', 'freshly-ground');
    await page.check('input[value=curators-choice]');
    check('WB016-T04', 'Quiz/Preferences', await page.locator('input[value=curators-choice]').isChecked() && (await page.inputValue('select[name=preparation]')) === 'freshly-ground', 'Freshly Ground and Curator Choice selected');
    await page.getByRole('button', { name: 'CONTINUE TO QUANTITY' }).click();
    await page.check('input[value=trace-six-cup]');
    await page.check('input[name=cadence][value="4"]');
    await page.getByRole('button', { name: 'CONTINUE TO REVIEW' }).click();
    await page.check('input[value=pay-per-delivery]');
    const reviewText = await page.locator('.review-box').innerText();
    check('WB016-T05', 'Plan', reviewText.includes('Freshly Ground') && reviewText.includes('6 cups') && reviewText.includes('Every 4 weeks') && reviewText.includes('$22.45'), 'server-rendered ground + trace-compatible 6-cup + monthly review visible');
    await page.getByRole('button', { name: 'CHECKOUT' }).click();
    const checkoutText = await page.locator('main').innerText();
    check('WB016-T02', 'ClawBench Core [697]', page.url().endsWith('/checkout') && checkoutText.includes('Freshly Ground') && checkoutText.includes('6 cups') && checkoutText.includes('Every 4 weeks') && checkoutText.includes('Pay Per Delivery'), 'server-rendered ground + curated + 6-cup + monthly state reached checkout');

    await page.locator('[data-fill-fixture]').click();
    check('WB016-T08', 'Shipping', (await page.inputValue('input[name=address]')) === '101 Test Market St', 'exact synthetic shipping fixture filled');
    check('WB016-T09', 'Payment', await page.locator('select[name=scenario_id]').isVisible() && await page.locator('input[name=card_number]').count() === 0, 'local-sandbox selector present and payment credential fields absent');
    await page.getByRole('button', { name: 'CONFIRM ORDER' }).click();
    check('WB016-T10', 'Start Subscription', (await page.locator('.success').innerText()).includes('Simulation complete'), 'approved checkout created order and subscription');
    check('WB016-T23', 'End-to-End Scenario [697]', (await page.locator('.success').innerText()).includes('No subscription, email, address or payment was sent'), 'full formal trace completed with local-only terminal proof');

    await page.goto(`${base}/account/subscriptions`);
    const managementText = await page.locator('main').innerText();
    check('WB016-T19', 'Post-Action / History and Management', managementText.toLowerCase().includes('manage subscriptions') && managementText.includes('SUB-'), 'authenticated management history rendered');
    await page.selectOption('select[name=preparation]', 'whole-bean');
    await page.selectOption('select[name=cadence]', '6');
    await page.getByRole('button', { name: 'SAVE CHANGES' }).click();
    check('WB016-T11', 'Modify Subscription', (await page.inputValue('select[name=preparation]')) === 'whole-bean' && (await page.inputValue('select[name=cadence]')) === '6' && (await page.locator('main').innerText()).includes('Every 6 weeks'), 'server-reloaded preparation and cadence modification persisted');
    await page.getByRole('button', { name: 'SKIP NEXT' }).click();
    await page.getByRole('button', { name: 'PAUSE' }).click();
    check('WB016-T12', 'Pause/Skip', (await page.locator('main').innerText()).includes('paused') && (await page.locator('main').innerText()).includes('skipped 1'), 'skip count persisted and plan paused');
    await page.getByRole('button', { name: 'RESUME' }).click();
    await page.getByRole('button', { name: 'CANCEL' }).click();
    await page.getByRole('button', { name: 'REACTIVATE' }).click();
    check('WB016-T13', 'Cancel/Reactivate', (await page.locator('main').innerText()).includes('Status: active'), 'cancel and reactivation transitions persisted');
    await page.goto(`${base}/account/orders`);
    check('WB016-T14', 'Orders', (await page.locator('main').innerText()).includes('BB-') && (await page.locator('main').innerText()).includes('$22.45'), 'local confirmed order visible in order history');

    await page.goto(`${base}/coffee?q=definitely-no-such-coffee`);
    check('WB016-T15', 'Anonymous Search / No Results', await page.getByText('No coffees found').isVisible(), 'zero-result state rendered');
    response = await page.goto(`${base}/faq`);
    check('WB016-T21', 'Help / Recovery', response.status() === 200 && await page.getByText('Frequently asked questions').isVisible(), 'FAQ and local recovery guidance available');
    response = await page.goto(`${base}/missing-expanded-task-route`);
    check('WB016-T22', 'Error / Not Found', response.status() === 404 && await page.getByText('This page needs a fresh grind').isVisible(), 'custom 404 returned HTTP 404');

    await page.goto(`${base}/account`);
    await page.getByRole('button', { name: 'SIGN OUT' }).click();
    await page.goto(`${base}/account/signin`);
    await page.fill('input[name=email]', syntheticEmail);
    await page.fill('input[name=password]', password);
    await page.getByRole('button', { name: 'CONTINUE' }).click();
    await page.waitForURL(`${base}/account`);
    check('WB016-T07', 'Login', (await page.locator('main').innerText()).toLowerCase().includes('welcome, expanded task student'), 'sign-out then local sign-in succeeded');
    await page.getByRole('button', { name: 'SIGN OUT' }).click();

    await page.goto(`${base}/account/password-reset`);
    await page.fill('input[name=email]', syntheticEmail);
    await page.getByRole('button', { name: 'CONTINUE' }).click();
    const resetCode = (await page.locator('[data-local-code]').innerText()).trim();
    await page.fill('input[name=code]', resetCode);
    await page.fill('input[name=new_password]', 'new-local-password-123');
    await page.getByRole('button', { name: 'CONTINUE' }).click();
    await page.waitForURL(`${base}/account`);
    check('WB016-T18', 'Authentication / Password Recovery', (await page.locator('main').innerText()).toLowerCase().includes('welcome, expanded task student'), 'local-only reset code changed password and authenticated rotated session');

    const deniedContext = await localContext(browser);
    const denied = await deniedContext.newPage();
    response = await denied.goto(`${base}/account/subscriptions`);
    const realEmailAttempt = await denied.request.post(`${base}/account/register`, { form: { phase: 'start', display_name: 'Rejected', email: 'person@example.com', password } });
    check('WB016-T20', 'Validation / Required Fields and Permissions', response.status() === 401 && realEmailAttempt.status() === 422, 'anonymous management denied and real-email registration rejected');
    await deniedContext.close();

    const external = network.filter(entry => !entry.local);
    if (external.length) throw new Error(`external requests observed: ${JSON.stringify(external)}`);
    fs.mkdirSync(path.dirname(out), { recursive: true });
    fs.writeFileSync(out, JSON.stringify({ site_id: 'bean-box', base_url: base, checked_at: new Date().toISOString(), results, summary: { complete: results.length, external_requests: external.length } }, null, 2));
    console.log(JSON.stringify({ complete: results.length, external_requests: external.length, artifact: out }));
    await context.close();
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exit(1); });
