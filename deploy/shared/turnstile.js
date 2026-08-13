/**
 * Cloudflare Turnstile boundary for public clone email entry points.
 *
 * The container never receives the Turnstile secret or the one-time token.
 * A verified request is reconstructed with the clone's strict pre-existing
 * payload so application handlers continue to receive only `{ email }`.
 */

const TURNSTILE_VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify";
const EMAIL_ENTRY_PATHS = new Set(["/api/auth/send-code"]);

function errorResponse(status, error) {
  return new Response(JSON.stringify({ ok: false, error }), {
    status,
    headers: {
      "Cache-Control": "no-store",
      "Content-Type": "application/json; charset=utf-8",
    },
  });
}

export function isTurnstileEmailEntry(request) {
  const url = new URL(request.url);
  return request.method === "POST" && EMAIL_ENTRY_PATHS.has(url.pathname);
}

/**
 * Turnstile is on unless a deployment opts out with AUTH_REQUIRE_TURNSTILE
 * exactly "false", the same switch the eight-site package already pins. Only an
 * explicit opt-out disables it: a missing or malformed value keeps the boundary
 * on, so losing the secret still fails closed rather than quietly admitting
 * unverified requests.
 */
export function turnstileRequired(env) {
  return String(env.AUTH_REQUIRE_TURNSTILE ?? "").trim().toLowerCase() !== "false";
}

export async function verifyTurnstileEmailEntry(request, env) {
  if (!isTurnstileEmailEntry(request)) return { request };
  // An opted-out deployment injects no widget, so the browser posts the plain
  // { email } body these handlers already accept and nothing else changes.
  if (!turnstileRequired(env)) return { request };
  const secret = String(env.TURNSTILE_SECRET_KEY || "").trim();
  if (!secret) return { response: errorResponse(503, "verification_unavailable") };

  const type = request.headers.get("Content-Type") || "";
  if (!type.toLowerCase().startsWith("application/json")) {
    return { response: errorResponse(400, "invalid_request") };
  }
  let payload;
  try {
    const body = await request.text();
    if (!body || new TextEncoder().encode(body).length > 4096) {
      return { response: errorResponse(400, "invalid_request") };
    }
    payload = JSON.parse(body);
  } catch {
    return { response: errorResponse(400, "invalid_request") };
  }
  if (
    !payload ||
    typeof payload !== "object" ||
    Array.isArray(payload) ||
    Object.keys(payload).sort().join(",") !== "cf-turnstile-response,email" ||
    typeof payload.email !== "string" ||
    typeof payload["cf-turnstile-response"] !== "string" ||
    !payload["cf-turnstile-response"].trim() ||
    payload["cf-turnstile-response"].length > 4096
  ) {
    return { response: errorResponse(400, "invalid_request") };
  }

  let verified;
  try {
    const response = await fetch(TURNSTILE_VERIFY_URL, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({
        secret,
        response: payload["cf-turnstile-response"],
        remoteip: request.headers.get("CF-Connecting-IP") || "",
      }),
    });
    verified = response.ok && (await response.json()).success === true;
  } catch {
    return { response: errorResponse(503, "verification_unavailable") };
  }
  if (!verified) return { response: errorResponse(403, "verification_failed") };

  const headers = new Headers(request.headers);
  headers.delete("Content-Length");
  headers.set("Content-Type", "application/json");
  headers.set("X-WebsiteBench-Turnstile-Verified", "1");
  return {
    request: new Request(request.url, {
      method: request.method,
      headers,
      body: JSON.stringify({ email: payload.email }),
      redirect: request.redirect,
    }),
  };
}

export function publicTurnstileSiteKey(env) {
  const value = String(env.TURNSTILE_SITE_KEY || "").trim();
  return /^[0-9A-Za-z_-]{20,200}$/u.test(value) ? value : "";
}

export function injectTurnstileClient(response, env) {
  const siteKey = publicTurnstileSiteKey(env);
  const contentType = response.headers.get("Content-Type") || "";
  // Gate the widget on the same switch as the verifier. If a stale site key
  // outlived the opt-out, injecting would make the browser attach a token the
  // verifier no longer strips, and the strict { email } payload check downstream
  // would reject every registration.
  if (!turnstileRequired(env)) return response;
  if (!siteKey || !contentType.toLowerCase().includes("text/html")) return response;
  const headers = new Headers(response.headers);
  headers.delete("Content-Length");
  headers.set("X-WebsiteBench-Turnstile", "enabled");
  const script = `<script>(function(){var k=${JSON.stringify(siteKey)},p='/api/auth/send-code',ready;function token(){if(!ready){ready=new Promise(function(resolve,reject){var s=document.createElement('script');s.src='https://challenges.cloudflare.com/turnstile/v0/api.js?render='+encodeURIComponent(k);s.async=true;s.onload=function(){turnstile.execute(k,{action:'email'}).then(resolve,reject)};s.onerror=reject;document.head.appendChild(s)})}return ready}var f=window.fetch;window.fetch=function(input,init){var u=typeof input==='string'?input:input&&input.url;if(!init||String(init.method||'GET').toUpperCase()!=='POST'||!u||new URL(u,location.href).pathname!==p)return f.apply(this,arguments);return token().then(function(t){var body;try{body=JSON.parse(init.body)}catch(_){throw new Error('invalid email request')}body['cf-turnstile-response']=t;return f.call(window,input,Object.assign({},init,{body:JSON.stringify(body)}))})}})();</script>`;
  return new Response(new ReadableStream({
    async start(controller) {
      const text = await response.text();
      controller.enqueue(new TextEncoder().encode(text.replace(/<\/body\s*>/iu, `${script}</body>`)));
      controller.close();
    },
  }), { status: response.status, statusText: response.statusText, headers });
}
