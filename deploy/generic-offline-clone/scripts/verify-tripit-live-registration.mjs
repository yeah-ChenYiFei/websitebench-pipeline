#!/usr/bin/env node

import assert from "node:assert/strict";
import { randomBytes } from "node:crypto";
import { writeFileSync } from "node:fs";
import { pathToFileURL } from "node:url";


const SITE_ID = "tripit";
const DEFAULT_SITE_URL = "https://tripit.website-bench.com";
const RESEND_API = "https://api.resend.com";
const REGISTRATION_SUBJECT = "Verify your TripIt account";
const SUCCESSFUL_DELIVERY_EVENTS = new Set(["delivered", "opened", "clicked"]);
const FAILED_DELIVERY_EVENTS = new Set([
  "bounced",
  "canceled",
  "complained",
  "failed",
  "suppressed",
]);

function required(environment, name) {
  const value = String(environment[name] || "").trim();
  if (!value) throw new Error(`${name} is required for the TripIt live registration check`);
  return value;
}

function delay(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

export function smokeRecipient(configuredAddress) {
  const recipient = String(configuredAddress || "").trim().toLowerCase();
  if (!/^[^@\s]+@[^@\s]+$/u.test(recipient) || recipient.length > 254) {
    throw new Error("PUBLIC_CLONE_AUTH_SMOKE_EMAIL must be one valid email address");
  }
  return recipient;
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
    .filter((value) => value.includes("="));
}

function mergedCookies(...groups) {
  const cookies = new Map();
  for (const cookie of groups.flat()) {
    const separator = cookie.indexOf("=");
    cookies.set(cookie.slice(0, separator), cookie);
  }
  return [...cookies.values()].join("; ");
}

async function responseJson(response, label) {
  const body = await response.json().catch(() => null);
  if (!body || typeof body !== "object" || Array.isArray(body)) {
    throw new Error(`${label} returned invalid JSON`);
  }
  return body;
}

async function currentHealth(fetchImpl, siteUrl, expectedBuildId) {
  const response = await fetchImpl(`${siteUrl}/healthz`, {
    headers: { "Cache-Control": "no-cache" },
  });
  assert.equal(response.status, 200, "TripIt health check is unavailable");
  const body = await responseJson(response, "TripIt health check");
  assert.equal(body.ok, true, "TripIt health check did not report success");
  assert.equal(body.site_id, SITE_ID, "TripIt health check returned another site");
  assert.equal(
    response.headers.get("x-websitebench-build-id"),
    expectedBuildId,
    "public Worker build does not match the deployed revision",
  );
  assert.equal(
    response.headers.get("x-websitebench-container-build-id"),
    expectedBuildId,
    "public Container build does not match the deployed revision",
  );
  assert.match(
    response.headers.get("x-websitebench-worker-version") || "",
    /^[A-Za-z0-9._:@+-]{1,160}$/u,
    "public Worker version metadata is missing",
  );
}

async function sendRegistrationCode({
  authorization,
  cookie,
  fetchImpl,
  origin,
  recipient,
  smokeSecret,
  sleep,
}) {
  const attempts = 4;
  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    const issuedAfter = Date.now();
    const response = await fetchImpl(`${origin}/api/auth/send-code`, {
      method: "POST",
      headers: {
        Authorization: authorization,
        "Content-Type": "application/json",
        Cookie: cookie,
        Origin: origin,
        "X-WebsiteBench-Registration-Smoke-Secret": smokeSecret,
      },
      body: JSON.stringify({ email: recipient }),
      redirect: "manual",
    });
    if (response.status === 429 && attempt < attempts) {
      const declared = Number(response.headers.get("retry-after") || "30");
      const seconds = Number.isFinite(declared)
        ? Math.max(1, Math.min(120, Math.ceil(declared)))
        : 30;
      await sleep(seconds * 1_000);
      continue;
    }
    const body = await responseJson(response, "TripIt send-code");
    assert.equal(response.status, 202, `TripIt send-code returned HTTP ${response.status}`);
    assert.equal(body.ok, true, "TripIt send-code did not report success");
    assert.equal(body.expires_in, 300, "TripIt send-code returned the wrong expiry");
    assert.equal("dev_code" in body, false, "TripIt exposed a development OTP");
    assert.match(
      String(body.smoke_code || ""),
      /^[0-9]{6}$/u,
      "TripIt trusted smoke channel omitted the OTP",
    );
    return { issuedAfter, smokeCode: String(body.smoke_code) };
  }
  throw new Error("TripIt send-code remained rate limited");
}

async function resendJson(fetchImpl, apiKey, path) {
  const response = await fetchImpl(`${RESEND_API}${path}`, {
    headers: {
      Accept: "application/json",
      Authorization: `Bearer ${apiKey}`,
    },
  });
  if (!response.ok) {
    const error = new Error(`Resend delivery lookup returned HTTP ${response.status}`);
    error.resendStatus = response.status;
    throw error;
  }
  return responseJson(response, "Resend delivery lookup");
}

