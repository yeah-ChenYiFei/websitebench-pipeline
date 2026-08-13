import { timingSafeEqual } from "node:crypto";
import { createServer } from "node:http";

import { createPublicCloneAuthProxy } from "./shared/public-clone-auth-proxy.js";
import { createStripeTestProxy } from "./shared/stripe-test-proxy.js";

const siteId = String(process.env.SITE_ID || "").trim();
const siteLabel = String(process.env.SITE_LABEL || "").trim();
const publicHost = String(process.env.PUBLIC_HOST || "").trim().toLowerCase();
const port = Number(process.env.EFFECTS_PORT || "8080");
if (
  !/^[a-z0-9]+(?:-[a-z0-9]+)*$/u.test(siteId) ||
  !siteLabel ||
  !/^(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,63}$/u.test(publicHost) ||
  !Number.isInteger(port) ||
  port < 1024 ||
  port > 65535
) throw new Error("effects gateway identity or listener is invalid");

let registrationTemplate = null;
if (process.env.PUBLIC_CLONE_AUTH_MAIL_TEMPLATE) {
  try {
    registrationTemplate = JSON.parse(process.env.PUBLIC_CLONE_AUTH_MAIL_TEMPLATE);
  } catch {
    throw new Error("effects gateway registration mail template is invalid");
  }
}
let mailTemplates = null;
if (process.env.MAIL_TEMPLATES) {
  try {
    mailTemplates = JSON.parse(process.env.MAIL_TEMPLATES);
  } catch {
    throw new Error("effects gateway business mail templates are invalid");
  }
}
const senderDisplayName = String(process.env.MAIL_SENDER_DISPLAY_NAME || "").trim() || null;
const publicAuth = createPublicCloneAuthProxy({
  siteId,
  siteLabel,
  registrationTemplate,
  mailTemplates,
  senderDisplayName,
});
const stripe = process.env.PAYMENT_ADAPTER === "stripe-test"
  ? createStripeTestProxy({
      siteId,
      publicOrigin: String(process.env.STRIPE_PUBLIC_ORIGIN || ""),
      returnPath: String(process.env.STRIPE_RETURN_PATH || ""),
      webhookPath: String(process.env.STRIPE_WEBHOOK_PATH || ""),
      currency: String(process.env.PAYMENT_CURRENCY || ""),
      maxLineItems: Number(process.env.STRIPE_MAX_LINE_ITEMS || "0"),
    })
  : null;

function authProviderEnv() {
  const senderEnv = String(process.env.MAIL_SENDER_ADDRESS_ENV || "");
  return {
    ...process.env,
    RESEND_FROM_EMAIL: process.env[senderEnv],
  };
}

function stripeProviderEnv() {
  return {
    ...process.env,
    STRIPE_TEST_SECRET_KEY:
      process.env[String(process.env.STRIPE_SECRET_KEY_ENV || "")],
    STRIPE_TEST_WEBHOOK_SECRET:
      process.env[String(process.env.STRIPE_WEBHOOK_SECRET_ENV || "")],
  };
}

function authorized(header) {
  const expected = String(process.env.BASIC_AUTH_PASSWORD || "");
  if (!expected || !String(header || "").startsWith("Basic ")) return false;
  let decoded;
  try {
    decoded = Buffer.from(String(header).slice(6).trim(), "base64").toString("utf8");
  } catch {
    return false;
  }
  const separator = decoded.indexOf(":");
  if (separator < 0 || decoded.slice(0, separator) !== "bench") return false;
  const actualBytes = Buffer.from(decoded.slice(separator + 1));
  const expectedBytes = Buffer.from(expected);
  return actualBytes.length === expectedBytes.length && timingSafeEqual(actualBytes, expectedBytes);
}

function internalAuthorized(header) {
  const expected = Buffer.from(String(process.env.EFFECTS_INTERNAL_TOKEN || ""));
  const actual = Buffer.from(String(header || ""));
  return (
    expected.length >= 24 &&
    actual.length === expected.length &&
    timingSafeEqual(actual, expected)
  );
}

function internalEffectsHeader(headers) {
  const canonical = headers["x-websitebench-effects-token"];
  if (canonical !== undefined) return canonical;
  if (process.env.WEBSITEBENCH_LEGACY_CLAW_RUNTIME === "1") {
    return headers["x-clawbench-effects-token"];
  }
  return undefined;
}

async function readBody(request) {
  if (["GET", "HEAD"].includes(request.method || "")) return undefined;
  const chunks = [];
  let length = 0;
  for await (const chunk of request) {
    length += chunk.length;
    if (length > 256 * 1024) throw new Error("request body is too large");
    chunks.push(chunk);
  }
  return Buffer.concat(chunks);
}

