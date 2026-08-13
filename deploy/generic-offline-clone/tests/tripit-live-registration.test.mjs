import assert from "node:assert/strict";
import test from "node:test";

import {
  smokeRecipient,
  verifyTripitLiveRegistration,
} from "../scripts/verify-tripit-live-registration.mjs";


const BUILD_ID = "0123456789abcdef0123456789abcdef01234567";
const WORKER_VERSION = "01234567-89ab-cdef-0123-456789abcdef";
const RECIPIENT = "qa@example.com";

function environment() {
  return {
    BASIC_AUTH_PASSWORD: "edge-secret",
    DEPLOYMENT_BUILD_ID: BUILD_ID,
    PUBLIC_CLONE_AUTH_SMOKE_EMAIL: RECIPIENT,
    PUBLIC_CLONE_AUTH_SMOKE_SECRET: "smoke-secret-at-least-32-characters",
    PUBLIC_CLONE_SITE_URL: "https://tripit.website-bench.com",
    RESEND_API_KEY: "re_test_key",
    RESEND_DELIVERY_ATTEMPTS: "1",
  };
}

function json(value, init = {}) {
  return new Response(JSON.stringify(value), {
    status: init.status || 200,
    headers: { "Content-Type": "application/json", ...(init.headers || {}) },
  });
}

function successfulFetch(requests, { deliveryEvent = "delivered" } = {}) {
  return async (url, options = {}) => {
    requests.push({ url, options });
    if (url.endsWith("/healthz")) {
      return json(
        { ok: true, site_id: "tripit" },
        { headers: {
          "X-WebsiteBench-Build-ID": BUILD_ID,
          "X-WebsiteBench-Container-Build-ID": BUILD_ID,
          "X-WebsiteBench-Worker-Version": WORKER_VERSION,
        } },
      );
    }
    if (url.endsWith("/account/create")) {
      return new Response(
        '<form data-external-registration="true"></form><script src="/static/auth-verification.js"></script>',
        {
          status: 200,
          headers: {
            "Set-Cookie": "__Host-websitebench-tripit-session=anonymous; Secure; HttpOnly; Path=/",
            "X-WebsiteBench-Worker-Version": WORKER_VERSION,
          },
        },
      );
    }
    if (url.endsWith("/api/auth/send-code")) {
      return json({ ok: true, expires_in: 300, smoke_code: "654321" }, { status: 202 });
    }
    if (url.endsWith("/emails?limit=100")) {
      return json({
        object: "list",
        data: [{
          id: "email-id",
          to: [RECIPIENT],
          subject: "Verify your TripIt account",
          created_at: new Date(Date.now() + 1_000).toISOString(),
          last_event: deliveryEvent,
        }],
      });
    }
    if (url.endsWith("/emails/email-id")) {
      return json({
        id: "email-id",
        to: [RECIPIENT],
        from: "TripIt <verify@example.com>",
        subject: "Verify your TripIt account",
        text: "Finish creating your TripIt account.\n\nYour verification code is 654321.\n\nThis code expires in 5 minutes.",
        last_event: deliveryEvent,
        tags: [
          { name: "purpose", value: "registration" },
          { name: "site", value: "tripit" },
        ],
      });
    }
    if (url.endsWith("/api/auth/verify-code")) {
      return json({ ok: true, status: "verified" });
    }
    if (url.endsWith("/account/update")) {
      return new Response(null, {
        status: 303,
        headers: {
          Location: "/app/trips",
          "Set-Cookie": "__Host-websitebench-tripit-session=account; Secure; HttpOnly; Path=/",
        },
      });
    }
    if (url.endsWith("/app/trips")) return new Response("Trips", { status: 200 });
    if (url.endsWith("/account/logout")) {
      return new Response(null, { status: 303, headers: { Location: "/" } });
    }
    if (url.endsWith("/account/login")) {
      return new Response(null, {
        status: 303,
        headers: {
          Location: "/app/trips",
          "Set-Cookie": "__Host-websitebench-tripit-session=login; Secure; HttpOnly; Path=/",
        },
      });
    }
    throw new Error(`unexpected request: ${url}`);
  };
}

test("TripIt live smoke proves delivery, consumes OTP, creates account, and logs in", async () => {
  const requests = [];
  let evidenceText = "";
  const result = await verifyTripitLiveRegistration({
    environment: environment(),
    fetchImpl: successfulFetch(requests),
    sleep: async () => {},
    evidenceWriter: (_path, value) => { evidenceText = value; },
  });

  assert.equal(result.recipient_mail_server_delivery, "delivered");
  assert.equal(result.delivery_audit, "passed");
  assert.equal(result.account_login, "passed");
  assert.equal(evidenceText.includes(RECIPIENT), false);
  assert.equal(evidenceText.includes("654321"), false);
  assert.equal(requests.some(({ url }) => url === "https://api.resend.com/emails?limit=100"), true);
  const verified = requests.find(({ url }) => url.endsWith("/api/auth/verify-code"));
  assert.deepEqual(JSON.parse(verified.options.body), { email: RECIPIENT, code: "654321" });
  const created = requests.find(({ url }) => url.endsWith("/account/update"));
  assert.equal(new URLSearchParams(created.options.body).get("email_address"), RECIPIENT);
  assert.equal(requests.every(({ options }) => !String(options.headers?.Authorization || "").includes("edge-secret")), true);
});

test("TripIt live smoke completes through a send-only Resend key", async () => {
  const requests = [];
  const fetchImpl = successfulFetch(requests);
  const result = await verifyTripitLiveRegistration({
    environment: environment(),
    fetchImpl: async (url, options = {}) => {
      if (url.endsWith("/emails?limit=100")) {
        requests.push({ url, options });
        return json({ message: "restricted" }, { status: 401 });
      }
      return fetchImpl(url, options);
    },
    sleep: async () => {},
    evidenceWriter: () => {},
  });

  assert.equal(result.provider_acceptance, "passed");
  assert.equal(result.recipient_mail_server_delivery, "not-audited-send-only-key");
  assert.equal(result.delivery_audit, "unavailable-send-only-key");
  const sent = requests.find(({ url }) => url.endsWith("/api/auth/send-code"));
  assert.equal(
    sent.options.headers["X-WebsiteBench-Registration-Smoke-Secret"],
    "smoke-secret-at-least-32-characters",
  );
  const verified = requests.find(({ url }) => url.endsWith("/api/auth/verify-code"));
  assert.deepEqual(JSON.parse(verified.options.body), { email: RECIPIENT, code: "654321" });
});

test("TripIt live smoke fails closed on a bounced email", async () => {
  await assert.rejects(
    verifyTripitLiveRegistration({
      environment: environment(),
      fetchImpl: successfulFetch([], { deliveryEvent: "bounced" }),
      sleep: async () => {},
      evidenceWriter: () => {},
    }),
    /terminal delivery state bounced/u,
  );
});

test("TripIt smoke recipient validation rejects malformed values", () => {
  assert.equal(smokeRecipient(" QA@Example.com "), "qa@example.com");
  assert.throws(() => smokeRecipient("not-an-email"), /one valid email address/u);
});