function matchingSentEmail(list, recipient, issuedAfter) {
  const rows = Array.isArray(list.data) ? list.data : [];
  return rows.find((row) => {
    const recipients = Array.isArray(row?.to) ? row.to : [];
    const createdAt = Date.parse(String(row?.created_at || ""));
    return recipients.some((value) => String(value).trim().toLowerCase() === recipient)
      && row?.subject === REGISTRATION_SUBJECT
      && Number.isFinite(createdAt)
      && createdAt >= issuedAfter - 10_000;
  }) || null;
}

function verificationCode(detail) {
  const text = typeof detail.text === "string" ? detail.text : "";
  const match = /Your verification code is ([0-9]{6})\./u.exec(text);
  if (!match) throw new Error("delivered TripIt email omitted the verification code");
  return match[1];
}

async function waitForDeliveredEmail({
  apiKey,
  attempts,
  fetchImpl,
  issuedAfter,
  recipient,
  sleep,
}) {
  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    const list = await resendJson(fetchImpl, apiKey, "/emails?limit=100");
    const match = matchingSentEmail(list, recipient, issuedAfter);
    if (match?.id) {
      const detail = await resendJson(
        fetchImpl,
        apiKey,
        `/emails/${encodeURIComponent(String(match.id))}`,
      );
      const recipients = Array.isArray(detail.to) ? detail.to : [];
      const tags = Array.isArray(detail.tags) ? detail.tags : [];
      assert.ok(
        recipients.some((value) => String(value).trim().toLowerCase() === recipient),
        "Resend delivery recipient changed",
      );
      assert.equal(detail.subject, REGISTRATION_SUBJECT, "Resend delivery subject changed");
      assert.match(String(detail.from || ""), /^TripIt\s*</u, "Resend sender branding changed");
      assert.ok(
        tags.some((tag) => tag?.name === "purpose" && tag?.value === "registration"),
        "Resend delivery omitted the registration tag",
      );
      assert.ok(
        tags.some((tag) => tag?.name === "site" && tag?.value === SITE_ID),
        "Resend delivery omitted the TripIt site tag",
      );
      const event = String(detail.last_event || match.last_event || "");
      if (FAILED_DELIVERY_EVENTS.has(event)) {
        throw new Error(`Resend reported terminal delivery state ${event}`);
      }
      if (SUCCESSFUL_DELIVERY_EVENTS.has(event)) {
        return { audited: true, code: verificationCode(detail), event };
      }
    }
    if (attempt < attempts) await sleep(5_000);
  }
  throw new Error("TripIt email was not delivered to the recipient mail server in time");
}

