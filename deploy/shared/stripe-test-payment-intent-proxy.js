const STRIPE_INTERNAL_HOST = "stripe.internal";
const STRIPE_API_ORIGIN = "https://api.stripe.com";
const MAX_BODY_BYTES = 16 * 1024;
const PAYMENT_INTENT_PATTERN = /^pi_[A-Za-z0-9_]{8,240}$/u;
const IDEMPOTENCY_PATTERN = /^[A-Za-z0-9_-]{16,128}$/u;
const USER_PATTERN = /^usr_[a-z0-9]+_[a-z0-9]{4,32}$/u;

function proxyError(status, message) {
  return new Response(JSON.stringify({ error: message }), {
    status,
    headers: {
      "Cache-Control": "no-store",
      "Content-Type": "application/json; charset=utf-8",
    },
  });
}

function secretConfigurationIsValid(env) {
  return /^sk_test_[A-Za-z0-9_]{16,240}$/u.test(
    String(env?.STRIPE_TEST_SECRET_KEY || ""),
  );
}

function validCreateBody(body) {
  const parameters = new URLSearchParams(body);
  const entries = [...parameters.entries()];
  const expectedKeys = [
    "amount",
    "confirm",
    "currency",
    "description",
    "metadata[source]",
    "metadata[testMode]",
    "metadata[userId]",
    "payment_method",
    "payment_method_types[0]",
  ].sort();
  if (
    entries.length !== expectedKeys.length ||
    JSON.stringify(entries.map(([key]) => key).sort()) !== JSON.stringify(expectedKeys)
  ) return false;

  const amount = Number(parameters.get("amount"));
  return (
    Number.isSafeInteger(amount) &&
    amount >= 50 &&
    amount <= 1_000_000 &&
    parameters.get("currency") === "usd" &&
    parameters.get("confirm") === "true" &&
    parameters.get("payment_method") === "pm_card_visa" &&
    parameters.get("payment_method_types[0]") === "card" &&
    parameters.get("description") === "Uber Eats replica QA order" &&
    parameters.get("metadata[source]") === "uber-eats-local-replica" &&
    parameters.get("metadata[testMode]") === "true" &&
    USER_PATTERN.test(parameters.get("metadata[userId]") || "")
  );
}

async function validCreateRequest(request) {
  if (
    request.method !== "POST" ||
    request.headers.has("Authorization") ||
    !request.headers.get("Content-Type")?.toLowerCase().startsWith(
      "application/x-www-form-urlencoded",
    ) ||
    !IDEMPOTENCY_PATTERN.test(request.headers.get("Idempotency-Key") || "")
  ) return null;

  const declared = Number(request.headers.get("Content-Length") || "0");
  if (Number.isFinite(declared) && declared > MAX_BODY_BYTES) return null;
  const body = await request.text();
  if (!body || new TextEncoder().encode(body).length > MAX_BODY_BYTES) return null;
  return validCreateBody(body) ? body : null;
}

async function validatedProviderResponse(response, operation) {
  const payload = await response.json().catch(() => null);
  if (!response.ok || !payload || typeof payload !== "object") {
    return proxyError(502, "stripe_request_failed");
  }
  if (
    payload.livemode !== false ||
    !PAYMENT_INTENT_PATTERN.test(String(payload.id || "")) ||
    (operation === "create" && payload.status !== "succeeded")
  ) return proxyError(502, "stripe_test_response_rejected");

  return new Response(JSON.stringify(payload), {
    status: 200,
    headers: {
      "Cache-Control": "no-store",
      "Content-Type": "application/json; charset=utf-8",
    },
  });
}

export function stripeTestPaymentIntentConfigurationIsValid(env) {
  return secretConfigurationIsValid(env);
}

export async function stripeTestPaymentIntentOutbound(request, env) {
  if (env?.SITE_ID !== "ubereats" || env?.SITE_LABEL !== "Uber Eats Clone") {
    return proxyError(403, "stripe_request_denied");
  }

  const configured = secretConfigurationIsValid(env);
  if (!configured) return proxyError(503, "stripe_not_configured");

  const url = new URL(request.url);
  if (
    url.protocol !== "http:" ||
    url.hostname !== STRIPE_INTERNAL_HOST ||
    url.port ||
    url.username ||
    url.password ||
    url.search ||
    url.hash
  ) return proxyError(403, "stripe_request_denied");

  let body;
  let operation;
  const headers = {
    Accept: "application/json",
    Authorization: `Bearer ${env.STRIPE_TEST_SECRET_KEY}`,
    "User-Agent": "WebsiteBench-ubereats-Stripe-Test-Proxy/1.0",
  };

  if (url.pathname === "/v1/payment_intents") {
    body = await validCreateRequest(request);
    if (body === null) return proxyError(400, "invalid_stripe_payment_intent_request");
    operation = "create";
    headers["Content-Type"] = "application/x-www-form-urlencoded";
    headers["Idempotency-Key"] = request.headers.get("Idempotency-Key");
  } else {
    const retrieve = /^\/v1\/payment_intents\/([^/]+)$/u.exec(url.pathname);
    if (
      !retrieve ||
      request.method !== "GET" ||
      request.headers.has("Authorization") ||
      !PAYMENT_INTENT_PATTERN.test(retrieve[1])
    ) return proxyError(403, "stripe_request_denied");
    body = undefined;
    operation = "retrieve";
  }

  const response = await fetch(`${STRIPE_API_ORIGIN}${url.pathname}`, {
    method: request.method,
    headers,
    body,
  });
  return validatedProviderResponse(response, operation);
}
