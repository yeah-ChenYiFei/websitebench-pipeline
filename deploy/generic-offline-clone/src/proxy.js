import { createPublicCloneAuthProxy } from "../../shared/public-clone-auth-proxy.js";
import { createStripeTestProxy } from "../../shared/stripe-test-proxy.js";

const proxies = new Map();
function proxyFor(env) {
  const siteId = String(env.SITE_ID || "").trim();
  const siteLabel = String(env.SITE_LABEL || "").trim();
  if (!/^[a-z0-9]+(?:-[a-z0-9]+)*$/u.test(siteId) || !siteLabel) throw new TypeError("invalid deployment identity");
  let registrationTemplate = null;
  if (env.MAIL_REGISTRATION_TEMPLATE) {
    try { registrationTemplate = JSON.parse(env.MAIL_REGISTRATION_TEMPLATE); } catch { throw new TypeError("invalid registration mail template"); }
  }
  let mailTemplates = null;
  if (env.MAIL_TEMPLATES) {
    try { mailTemplates = JSON.parse(env.MAIL_TEMPLATES); } catch { throw new TypeError("invalid business mail templates"); }
  }
  const senderDisplayName = String(env.MAIL_SENDER_DISPLAY_NAME || "").trim() || null;
  const key = `${siteId}\0${siteLabel}\0${JSON.stringify(registrationTemplate)}\0${JSON.stringify(mailTemplates)}\0${senderDisplayName || ""}`;
  if (!proxies.has(key)) proxies.set(key, createPublicCloneAuthProxy({ siteId, siteLabel, registrationTemplate, mailTemplates, senderDisplayName }));
  return proxies.get(key);
}

export async function redisOutbound(request, env) { return proxyFor(env).redisOutbound(request, env); }
export async function resendOutbound(request, env) {
  const senderEnv = String(env.MAIL_SENDER_ADDRESS_ENV || "");
  return proxyFor(env).resendOutbound(request, {
    ...env,
    RESEND_FROM_EMAIL: env[senderEnv],
  });
}

const stripeProxies = new Map();
function stripeProxyFor(env) {
  if (env.PAYMENT_ADAPTER !== "stripe-test") throw new TypeError("stripe-test is not enabled");
  const config = {
    siteId: String(env.SITE_ID || ""),
    publicOrigin: String(env.STRIPE_PUBLIC_ORIGIN || ""),
    returnPath: String(env.STRIPE_RETURN_PATH || ""),
    webhookPath: String(env.STRIPE_WEBHOOK_PATH || ""),
    currency: String(env.PAYMENT_CURRENCY || ""),
    maxLineItems: Number(env.STRIPE_MAX_LINE_ITEMS || "0"),
  };
  const key = JSON.stringify(config);
  if (!stripeProxies.has(key)) stripeProxies.set(key, createStripeTestProxy(config));
  return stripeProxies.get(key);
}

function stripeProviderEnv(env) {
  return {
    ...env,
    STRIPE_TEST_SECRET_KEY: env[String(env.STRIPE_SECRET_KEY_ENV || "")],
    STRIPE_TEST_WEBHOOK_SECRET: env[String(env.STRIPE_WEBHOOK_SECRET_ENV || "")],
  };
}

export async function stripeOutbound(request, env) {
  return stripeProxyFor(env).stripeOutbound(request, stripeProviderEnv(env));
}
export function isStripeWebhookRequest(request, env) {
  return env.PAYMENT_ADAPTER === "stripe-test" && stripeProxyFor(env).isStripeWebhookRequest(request);
}
export async function verifyStripeWebhook(request, env) {
  return stripeProxyFor(env).verifyStripeWebhook(
    request,
    stripeProviderEnv(env).STRIPE_TEST_WEBHOOK_SECRET,
  );
}

export function buildContainerRequest(request, {
  registrationSmokeVerified = false,
  stripeWebhookVerified = false,
} = {}) {
  const url = new URL(request.url);
  const headers = new Headers(request.headers);
  const clientAddress = headers.get("CF-Connecting-IP") || "unknown";
  for (const name of ["Authorization", "CF-Connecting-IP", "Forwarded", "True-Client-IP", "X-Forwarded-For", "X-Forwarded-Host", "X-Forwarded-Proto", "X-Real-IP", "X-WebsiteBench-Client-IP", "X-WebsiteBench-Turnstile-Verified", "X-WebsiteBench-Stripe-Verified", "X-WebsiteBench-Registration-Smoke-Secret", "X-WebsiteBench-Registration-Smoke-Verified", "X-ClawBench-Client-IP", "X-ClawBench-Stripe-Verified"]) headers.delete(name);
  headers.set("X-Forwarded-Host", url.host);
  headers.set("X-Forwarded-Proto", url.protocol.replace(":", ""));
  headers.set("X-WebsiteBench-Client-IP", clientAddress);
  if (stripeWebhookVerified) headers.set("X-WebsiteBench-Stripe-Verified", "1");
  if (registrationSmokeVerified) headers.set("X-WebsiteBench-Registration-Smoke-Verified", "1");
  return new Request(request, { headers });
}

export function securedResponse(response, env) {
  const headers = new Headers(response.headers);
  headers.set("Cache-Control", "private, no-store");
  headers.set("Content-Security-Policy", "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline' https://challenges.cloudflare.com; connect-src 'self' https://challenges.cloudflare.com; frame-src https://challenges.cloudflare.com; form-action 'self'; frame-ancestors 'none'; base-uri 'self'");
  headers.set("Referrer-Policy", "same-origin");
  headers.set("Strict-Transport-Security", "max-age=31536000");
  headers.set("X-Content-Type-Options", "nosniff");
  headers.set("X-Frame-Options", "DENY");
  headers.set("X-Robots-Tag", "noindex, nofollow, noarchive");
  if (env.CF_VERSION_METADATA?.id) headers.set("X-WebsiteBench-Worker-Version", env.CF_VERSION_METADATA.id);
  const buildId = String(env.DEPLOYMENT_BUILD_ID || "");
  if (/^[A-Za-z0-9._:@+-]{1,160}$/u.test(buildId)) {
    headers.set("X-WebsiteBench-Build-ID", buildId);
  }
  if (["local-sandbox", "stripe-test"].includes(env.PAYMENT_ADAPTER)) {
    headers.set("X-WebsiteBench-Payment-Mode", env.PAYMENT_ADAPTER);
  }
  return new Response(response.body, { status: response.status, statusText: response.statusText, headers });
}