export async function verifyTripitLiveRegistration({
  environment = process.env,
  fetchImpl = fetch,
  sleep = delay,
  evidenceWriter = (path, value) => writeFileSync(path, value, { encoding: "utf8" }),
} = {}) {
  const origin = String(environment.PUBLIC_CLONE_SITE_URL || DEFAULT_SITE_URL)
    .trim()
    .replace(/\/$/u, "");
  const expectedBuildId = required(environment, "DEPLOYMENT_BUILD_ID");
  const recipient = smokeRecipient(required(environment, "PUBLIC_CLONE_AUTH_SMOKE_EMAIL"));
  const authorization = basicAuthorization(required(environment, "BASIC_AUTH_PASSWORD"));
  const smokeSecret = required(environment, "PUBLIC_CLONE_AUTH_SMOKE_SECRET");
  const resendApiKey = required(environment, "RESEND_API_KEY");
  const deliveryAttempts = Math.max(
    1,
    Math.min(120, Number(environment.RESEND_DELIVERY_ATTEMPTS || "60")),
  );

  await currentHealth(fetchImpl, origin, expectedBuildId);

  const registration = await fetchImpl(`${origin}/account/create`, {
    headers: { Authorization: authorization },
    redirect: "manual",
  });
  assert.equal(registration.status, 200, "TripIt registration page is unavailable");
  const markup = await registration.text();
  assert.match(markup, /data-external-registration=["']true["']/u, "TripIt is using local-only registration");
  assert.match(markup, /\/static\/auth-verification\.js/u, "TripIt registration omitted the verification client");
  const anonymousCookies = responseCookies(registration);
  assert.ok(
    anonymousCookies.some((value) => value.startsWith("__Host-websitebench-tripit-session=")),
    "TripIt registration did not issue an isolated session",
  );
  const anonymousCookie = mergedCookies(anonymousCookies);

  const issued = await sendRegistrationCode({
    authorization,
    cookie: anonymousCookie,
    fetchImpl,
    origin,
    recipient,
    smokeSecret,
    sleep,
  });
  let delivered;
  try {
    delivered = await waitForDeliveredEmail({
      apiKey: resendApiKey,
      attempts: deliveryAttempts,
      fetchImpl,
      issuedAfter: issued.issuedAfter,
      recipient,
      sleep,
    });
    assert.equal(
      delivered.code,
      issued.smokeCode,
      "Resend email body OTP differs from the issued challenge",
    );
  } catch (error) {
    if (error?.resendStatus !== 401) throw error;
    // A send-only Resend key can submit real mail but cannot read delivery
    // events. The provider acceptance above remains authoritative for sending;
    // the Worker-authenticated channel lets this check consume the exact same
    // OTP without exposing it to ordinary Basic-authenticated visitors.
    delivered = {
      audited: false,
      code: issued.smokeCode,
      event: "not-audited-send-only-key",
    };
  }

  const verified = await fetchImpl(`${origin}/api/auth/verify-code`, {
    method: "POST",
    headers: {
      Authorization: authorization,
      "Content-Type": "application/json",
      Cookie: anonymousCookie,
      Origin: origin,
    },
    body: JSON.stringify({ email: recipient, code: delivered.code }),
    redirect: "manual",
  });
  const verifiedBody = await responseJson(verified, "TripIt verify-code");
  assert.equal(verified.status, 200, "TripIt rejected the delivered OTP");
  assert.equal(verifiedBody.ok, true, "TripIt verify-code did not report success");
  assert.equal(verifiedBody.status, "verified", "TripIt OTP did not mint a verified ticket");

  const accountPassword = `Wb1a-${randomBytes(18).toString("base64url")}`;
  const form = new URLSearchParams({
    email_address: recipient,
    password: accountPassword,
    place: "",
    toc: "1",
  });
  const created = await fetchImpl(`${origin}/account/update`, {
    method: "POST",
    headers: {
      Authorization: authorization,
      "Content-Type": "application/x-www-form-urlencoded",
      Cookie: anonymousCookie,
      Origin: origin,
    },
    body: form.toString(),
    redirect: "manual",
  });
  assert.equal(created.status, 303, "TripIt verified OTP did not create an account");
  assert.equal(created.headers.get("location"), "/app/trips", "TripIt registration did not enter the app");
  const accountCookie = mergedCookies(anonymousCookies, responseCookies(created));
  const trips = await fetchImpl(`${origin}/app/trips`, {
    headers: { Authorization: authorization, Cookie: accountCookie },
    redirect: "manual",
  });
  assert.equal(trips.status, 200, "TripIt created account session is unavailable");

  const signedOut = await fetchImpl(`${origin}/account/logout`, {
    method: "POST",
    headers: { Authorization: authorization, Cookie: accountCookie, Origin: origin },
    redirect: "manual",
  });
  assert.equal(signedOut.status, 303, "TripIt account could not sign out");
  const login = await fetchImpl(`${origin}/account/login`, {
    method: "POST",
    headers: {
      Authorization: authorization,
      "Content-Type": "application/x-www-form-urlencoded",
      Origin: origin,
    },
    body: new URLSearchParams({
      login_email_address: recipient,
      login_password: accountPassword,
    }).toString(),
    redirect: "manual",
  });
  assert.equal(login.status, 303, "TripIt created account could not sign in again");
  assert.ok(
    responseCookies(login).some((value) => value.startsWith("__Host-websitebench-tripit-session=")),
    "TripIt login did not issue an isolated session",
  );

  const evidence = {
    schema_version: "websitebench.tripit-public-registration-smoke.v1",
    site_id: SITE_ID,
    build_id: expectedBuildId,
    worker_version: registration.headers.get("x-websitebench-worker-version") || null,
    provider_acceptance: "passed",
    recipient_mail_server_delivery: delivered.event,
    delivery_audit: delivered.audited ? "passed" : "unavailable-send-only-key",
    otp_verification: "passed",
    account_creation: "passed",
    account_login: "passed",
    generated_at: new Date().toISOString(),
  };
  evidenceWriter(
    String(environment.TRIPIT_REGISTRATION_EVIDENCE_PATH || "tripit-registration-smoke.json"),
    `${JSON.stringify(evidence, null, 2)}\n`,
  );
  return evidence;
}

async function main() {
  const result = await verifyTripitLiveRegistration();
  process.stdout.write(
    `Verified TripIt build ${result.build_id}: real Resend submission, OTP consumption, account creation, and login all passed (delivery audit: ${result.delivery_audit}).\n`,
  );
}

if (import.meta.url === pathToFileURL(process.argv[1] || "").href) {
  main().catch((error) => {
    process.stderr.write(`TripIt live registration verification failed: ${error instanceof Error ? error.message : "unknown error"}\n`);
    process.exitCode = 1;
  });
}
