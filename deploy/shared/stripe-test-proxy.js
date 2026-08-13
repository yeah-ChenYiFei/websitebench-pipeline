const STRIPE_INTERNAL_HOST = "stripe.internal";
const STRIPE_API_ORIGIN = "https://api.stripe.com";
const MAX_BODY_BYTES = 64 * 1024;
const WEBHOOK_TOLERANCE_SECONDS = 300;
const SESSION_PATTERN = /^cs_test_[A-Za-z0-9_]{8,240}$/u;
const SIGNATURE_PATTERN = /^[0-9a-f]{64}$/u;
const FLOW_PATTERN = /^[A-Za-z0-9_-]{24,160}$/u;
const OWNER_PATTERN = /^[A-Za-z0-9._:-]{8,240}$/u;
const FINGERPRINT_PATTERN = /^[0-9a-f]{64}$/u;
const IDEMPOTENCY_PATTERN = /^[A-Za-z0-9_-]{16,128}$/u;
const SITE_ID_PATTERN = /^[a-z0-9]+(?:-[a-z0-9]+)*$/u;
const CURRENCY_PATTERN = /^[A-Z]{3}$/u;

function proxyError(status, message) {
  return new Response(JSON.stringify({ error: message }), {
    status,
    headers: {
      "Cache-Control": "no-store",
      "Content-Type": "application/json; charset=utf-8",
    },
  });
}

function frozenConfig(raw) {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) throw new TypeError("stripe-test config must be an object");
  const keys = Object.keys(raw).sort();
  const expected = ["currency", "maxLineItems", "publicOrigin", "returnPath", "siteId", "webhookPath"];
  if (JSON.stringify(keys) !== JSON.stringify(expected)) throw new TypeError("stripe-test config has missing or unknown fields");
  let origin;
  try {
    const parsed = new URL(raw.publicOrigin);
    if (parsed.protocol !== "https:" || parsed.username || parsed.password || parsed.port || parsed.pathname !== "/" || parsed.search || parsed.hash) throw new TypeError();
    origin = parsed.origin;
  } catch {
    throw new TypeError("stripe-test publicOrigin must be an https origin");
  }
  for (const [label, value] of [["returnPath", raw.returnPath], ["webhookPath", raw.webhookPath]]) {
    if (typeof value !== "string" || !value.startsWith("/") || value.startsWith("//") || value.includes("\\") || /[?#\r\n]/u.test(value) || value.split("/").includes("..")) {
      throw new TypeError(`stripe-test ${label} must be a safe local path`);
    }
  }
  if (!SITE_ID_PATTERN.test(raw.siteId)) throw new TypeError("stripe-test siteId is invalid");
  if (!CURRENCY_PATTERN.test(raw.currency)) throw new TypeError("stripe-test currency is invalid");
  if (!Number.isInteger(raw.maxLineItems) || raw.maxLineItems < 1 || raw.maxLineItems > 100) throw new TypeError("stripe-test maxLineItems is invalid");
  return Object.freeze({
    siteId: raw.siteId,
    publicOrigin: origin,
    returnPath: raw.returnPath,
    webhookPath: raw.webhookPath,
    currency: raw.currency,
    maxLineItems: raw.maxLineItems,
  });
}

function secretConfigurationIsValid(env) {
  return (
    /^sk_test_[A-Za-z0-9_]{16,240}$/u.test(String(env.STRIPE_TEST_SECRET_KEY || "")) &&
    /^whsec_[A-Za-z0-9_]{16,240}$/u.test(String(env.STRIPE_TEST_WEBHOOK_SECRET || ""))
  );
}

function validReturnUrl(rawValue, cancelled, config) {
  try {
    const url = new URL(rawValue);
    if (
      url.origin !== config.publicOrigin ||
      url.pathname !== config.returnPath ||
      url.username ||
      url.password ||
      url.hash ||
      url.searchParams.get("session_id") !== "{CHECKOUT_SESSION_ID}"
    ) return false;
    const expected = cancelled ? new Set(["cancelled", "session_id"]) : new Set(["session_id"]);
    return (
      ![...url.searchParams.keys()].some((key) => !expected.has(key)) &&
      (!cancelled || url.searchParams.get("cancelled") === "1")
    );
  } catch {
    return false;
  }
}

