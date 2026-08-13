import assert from "node:assert/strict";
import test from "node:test";

import { createPublicCloneAuthProxy } from "../../shared/public-clone-auth-proxy.js";

const registrationTemplate = {
  sender_display_name: "edX Learning Clone",
  subject: "Confirm ${code}",
  lead: "Complete your edX Learning Clone registration.",
  body: "Enter verification code ${code}.",
  expiry: "This code expires in ${minutes} minutes.",
  footer: "Use this code only on edX Learning Clone.",
};

const mailTemplates = {
  registration: {
    template_id: "edx.registration.v1",
    subject: registrationTemplate.subject,
    lead: registrationTemplate.lead,
    body: registrationTemplate.body,
    expiry: registrationTemplate.expiry,
    footer: registrationTemplate.footer,
    required_variables: ["code", "minutes"],
    secret_variables: ["code"],
  },
  "password-reset": {
    template_id: "edx.password-reset.v1",
    subject: "Recover your edX Learning Clone account",
    lead: "A password recovery was requested.",
    body: "Enter recovery code ${code} to continue.",
    expiry: "This code expires in ${minutes} minutes.",
    footer: "Ignore this message if you did not request recovery.",
    required_variables: ["code", "minutes"],
    secret_variables: ["code"],
  },
  "enrollment-receipt": {
    template_id: "edx.enrollment-receipt.v1",
    subject: "edX Learning Clone enrollment ${enrollment_id}",
    lead: "Your simulated learning enrollment is recorded.",
    body: "Enrollment ${enrollment_id} is for course run ${run_id}.",
    expiry: "No real tuition payment or credential was issued.",
    footer: "This learning record belongs only to your edX Learning Clone account.",
    required_variables: ["enrollment_id", "run_id"],
    secret_variables: [],
  },
};

function businessProxy() {
  return createPublicCloneAuthProxy({
    siteId: "edx",
    siteLabel: "edX Learning Clone",
    registrationTemplate,
    mailTemplates,
    senderDisplayName: "edX Learning Clone",
  });
}

test("business mail effects accepts only frozen non-secret templates", () => {
  const proxy = businessProxy();
  const envelope = {
    purpose: "enrollment-receipt",
    template_id: "edx.enrollment-receipt.v1",
    recipient: "learner@example.test",
    variables: {
      enrollment_id: "order-<safe>",
      run_id: "course-v1:edX+Demo+2026",
    },
  };
  assert.equal(proxy.resendBusinessPayloadIsValid(envelope), true);
  assert.equal(
    proxy.resendBusinessPayloadIsValid({ ...envelope, html: "<h1>arbitrary</h1>" }),
    false,
  );
  assert.equal(
    proxy.resendBusinessPayloadIsValid({
      ...envelope,
      purpose: "registration",
      template_id: "edx.registration.v1",
      variables: { code: "123456", minutes: 5 },
    }),
    false,
  );
  assert.equal(
    proxy.resendBusinessPayloadIsValid({
      ...envelope,
      variables: { enrollment_id: "order-1" },
    }),
    false,
  );
});

test("auth mail effects accepts only frozen secret challenge envelopes", async () => {
  const proxy = businessProxy();
  const envelope = {
    purpose: "password-reset",
    template_id: "edx.password-reset.v1",
    recipient: "learner@example.test",
    variables: { code: "123456", minutes: 10 },
  };
  assert.equal(proxy.resendAuthPayloadIsValid(envelope), true);
  assert.equal(
    proxy.resendAuthPayloadIsValid({ ...envelope, html: "<p>arbitrary</p>" }),
    false,
  );
  assert.equal(
    proxy.resendAuthPayloadIsValid({
      ...envelope,
      variables: { code: "not-a-code", minutes: 10 },
    }),
    false,
  );
  assert.equal(proxy.resendBusinessPayloadIsValid(envelope), false);

  const originalFetch = globalThis.fetch;
  let observed;
  globalThis.fetch = async (target, options) => {
    observed = { target: String(target), options };
    return new Response('{"id":"email_auth_123"}', { status: 200 });
  };
  try {
    const response = await proxy.resendOutbound(
      new Request("http://resend.internal/auth-emails", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Idempotency-Key": "auth_0123456789abcdef0123456789abcdef",
        },
        body: JSON.stringify(envelope),
      }),
      {
        RESEND_API_KEY: "provider-secret",
        RESEND_FROM_EMAIL: "verify@send.example.test",
      },
    );
    assert.equal(response.status, 200);
    const sent = JSON.parse(observed.options.body);
    assert.equal(sent.from, "edX Learning Clone <verify@send.example.test>");
    assert.equal(sent.subject, "Recover your edX Learning Clone account");
    assert.match(sent.text, /123456/u);
    assert.deepEqual(sent.tags, [
      { name: "purpose", value: "password-reset" },
      { name: "site", value: "edx" },
      { name: "template", value: "edx.password-reset.v1" },
    ]);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("business mail effects renders frozen copy at the gateway and owns sender", async () => {
  const proxy = businessProxy();
  const envelope = {
    purpose: "enrollment-receipt",
    template_id: "edx.enrollment-receipt.v1",
    recipient: "learner@example.test",
    variables: {
      enrollment_id: "order-<safe>",
      run_id: "course-v1:edX+Demo+2026",
    },
  };
  const originalFetch = globalThis.fetch;
  let observed;
  globalThis.fetch = async (target, options) => {
    observed = { target: String(target), options };
    return new Response('{"id":"email_123"}', { status: 200 });
  };
  try {
    const response = await proxy.resendOutbound(
      new Request("http://resend.internal/business-emails", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Idempotency-Key": "business_0123456789abcdef0123456789abcdef",
        },
        body: JSON.stringify(envelope),
      }),
      {
        RESEND_API_KEY: "provider-secret",
        RESEND_FROM_EMAIL: "verify@send.example.test",
      },
    );
    assert.equal(response.status, 200);
    assert.deepEqual(await response.json(), { ok: true });
    assert.equal(observed.target, "https://api.resend.com/emails");
    const sent = JSON.parse(observed.options.body);
    assert.equal(sent.from, "edX Learning Clone <verify@send.example.test>");
    assert.equal(sent.subject, "edX Learning Clone enrollment order-<safe>");
    assert.match(sent.html, /order-&lt;safe&gt;/u);
    assert.doesNotMatch(sent.html, /<safe>/u);
    assert.deepEqual(sent.tags, [
      { name: "purpose", value: "enrollment-receipt" },
      { name: "site", value: "edx" },
      { name: "template", value: "edx.enrollment-receipt.v1" },
    ]);
    assert.equal("html" in envelope, false);
    assert.equal(observed.options.headers.Authorization, "Bearer provider-secret");
  } finally {
    globalThis.fetch = originalFetch;
  }
});
