#!/usr/bin/env node

import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { writeFileSync } from "node:fs";
import { pathToFileURL } from "node:url";


const DEFAULT_SITE_URL = "https://tripit.website-bench.com";
const FIXTURE_EMAIL = "traveler@example.com";
const FIXTURE_PASSWORD = "traveler-fixture-2027";

function required(environment, name) {
  const value = String(environment[name] || "").trim();
  if (!value) throw new Error(`${name} is required for the TripIt Stripe check`);
  return value;
}

function basicAuthorization(password) {
  return `Basic ${Buffer.from(`bench:${password}`).toString("base64")}`;
}

function responseCookies(response) {
  const values = typeof response.headers.getSetCookie === "function"
    ? response.headers.getSetCookie()
    : [response.headers.get("set-cookie")].filter(Boolean);
  return values
    .map((value) => String(value).split(";", 1)[0].trim())
    .filter((value) => value.includes("="))
    .join("; ");
}

export async function verifyTripitLiveStripe({
  environment = process.env,
  fetchImpl = fetch,
  evidenceWriter = (path, value) => writeFileSync(path, value, { encoding: "utf8" }),
} = {}) {
  const origin = String(environment.PUBLIC_CLONE_SITE_URL || DEFAULT_SITE_URL)
    .trim()
    .replace(/\/$/u, "");
  const expectedBuildId = required(environment, "DEPLOYMENT_BUILD_ID");
  const authorization = basicAuthorization(required(environment, "BASIC_AUTH_PASSWORD"));
  const stripeSecretKey = required(environment, "STRIPE_TEST_SECRET_KEY");
  const stripeWebhookSecret = required(environment, "STRIPE_TEST_WEBHOOK_SECRET");
  assert.match(
    stripeSecretKey,
    /^sk_test_[A-Za-z0-9_]{16,240}$/u,
    "STRIPE_TEST_SECRET_KEY is not a valid Stripe test key",
  );
  assert.match(
    stripeWebhookSecret,
    /^whsec_[A-Za-z0-9_]{16,240}$/u,
    "STRIPE_TEST_WEBHOOK_SECRET is not a valid Stripe test webhook secret",
  );

  const providerAccount = await fetchImpl("https://api.stripe.com/v1/account", {
    headers: { Authorization: `Bearer ${stripeSecretKey}` },
  });
  assert.equal(
    providerAccount.status,
    200,
    `Stripe test key validation returned HTTP ${providerAccount.status}`,
  );

  const smokeFlowId = `payflow_smoke_${expectedBuildId}`;
  const smokeFingerprint = createHash("sha256").update(smokeFlowId).digest("hex");
  const providerCheckout = await fetchImpl(
    "https://api.stripe.com/v1/checkout/sessions",
    {
      method: "POST",
      headers: {
        Authorization: `Bearer ${stripeSecretKey}`,
        "Content-Type": "application/x-www-form-urlencoded",
      },
      body: new URLSearchParams([
        ["mode", "payment"],
        ["payment_method_types[0]", "card"],
        ["payment_method_types[1]", "link"],
        ["customer_email", FIXTURE_EMAIL],
        ["success_url", `${origin}/pro/stripe-return?session_id={CHECKOUT_SESSION_ID}`],
        ["cancel_url", `${origin}/pro/stripe-return?cancelled=1&session_id={CHECKOUT_SESSION_ID}`],
        ["client_reference_id", smokeFlowId],
        ["expires_at", String(Math.floor(Date.now() / 1_000) + 31 * 60)],
        ["metadata[site_id]", "tripit"],
        ["metadata[flow_id]", smokeFlowId],
        ["metadata[owner]", "smoke-runner"],
        ["metadata[amount_minor]", "4900"],
        ["metadata[currency]", "USD"],
        ["metadata[fingerprint]", smokeFingerprint],
        ["metadata[is_simulation]", "true"],
        ["line_items[0][price_data][currency]", "usd"],
        ["line_items[0][price_data][unit_amount]", "4900"],
        ["line_items[0][price_data][product_data][name]", "TripIt Pro (annual)"],
        ["line_items[0][quantity]", "1"],
      ]).toString(),
    },
  );
  if (!providerCheckout.ok) {
    const payload = await providerCheckout.json().catch(() => null);
    const code = String(payload?.error?.code || "unknown").replace(/[^A-Za-z0-9_.-]/gu, "");
    const parameter = String(payload?.error?.param || "unknown").replace(/[^A-Za-z0-9_.\[\]-]/gu, "");
    throw new Error(
      `Stripe direct Checkout preflight returned HTTP ${providerCheckout.status} ` +
      `(code=${code || "unknown"}, param=${parameter || "unknown"})`,
    );
  }

  const health = await fetchImpl(`${origin}/healthz`, {
    headers: { "Cache-Control": "no-cache" },
  });
  assert.equal(health.status, 200, "TripIt health check is unavailable");
  assert.equal(
    health.headers.get("x-websitebench-build-id"),
    expectedBuildId,
    "public Worker build does not match the deployed revision",
  );

  const login = await fetchImpl(`${origin}/account/login`, {
    method: "POST",
    headers: {
      Authorization: authorization,
      "Content-Type": "application/x-www-form-urlencoded",
      Origin: origin,
    },
    body: new URLSearchParams({
      login_email_address: FIXTURE_EMAIL,
      login_password: FIXTURE_PASSWORD,
    }).toString(),
    redirect: "manual",
  });
  assert.equal(
    login.status,
    303,
    `TripIt fixture account sign-in returned HTTP ${login.status}`,
  );
  const cookie = responseCookies(login);
  assert.match(cookie, /__Host-websitebench-tripit-session=/u, "TripIt login omitted its session cookie");

  const upgrade = await fetchImpl(`${origin}/pro/upgrade`, {
    headers: { Authorization: authorization, Cookie: cookie },
    redirect: "manual",
  });
  assert.equal(upgrade.status, 200, "TripIt Pro upgrade page is unavailable");
  assert.equal(
    upgrade.headers.get("x-websitebench-payment-mode"),
    "stripe-test",
    "TripIt public deployment is not using Stripe test mode",
  );
  const markup = await upgrade.text();
  assert.match(markup, /Continue to Stripe test checkout/u, "TripIt omitted the Stripe checkout control");
  assert.doesNotMatch(markup, /sandbox-pro-approved/u, "TripIt exposed the local payment sandbox publicly");

  const checkout = await fetchImpl(`${origin}/pro/subscribe`, {
    method: "POST",
    headers: {
      Authorization: authorization,
      Cookie: cookie,
      Origin: origin,
    },
    redirect: "manual",
  });
  assert.equal(
    checkout.status,
    303,
    `TripIt Stripe checkout returned HTTP ${checkout.status} ` +
    `(gateway=${checkout.headers.get("x-websitebench-stripe-gateway-status") || "unknown"}, ` +
    `kind=${checkout.headers.get("x-websitebench-stripe-error-kind") || "unknown"})`,
  );
  const location = checkout.headers.get("location") || "";
  assert.match(
    location,
    /^https:\/\/checkout\.stripe\.com\//u,
    "TripIt did not create a hosted Stripe test Checkout Session",
  );

  const evidence = {
    schema_version: "websitebench.tripit-public-stripe-smoke.v1",
    site_id: "tripit",
    build_id: expectedBuildId,
    payment_adapter: "stripe-test",
    hosted_checkout: "passed",
    generated_at: new Date().toISOString(),
  };
  evidenceWriter(
    String(environment.TRIPIT_STRIPE_EVIDENCE_PATH || "tripit-stripe-smoke.json"),
    `${JSON.stringify(evidence, null, 2)}\n`,
  );
  return evidence;
}

async function main() {
  const result = await verifyTripitLiveStripe();
  process.stdout.write(
    `Verified TripIt build ${result.build_id}: hosted Stripe test checkout passed.\n`,
  );
}

if (import.meta.url === pathToFileURL(process.argv[1] || "").href) {
  main().catch((error) => {
    process.stderr.write(
      `TripIt live Stripe verification failed: ${error instanceof Error ? error.message : "unknown error"}\n`,
    );
    process.exitCode = 1;
  });
}