async function toRequest(request, forcedHost = null) {
  const body = await readBody(request);
  const headers = new Headers();
  for (const [name, value] of Object.entries(request.headers)) {
    if (value !== undefined && !["connection", "host", "transfer-encoding"].includes(name.toLowerCase())) {
      headers.set(name, Array.isArray(value) ? value.join(",") : value);
    }
  }
  const host = forcedHost || String(request.headers.host || "");
  return new Request(`http://${host}${request.url || "/"}`, {
    method: request.method,
    headers,
    body,
    duplex: body === undefined ? undefined : "half",
  });
}

async function send(response, outgoing) {
  const headers = {};
  for (const [name, value] of response.headers) {
    if (!["connection", "content-length", "transfer-encoding"].includes(name.toLowerCase())) headers[name] = value;
  }
  const body = Buffer.from(await response.arrayBuffer());
  outgoing.writeHead(response.status, { ...headers, "content-length": String(body.length) });
  outgoing.end(body);
}

function noStore(status, body) {
  return new Response(body, {
    status,
    headers: {
      "Cache-Control": "private, no-store",
      "Content-Type": "text/plain; charset=utf-8",
      "X-Content-Type-Options": "nosniff",
      "X-Robots-Tag": "noindex, nofollow, noarchive",
    },
  });
}

async function forwardToApp(source, { stripeVerified = false } = {}) {
  const headers = new Headers(source.headers);
  for (const name of ["authorization", "forwarded", "x-forwarded-for", "x-forwarded-host", "x-forwarded-proto", "x-websitebench-stripe-verified", "x-clawbench-stripe-verified"]) headers.delete(name);
  headers.set("X-Forwarded-Host", publicHost);
  headers.set("X-Forwarded-Proto", "https");
  if (stripeVerified) headers.set("X-WebsiteBench-Stripe-Verified", "1");
  return fetch(`http://app:10000${new URL(source.url).pathname}${new URL(source.url).search}`, {
    method: source.method,
    headers,
    body: ["GET", "HEAD"].includes(source.method) ? undefined : await source.arrayBuffer(),
  });
}

const server = createServer(async (request, response) => {
  try {
    const incomingHost = String(request.headers.host || "").split(":", 1)[0].toLowerCase();
    const path = new URL(request.url || "/", "http://placeholder").pathname;
    if (path === "/healthz" && ["127.0.0.1", "localhost"].includes(incomingHost)) {
      await send(new Response(JSON.stringify({ ok: true, site_id: siteId }), {
        headers: { "Content-Type": "application/json; charset=utf-8" },
      }), response);
      return;
    }
    if (incomingHost === "redis.internal") {
      if (!internalAuthorized(internalEffectsHeader(request.headers))) {
        await send(noStore(403, "Forbidden"), response);
        return;
      }
      await send(await publicAuth.redisOutbound(await toRequest(request, "redis.internal"), authProviderEnv()), response);
      return;
    }
    if (incomingHost === "resend.internal") {
      if (!internalAuthorized(internalEffectsHeader(request.headers))) {
        await send(noStore(403, "Forbidden"), response);
        return;
      }
      await send(await publicAuth.resendOutbound(await toRequest(request, "resend.internal"), authProviderEnv()), response);
      return;
    }
    if (incomingHost === "stripe.internal") {
      if (!internalAuthorized(internalEffectsHeader(request.headers))) {
        await send(noStore(403, "Forbidden"), response);
        return;
      }
      await send(stripe ? await stripe.stripeOutbound(await toRequest(request, "stripe.internal"), stripeProviderEnv()) : noStore(404, "Not Found"), response);
      return;
    }
    if (incomingHost !== publicHost) {
      await send(noStore(404, "Not Found"), response);
      return;
    }
    const browserRequest = await toRequest(request);
    const stripeRequest = stripe && stripe.isStripeWebhookRequest(browserRequest);
    if (stripeRequest) {
      const verified = await stripe.verifyStripeWebhook(
        browserRequest,
        stripeProviderEnv().STRIPE_TEST_WEBHOOK_SECRET,
      );
      await send(verified ? await forwardToApp(browserRequest, { stripeVerified: true }) : noStore(400, "Invalid Stripe webhook"), response);
      return;
    }
    if (!authorized(request.headers.authorization)) {
      await send(new Response("Authentication required", {
        status: 401,
        headers: {
          "Cache-Control": "private, no-store",
          "WWW-Authenticate": `Basic realm="${siteLabel}", charset="UTF-8"`,
        },
      }), response);
      return;
    }
    await send(await forwardToApp(browserRequest), response);
  } catch {
    await send(noStore(500, "Effects gateway request failed"), response);
  }
});

server.listen(port, "0.0.0.0");