function validCheckoutFields(parameters, nowSeconds, config) {
  const entries = [...parameters.entries()];
  if (
    entries.length < 19 ||
    entries.length > 19 + config.maxLineItems * 4 ||
    new Set(entries.map(([key]) => key)).size !== entries.length
  ) return false;
  const allowedBase = new Set([
    "mode",
    "payment_method_types[0]",
    "payment_method_types[1]",
    "customer_email",
    "success_url",
    "cancel_url",
    "client_reference_id",
    "expires_at",
    "metadata[site_id]",
    "metadata[flow_id]",
    "metadata[owner]",
    "metadata[amount_minor]",
    "metadata[currency]",
    "metadata[fingerprint]",
    "metadata[is_simulation]",
  ]);
  const linePattern = /^line_items\[([0-9]{1,3})\]\[(price_data\]\[(?:currency|unit_amount|product_data\]\[name)|quantity)\]$/u;
  const lineFields = new Map();
  for (const [key, value] of entries) {
    if (allowedBase.has(key)) {
      if (value.length > 2048) return false;
      continue;
    }
    const match = linePattern.exec(key);
    if (!match) return false;
    const index = Number(match[1]);
    if (!Number.isInteger(index) || index < 0 || index >= config.maxLineItems) return false;
    const values = lineFields.get(index) || new Map();
    values.set(match[2], value);
    lineFields.set(index, values);
  }
  const flowId = parameters.get("client_reference_id") || "";
  const expiresAt = Number(parameters.get("expires_at"));
  if (
    parameters.get("mode") !== "payment" ||
    parameters.get("payment_method_types[0]") !== "card" ||
    parameters.get("payment_method_types[1]") !== "link" ||
    !/^[^@\s]{1,200}@[^@\s]{1,200}$/u.test(parameters.get("customer_email") || "") ||
    !validReturnUrl(parameters.get("success_url") || "", false, config) ||
    !validReturnUrl(parameters.get("cancel_url") || "", true, config) ||
    !FLOW_PATTERN.test(flowId) ||
    parameters.get("metadata[site_id]") !== config.siteId ||
    parameters.get("metadata[flow_id]") !== flowId ||
    !OWNER_PATTERN.test(parameters.get("metadata[owner]") || "") ||
    parameters.get("metadata[currency]") !== config.currency ||
    !FINGERPRINT_PATTERN.test(parameters.get("metadata[fingerprint]") || "") ||
    parameters.get("metadata[is_simulation]") !== "true" ||
    !Number.isInteger(expiresAt) ||
    expiresAt < nowSeconds + 20 * 60 ||
    expiresAt > nowSeconds + 35 * 60 ||
    lineFields.size < 1 ||
    lineFields.size > config.maxLineItems
  ) return false;
  const indexes = [...lineFields.keys()].sort((left, right) => left - right);
  if (indexes.some((index, position) => index !== position)) return false;
  let total = 0;
  for (const index of indexes) {
    const fields = lineFields.get(index);
    if (
      fields?.size !== 4 ||
      fields.get("price_data][currency") !== config.currency.toLowerCase() ||
      !/^(0|[1-9][0-9]{0,10})$/u.test(fields.get("price_data][unit_amount") || "") ||
      !/^[1-9][0-9]?$/u.test(fields.get("quantity") || "")
    ) return false;
    const quantity = Number(fields.get("quantity"));
    const unitAmount = Number(fields.get("price_data][unit_amount"));
    const name = fields.get("price_data][product_data][name") || "";
    if (quantity > 30 || name.length < 1 || name.length > 240 || /[\u0000-\u001f\u007f]/u.test(name)) return false;
    total += quantity * unitAmount;
    if (!Number.isSafeInteger(total)) return false;
  }
  return parameters.get("metadata[amount_minor]") === String(total);
}

async function checkoutCreateRequestIsValid(request, nowSeconds, config) {
  if (
    request.method !== "POST" ||
    !request.headers.get("Content-Type")?.toLowerCase().startsWith("application/x-www-form-urlencoded") ||
    request.headers.has("Authorization") ||
    !IDEMPOTENCY_PATTERN.test(request.headers.get("Idempotency-Key") || "")
  ) return null;
  const declared = Number(request.headers.get("Content-Length") || "0");
  if (Number.isFinite(declared) && declared > MAX_BODY_BYTES) return null;
  const body = await request.text();
  if (!body || new TextEncoder().encode(body).length > MAX_BODY_BYTES) return null;
  return validCheckoutFields(new URLSearchParams(body), nowSeconds, config) ? body : null;
}

function providerResponse(response) {
  if (!response.ok) return proxyError(502, "stripe_request_failed");
  return new Response(response.body, {
    status: response.status,
    headers: {
      "Cache-Control": "no-store",
      "Content-Type": "application/json; charset=utf-8",
    },
  });
}

function parseStripeSignature(header) {
  if (!header || header.length > 4096) return null;
  const timestamps = [];
  const signatures = [];
  for (const component of header.split(",")) {
    const [name, value, ...rest] = component.trim().split("=");
    if (rest.length) continue;
    if (name === "t" && /^[0-9]{1,16}$/u.test(value || "")) timestamps.push(Number(value));
    else if (name === "v1" && SIGNATURE_PATTERN.test(value || "")) signatures.push(value);
  }
  return timestamps.length === 1 && signatures.length ? { timestamp: timestamps[0], signatures } : null;
}

function constantTimeHexEqual(left, right) {
  if (left.length !== right.length) return false;
  let mismatch = 0;
  for (let index = 0; index < left.length; index += 1) mismatch |= left.charCodeAt(index) ^ right.charCodeAt(index);
  return mismatch === 0;
}

