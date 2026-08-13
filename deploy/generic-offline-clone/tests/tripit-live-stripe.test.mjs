import assert from "node:assert/strict";
import test from "node:test";

import { verifyTripitLiveStripe } from "../scripts/verify-tripit-live-stripe.mjs";


test("TripIt live Stripe smoke reaches a hosted test Checkout Session", async () => {
  const requests = [];
  let evidence = null;
  const fetchImpl = async (url, options = {}) => {
    requests.push({ url, options });
    if (url === "https://api.stripe.com/v1/account") {
      return new Response("{}", { status: 200 });
    }
    if (url === "https://api.stripe.com/v1/checkout/sessions") {
      return new Response(
        '{"id":"cs_test_direct_123","url":"https://checkout.stripe.com/c/pay/cs_test_direct_123"}',
        { status: 200 },
      );
    }
    const path = new URL(url).pathname;
    if (path === "/healthz") {
      return new Response('{"ok":true,"site_id":"tripit"}', {
        status: 200,
        headers: { "x-websitebench-build-id": "build-123" },
      });
    }
    if (path === "/account/login") {
      return new Response(null, {
        status: 303,
        headers: {
          location: "/app/trips",
          "set-cookie": "__Host-websitebench-tripit-session=session-123; Path=/; Secure",
        },
      });
    }
    if (path === "/pro/upgrade") {
      return new Response("Continue to Stripe test checkout", {
        status: 200,
        headers: { "x-websitebench-payment-mode": "stripe-test" },
      });
    }
    if (path === "/pro/subscribe") {
      return new Response(null, {
        status: 303,
        headers: { location: "https://checkout.stripe.com/c/pay/cs_test_123" },
      });
    }
    throw new Error(`unexpected request ${url}`);
  };

  const result = await verifyTripitLiveStripe({
    environment: {
      BASIC_AUTH_PASSWORD: "bench-password",
      DEPLOYMENT_BUILD_ID: "build-123",
      PUBLIC_CLONE_SITE_URL: "https://tripit.example.test",
      STRIPE_TEST_SECRET_KEY: "sk_test_1234567890abcdefghijklmnop",
      STRIPE_TEST_WEBHOOK_SECRET: "whsec_1234567890abcdefghijklmnop",
    },
    fetchImpl,
    evidenceWriter: (_path, value) => {
      evidence = JSON.parse(value);
    },
  });

  assert.equal(result.hosted_checkout, "passed");
  assert.equal(evidence.payment_adapter, "stripe-test");
  assert.equal(requests.length, 6);
  assert.equal(
    requests[0].options.headers.Authorization,
    "Bearer sk_test_1234567890abcdefghijklmnop",
  );
  assert.match(requests[1].options.body, /expires_at=/u);
  assert.match(requests[3].options.body, /traveler%40example\.com/u);
  assert.match(
    requests[5].options.headers.Cookie,
    /__Host-websitebench-tripit-session=session-123/u,
  );
  assert.equal(requests[5].options.redirect, "manual");
});