function webhookSessionMatches(body, config) {
  let event;
  try {
    event = JSON.parse(new TextDecoder().decode(body));
  } catch {
    return false;
  }
  const session = event?.data?.object;
  const metadata = session?.metadata;
  if (
    !/^evt_[A-Za-z0-9_]{8,240}$/u.test(String(event?.id || "")) ||
    !["checkout.session.completed", "checkout.session.expired"].includes(event?.type) ||
    !SESSION_PATTERN.test(String(session?.id || "")) ||
    metadata?.site_id !== config.siteId ||
    !FLOW_PATTERN.test(String(metadata?.flow_id || "")) ||
    !OWNER_PATTERN.test(String(metadata?.owner || "")) ||
    metadata?.currency !== config.currency ||
    !FINGERPRINT_PATTERN.test(String(metadata?.fingerprint || "")) ||
    metadata?.is_simulation !== "true" ||
    !/^(0|[1-9][0-9]{0,10})$/u.test(String(metadata?.amount_minor || "")) ||
    String(session?.currency || "").toUpperCase() !== config.currency ||
    Number(session?.amount_total) !== Number(metadata.amount_minor)
  ) return false;
  return true;
}

export function createStripeTestProxy(rawConfig) {
  const config = frozenConfig(rawConfig);
  function isStripeWebhookRequest(request) {
    const url = new URL(request.url);
    return request.method === "POST" && url.pathname === config.webhookPath && !url.search;
  }
  async function stripeOutbound(request, env) {
    const url = new URL(request.url);
    const configured = secretConfigurationIsValid(env);
    if (
      url.protocol !== "http:" ||
      url.hostname !== STRIPE_INTERNAL_HOST ||
      url.port ||
      url.username ||
      url.password ||
      url.search ||
      url.hash ||
      !configured
    ) return proxyError(configured ? 403 : 503, configured ? "stripe_request_denied" : "stripe_not_configured");

    let body;
    const headers = {
      Accept: "application/json",
      Authorization: `Bearer ${env.STRIPE_TEST_SECRET_KEY}`,
      "User-Agent": `WebsiteBench-${config.siteId}-Stripe-Test-Proxy/1.0`,
    };
    if (url.pathname === "/v1/checkout/sessions") {
      body = await checkoutCreateRequestIsValid(request, Math.floor(Date.now() / 1000), config);
      if (body === null) return proxyError(400, "invalid_stripe_checkout_request");
      headers["Content-Type"] = "application/x-www-form-urlencoded";
      headers["Idempotency-Key"] = request.headers.get("Idempotency-Key");
    } else {
      const retrieve = /^\/v1\/checkout\/sessions\/([^/]+)$/u.exec(url.pathname);
      const expire = /^\/v1\/checkout\/sessions\/([^/]+)\/expire$/u.exec(url.pathname);
      if (retrieve && request.method === "GET" && SESSION_PATTERN.test(retrieve[1]) && !request.headers.has("Authorization")) body = undefined;
      else if (expire && request.method === "POST" && SESSION_PATTERN.test(expire[1]) && !request.headers.has("Authorization") && (await request.text()) === "") {
        body = "";
        headers["Content-Type"] = "application/x-www-form-urlencoded";
      } else return proxyError(403, "stripe_request_denied");
    }
    return providerResponse(await fetch(`${STRIPE_API_ORIGIN}${url.pathname}`, {
      method: request.method,
      headers,
      body,
    }));
  }
  async function verifyStripeWebhook(request, webhookSecret, nowSeconds = Math.floor(Date.now() / 1000)) {
    if (!isStripeWebhookRequest(request) || !/^whsec_[A-Za-z0-9_]{16,240}$/u.test(String(webhookSecret || ""))) return null;
    const declared = Number(request.headers.get("Content-Length") || "0");
    if (Number.isFinite(declared) && declared > MAX_BODY_BYTES) return null;
    const signature = parseStripeSignature(request.headers.get("Stripe-Signature"));
    if (!signature || Math.abs(nowSeconds - signature.timestamp) > WEBHOOK_TOLERANCE_SECONDS) return null;
    const body = new Uint8Array(await request.clone().arrayBuffer());
    if (!body.length || body.length > MAX_BODY_BYTES) return null;
    const prefix = new TextEncoder().encode(`${signature.timestamp}.`);
    const signed = new Uint8Array(prefix.length + body.length);
    signed.set(prefix);
    signed.set(body, prefix.length);
    const key = await crypto.subtle.importKey("raw", new TextEncoder().encode(webhookSecret), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
    const digest = new Uint8Array(await crypto.subtle.sign("HMAC", key, signed));
    const expected = [...digest].map((value) => value.toString(16).padStart(2, "0")).join("");
    if (!signature.signatures.some((candidate) => constantTimeHexEqual(expected, candidate))) return null;
    return webhookSessionMatches(body, config) ? body : null;
  }
  return Object.freeze({
    config,
    isStripeWebhookRequest,
    stripeConfigurationIsValid: secretConfigurationIsValid,
    stripeOutbound,
    verifyStripeWebhook,
  });
}
