/** Shared Cloudflare outbound boundary for public-clone email verification. */

export const PUBLIC_CLONE_REDIS_HOST = "redis.internal";
export const PUBLIC_CLONE_RESEND_HOST = "resend.internal";

const REDIS_KEY_PREFIX = "public-clone-auth:v1:";
const SITE_ID_PATTERN = /^[a-z0-9][a-z0-9-]{1,62}$/;
const MAIL_PURPOSE_PATTERN = /^[a-z][a-z0-9-]{1,79}$/;
const TEMPLATE_ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._-]{1,119}$/;
const TEMPLATE_VARIABLE_PATTERN = /^[A-Za-z_][A-Za-z0-9_]*$/;
const ALLOWED_REDIS_COMMANDS = new Set([
  "DEL",
  "EXPIRE",
  "GET",
  "GETDEL",
  "INCR",
  "SET",
]);

function redisTtlIsValid(value) {
  const ttl = Number(value);
  return (
    Number.isInteger(ttl) &&
    ttl >= 1 &&
    ttl <= 60 * 60 &&
    String(value) === String(ttl)
  );
}

function redisCommandShapeIsValid(command) {
  const name = String(command[0]).toUpperCase();
  if (["DEL", "GET", "GETDEL", "INCR"].includes(name)) {
    return command.length === 2;
  }
  if (name === "EXPIRE") {
    return command.length === 3 && redisTtlIsValid(command[2]);
  }
  if (name === "SET") {
    return (
      [5, 6].includes(command.length) &&
      String(command[3]).toUpperCase() === "EX" &&
      redisTtlIsValid(command[4]) &&
      (command.length === 5 ||
        String(command[5]).toUpperCase() === "NX")
    );
  }
  return false;
}

function escapeHtml(value) {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function validatedIdentity(siteId, siteLabel) {
  const normalizedId = String(siteId || "").trim().toLowerCase();
  const normalizedLabel = String(siteLabel || "")
    .trim()
    .replace(/\s+/gu, " ");
  if (!SITE_ID_PATTERN.test(normalizedId)) {
    throw new TypeError("siteId is not a valid public clone identifier");
  }
  if (
    !normalizedLabel ||
    normalizedLabel.length > 80 ||
    /[\u0000-\u001f\u007f]/u.test(normalizedLabel)
  ) {
    throw new TypeError("siteLabel must contain 1 to 80 visible characters");
  }
  return Object.freeze({
    siteId: normalizedId,
    siteLabel: normalizedLabel,
  });
}

function validatedMailTemplate(identity, value) {
  const raw = value || {
    sender_display_name: identity.siteLabel,
    subject: `${identity.siteLabel} verification code`,
    lead: `Your ${identity.siteLabel} verification code is:`,
    body: "${code}",
    expiry: "This code expires in ${minutes} minutes.",
    footer: "If you did not request it, you can ignore this message.",
  };
  const expected = ["body", "expiry", "footer", "lead", "sender_display_name", "subject"];
  if (!raw || typeof raw !== "object" || Array.isArray(raw) || JSON.stringify(Object.keys(raw).sort()) !== JSON.stringify(expected)) {
    throw new TypeError("registration mail template has missing or unknown fields");
  }
  for (const [key, maximum] of [["sender_display_name", 120], ["subject", 200], ["lead", 1000], ["body", 2000], ["expiry", 1000], ["footer", 1000]]) {
    if (typeof raw[key] !== "string" || !raw[key].trim() || raw[key] !== raw[key].trim() || raw[key].length > maximum || /[\u0000\r]/u.test(raw[key])) {
      throw new TypeError(`registration mail template ${key} is invalid`);
    }
  }
  const joined = [raw.subject, raw.lead, raw.body, raw.expiry, raw.footer].join("\n");
  if (!joined.includes("${code}") || /\$\{(?!code\}|minutes\})/u.test(joined)) {
    throw new TypeError("registration mail template may use only code and minutes");
  }
  return Object.freeze({ ...raw });
}

function boundedTemplateText(value, label, maximum) {
  if (
    typeof value !== "string" ||
    !value.trim() ||
    value !== value.trim() ||
    value.length > maximum ||
    /[\u0000\r]/u.test(value)
  ) {
    throw new TypeError(`business mail template ${label} is invalid`);
  }
  return value;
}

function templatePlaceholders(value) {
  const names = new Set();
  let position = 0;
  while (position < value.length) {
    const dollar = value.indexOf("$", position);
    if (dollar < 0) break;
    const next = value[dollar + 1] || "";
    if (next === "$") {
      position = dollar + 2;
      continue;
    }
    if (next === "{") {
      const closing = value.indexOf("}", dollar + 2);
      const name = closing < 0 ? "" : value.slice(dollar + 2, closing);
      if (!TEMPLATE_VARIABLE_PATTERN.test(name)) {
        throw new TypeError("business mail template placeholders are invalid");
      }
      names.add(name);
      position = closing + 1;
      continue;
    }
    const match = /^[A-Za-z_][A-Za-z0-9_]*/u.exec(value.slice(dollar + 1));
    if (!match) {
      throw new TypeError("business mail template placeholders are invalid");
    }
    names.add(match[0]);
    position = dollar + 1 + match[0].length;
  }
  return names;
}

function renderedTemplateField(value, variables) {
  let output = "";
  let position = 0;
  while (position < value.length) {
    const dollar = value.indexOf("$", position);
    if (dollar < 0) return output + value.slice(position);
    output += value.slice(position, dollar);
    const next = value[dollar + 1] || "";
    if (next === "$") {
      output += "$";
      position = dollar + 2;
      continue;
    }
    let name = "";
    if (next === "{") {
      const closing = value.indexOf("}", dollar + 2);
      name = closing < 0 ? "" : value.slice(dollar + 2, closing);
      position = closing + 1;
    } else {
      const match = /^[A-Za-z_][A-Za-z0-9_]*/u.exec(value.slice(dollar + 1));
      name = match?.[0] || "";
      position = dollar + 1 + name.length;
    }
    if (!TEMPLATE_VARIABLE_PATTERN.test(name) || !Object.hasOwn(variables, name)) {
      throw new TypeError("business mail template rendering is invalid");
    }
    output += variables[name];
  }
  return output;
}

function validatedBusinessMailTemplates(value) {
  if (value === null || value === undefined) return Object.freeze({});
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new TypeError("business mail templates are invalid");
  }
  const entries = Object.entries(value);
  if (entries.length > 64) throw new TypeError("business mail templates are invalid");
  const templates = {};
  const expected = [
    "body",
    "expiry",
    "footer",
    "lead",
    "required_variables",
    "secret_variables",
    "subject",
    "template_id",
  ];
  for (const [purpose, raw] of entries) {
    if (!MAIL_PURPOSE_PATTERN.test(purpose) || !raw || typeof raw !== "object" || Array.isArray(raw) || JSON.stringify(Object.keys(raw).sort()) !== JSON.stringify(expected)) {
      throw new TypeError("business mail templates are invalid");
    }
    const templateId = boundedTemplateText(raw.template_id, "template_id", 120);
    if (!TEMPLATE_ID_PATTERN.test(templateId)) {
      throw new TypeError("business mail template_id is invalid");
    }
    const template = {
      template_id: templateId,
      subject: boundedTemplateText(raw.subject, "subject", 200),
      lead: boundedTemplateText(raw.lead, "lead", 1000),
      body: boundedTemplateText(raw.body, "body", 4000),
      expiry: boundedTemplateText(raw.expiry, "expiry", 1000),
      footer: boundedTemplateText(raw.footer, "footer", 1000),
    };
    if (!Array.isArray(raw.required_variables) || !raw.required_variables.every((name) => typeof name === "string" && TEMPLATE_VARIABLE_PATTERN.test(name)) || new Set(raw.required_variables).size !== raw.required_variables.length) {
      throw new TypeError("business mail required variables are invalid");
    }
    if (!Array.isArray(raw.secret_variables) || !raw.secret_variables.every((name) => raw.required_variables.includes(name)) || new Set(raw.secret_variables).size !== raw.secret_variables.length) {
      throw new TypeError("business mail secret variables are invalid");
    }
    const placeholders = new Set();
    for (const field of [template.subject, template.lead, template.body, template.expiry, template.footer]) {
      for (const name of templatePlaceholders(field)) placeholders.add(name);
    }
    if (placeholders.size !== raw.required_variables.length || raw.required_variables.some((name) => !placeholders.has(name))) {
      throw new TypeError("business mail placeholders do not match the template contract");
    }
    templates[purpose] = Object.freeze({
      ...template,
      required_variables: Object.freeze([...raw.required_variables]),
      secret_variables: Object.freeze([...raw.secret_variables]),
    });
  }
  return Object.freeze(templates);
}

function validatedSenderDisplayName(identity, value) {
  const source = value ?? identity.siteLabel;
  if (
    typeof source !== "string" ||
    !source.trim() ||
    source !== source.trim() ||
    source.length > 120 ||
    /[\u0000\r\n]/u.test(source)
  ) {
    throw new TypeError("business mail sender display name is invalid");
  }
  return source;
}

function normalizedBusinessVariables(template, value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const keys = Object.keys(value);
  if (keys.length !== template.required_variables.length || template.required_variables.some((name) => !Object.hasOwn(value, name))) {
    return null;
  }
  const variables = {};
  for (const name of template.required_variables) {
    const item = value[name];
    if (!(typeof item === "string" || Number.isSafeInteger(item))) return null;
    const text = String(item);
    if (!text || text.length > 1000 || /[\u0000\r]/u.test(text)) return null;
    variables[name] = text;
  }
  return variables;
}

function businessMailEnvelope(payload, templates) {
  if (!payload || typeof payload !== "object" || Array.isArray(payload) || JSON.stringify(Object.keys(payload).sort()) !== JSON.stringify(["purpose", "recipient", "template_id", "variables"])) {
    return null;
  }
  const template = templates[payload.purpose];
  if (
    !template ||
    template.secret_variables.length > 0 ||
    payload.template_id !== template.template_id ||
    typeof payload.recipient !== "string" ||
    payload.recipient.length > 254 ||
    !/^[^@\s]+@[^@\s]+$/u.test(payload.recipient)
  ) {
    return null;
  }
  const variables = normalizedBusinessVariables(template, payload.variables);
  if (variables === null) return null;
  return { purpose: payload.purpose, recipient: payload.recipient, template, variables };
}

function authMailEnvelope(payload, templates) {
  if (!payload || typeof payload !== "object" || Array.isArray(payload) || JSON.stringify(Object.keys(payload).sort()) !== JSON.stringify(["purpose", "recipient", "template_id", "variables"])) {
    return null;
  }
  const template = templates[payload.purpose];
  if (
    !["registration", "password-reset"].includes(payload.purpose) ||
    !template ||
    template.secret_variables.length !== 1 ||
    template.secret_variables[0] !== "code" ||
    payload.template_id !== template.template_id ||
    typeof payload.recipient !== "string" ||
    payload.recipient.length > 254 ||
    !/^[^@\s]+@[^@\s]+$/u.test(payload.recipient)
  ) {
    return null;
  }
  const variables = normalizedBusinessVariables(template, payload.variables);
  if (
    variables === null ||
    !/^[0-9]{6}$/u.test(variables.code || "") ||
    !/^(?:[1-9]|[1-5][0-9]|60)$/u.test(variables.minutes || "")
  ) {
    return null;
  }
  return { purpose: payload.purpose, recipient: payload.recipient, template, variables };
}

function renderBusinessMailTemplate(template, variables) {
  const fields = Object.fromEntries(
    ["subject", "lead", "body", "expiry", "footer"].map((key) => [
      key,
      renderedTemplateField(template[key], variables),
    ]),
  );
  return {
    ...fields,
    html: ["lead", "body", "expiry", "footer"].map((key) => `<p>${escapeHtml(fields[key])}</p>`).join(""),
    text: ["lead", "body", "expiry", "footer"].map((key) => fields[key]).join("\n\n"),
  };
}

function renderMailTemplate(template, code) {
  const render = (value) => value.replaceAll("${code}", code).replaceAll("${minutes}", "5");
  const fields = Object.fromEntries(["subject", "lead", "body", "expiry", "footer"].map((key) => [key, render(template[key])]));
  return {
    ...fields,
    html: ["lead", "body", "expiry", "footer"].map((key) => `<p>${escapeHtml(fields[key])}</p>`).join(""),
    text: ["lead", "body", "expiry", "footer"].map((key) => fields[key]).join("\n\n"),
  };
}

function safeHttpsEndpoint(value) {
  try {
    const url = new URL(value);
    if (
      url.protocol !== "https:" ||
      url.username ||
      url.password ||
      url.search ||
      url.hash
    ) {
      return null;
    }
    return url;
  } catch {
    return null;
  }
}

async function parsedJsonBody(request, maximumBytes) {
  const declaredLength = Number(request.headers.get("Content-Length") || "0");
  if (
    (Number.isFinite(declaredLength) && declaredLength > maximumBytes) ||
    !request.headers
      .get("Content-Type")
      ?.toLowerCase()
      .startsWith("application/json")
  ) {
    return null;
  }
  try {
    const text = await request.text();
    if (!text || new TextEncoder().encode(text).length > maximumBytes) {
      return null;
    }
    return JSON.parse(text);
  } catch {
    return null;
  }
}

function proxyError(status, message) {
  return new Response(JSON.stringify({ error: message }), {
    status,
    headers: {
      "Cache-Control": "no-store",
      "Content-Type": "application/json; charset=utf-8",
    },
  });
}

export function createPublicCloneAuthProxy({
  siteId,
  siteLabel,
  registrationTemplate = null,
  mailTemplates = null,
  senderDisplayName = null,
}) {
  const identity = validatedIdentity(siteId, siteLabel);
  const mailTemplate = validatedMailTemplate(identity, registrationTemplate);
  const businessTemplates = validatedBusinessMailTemplates(mailTemplates);
  const businessSenderDisplayName = validatedSenderDisplayName(
    identity,
    senderDisplayName ?? mailTemplate.sender_display_name,
  );
  if (mailTemplate.sender_display_name !== businessSenderDisplayName) {
    throw new TypeError("mail sender display name does not match registration template");
  }
  const sitePrefix = `${REDIS_KEY_PREFIX}site:${identity.siteId}:`;
  const allowedGlobalPrefixes = [
    `${REDIS_KEY_PREFIX}global:cooldown-email:`,
    `${REDIS_KEY_PREFIX}global:rate-email-hour:`,
    `${REDIS_KEY_PREFIX}global:rate-ip-hour:`,
  ];

  function redisKeyIsAllowed(key) {
    return (
      key.startsWith(sitePrefix) ||
      allowedGlobalPrefixes.some((prefix) => key.startsWith(prefix))
    );
  }

  function redisCommandBatchIsValid(payload) {
    if (
      !Array.isArray(payload) ||
      payload.length < 1 ||
      payload.length > 8
    ) {
      return false;
    }
    return payload.every((command) => {
      if (
        !Array.isArray(command) ||
        command.length < 2 ||
        !ALLOWED_REDIS_COMMANDS.has(String(command[0]).toUpperCase()) ||
        !redisCommandShapeIsValid(command) ||
        !redisKeyIsAllowed(String(command[1]))
      ) {
        return false;
      }
      return command.every(
        (argument) =>
          !Array.isArray(argument) &&
          (argument === null || typeof argument !== "object") &&
          String(argument).length <= 4096,
      );
    });
  }

  function resendPayloadIsValid(payload) {
    const allowedKeys = new Set(["to", "subject", "html", "text", "tags"]);
    const codeMatch = typeof payload?.text === "string" ? /(?:^|\D)([0-9]{6})(?:\D|$)/u.exec(payload.text) : null;
    const code = codeMatch?.[1] || "";
    const expected = renderMailTemplate(mailTemplate, code);
    return Boolean(
      payload &&
        typeof payload === "object" &&
        !Array.isArray(payload) &&
        Object.keys(payload).every((key) => allowedKeys.has(key)) &&
        Array.isArray(payload.to) &&
        payload.to.length === 1 &&
        typeof payload.to[0] === "string" &&
        payload.to[0].length <= 254 &&
        /^[^@\s]+@[^@\s]+$/.test(payload.to[0]) &&
        payload.subject === expected.subject &&
        code &&
        payload.html === expected.html &&
        payload.text === expected.text &&
        Array.isArray(payload.tags) &&
        payload.tags.length === 2 &&
        payload.tags[0]?.name === "purpose" &&
        payload.tags[0]?.value === "registration" &&
        payload.tags[1]?.name === "site" &&
        payload.tags[1]?.value === identity.siteId,
    );
  }

  function resendBusinessPayloadIsValid(payload) {
    return businessMailEnvelope(payload, businessTemplates) !== null;
  }

  function resendAuthPayloadIsValid(payload) {
    return authMailEnvelope(payload, businessTemplates) !== null;
  }

  function resendProviderIsConfigured(env) {
    const from = String(env.RESEND_FROM_EMAIL || "").trim();
    if (
      !env.RESEND_API_KEY ||
      !from ||
      from.length > 320 ||
      /[\r\n]/.test(from) ||
      !/^[^<>\s@]+@[^<>\s@]+$/u.test(from)
    ) {
      return null;
    }
    return from;
  }

  async function sendResend(payload, idempotencyKey, senderDisplayName, env) {
    const from = resendProviderIsConfigured(env);
    if (!from) return proxyError(503, "email_not_configured");
    const response = await fetch("https://api.resend.com/emails", {
      method: "POST",
      headers: {
        Accept: "application/json",
        Authorization: `Bearer ${env.RESEND_API_KEY}`,
        "Content-Type": "application/json",
        "Idempotency-Key": idempotencyKey,
        "User-Agent": "WebsiteBench-Public-Clone-Auth/1.0",
      },
      body: JSON.stringify({ ...payload, from: `${senderDisplayName} <${from}>` }),
    });
    if (!response.ok) return proxyError(502, "email_delivery_failed");
    return new Response(JSON.stringify({ ok: true }), {
      status: 200,
      headers: {
        "Cache-Control": "no-store",
        "Content-Type": "application/json; charset=utf-8",
      },
    });
  }

  async function redisOutbound(request, env) {
    const url = new URL(request.url);
    if (
      request.method !== "POST" ||
      url.hostname !== PUBLIC_CLONE_REDIS_HOST ||
      !["/pipeline", "/multi-exec"].includes(url.pathname) ||
      url.search
    ) {
      return proxyError(403, "redis_request_denied");
    }
    const payload = await parsedJsonBody(request, 32 * 1024);
    if (!redisCommandBatchIsValid(payload)) {
      return proxyError(400, "invalid_redis_request");
    }
    const upstream = safeHttpsEndpoint(env.REDIS_REST_URL || "");
    if (!upstream || !env.REDIS_REST_TOKEN) {
      return proxyError(503, "redis_not_configured");
    }
    const target = new URL(
      url.pathname,
      `${upstream.href.replace(/\/$/, "")}/`,
    );
    const response = await fetch(target, {
      method: "POST",
      headers: {
        Accept: "application/json",
        Authorization: `Bearer ${env.REDIS_REST_TOKEN}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
    });
    return new Response(response.body, {
      status: response.status,
      headers: {
        "Cache-Control": "no-store",
        "Content-Type": "application/json; charset=utf-8",
      },
    });
  }

  async function resendOutbound(request, env) {
    const url = new URL(request.url);
    if (
      request.method !== "POST" ||
      url.hostname !== PUBLIC_CLONE_RESEND_HOST ||
      url.search
    ) {
      return proxyError(403, "email_request_denied");
    }
    if (url.pathname === "/business-emails") {
      return resendBusinessOutbound(request, env);
    }
    if (url.pathname === "/auth-emails") {
      return resendAuthOutbound(request, env);
    }
    if (url.pathname !== "/emails") return proxyError(403, "email_request_denied");
    const payload = await parsedJsonBody(request, 16 * 1024);
    const idempotencyKey = request.headers.get("Idempotency-Key") || "";
    if (
      !resendPayloadIsValid(payload) ||
      !/^[A-Za-z0-9_-]{16,128}$/.test(idempotencyKey)
    ) {
      return proxyError(400, "invalid_email_request");
    }
    return sendResend(payload, idempotencyKey, mailTemplate.sender_display_name, env);
  }

  async function resendAuthOutbound(request, env) {
    const url = new URL(request.url);
    if (
      request.method !== "POST" ||
      url.hostname !== PUBLIC_CLONE_RESEND_HOST ||
      url.pathname !== "/auth-emails" ||
      url.search
    ) {
      return proxyError(403, "email_request_denied");
    }
    const payload = await parsedJsonBody(request, 16 * 1024);
    const idempotencyKey = request.headers.get("Idempotency-Key") || "";
    const envelope = authMailEnvelope(payload, businessTemplates);
    if (!envelope || !/^[A-Za-z0-9_-]{16,128}$/.test(idempotencyKey)) {
      return proxyError(400, "invalid_auth_email_request");
    }
    const rendered = renderBusinessMailTemplate(envelope.template, envelope.variables);
    return sendResend(
      {
        to: [envelope.recipient],
        subject: rendered.subject,
        html: rendered.html,
        text: rendered.text,
        tags: [
          { name: "purpose", value: envelope.purpose },
          { name: "site", value: identity.siteId },
          { name: "template", value: envelope.template.template_id },
        ],
      },
      idempotencyKey,
      businessSenderDisplayName,
      env,
    );
  }

  async function resendBusinessOutbound(request, env) {
    const url = new URL(request.url);
    if (
      request.method !== "POST" ||
      url.hostname !== PUBLIC_CLONE_RESEND_HOST ||
      url.pathname !== "/business-emails" ||
      url.search
    ) {
      return proxyError(403, "email_request_denied");
    }
    const payload = await parsedJsonBody(request, 16 * 1024);
    const idempotencyKey = request.headers.get("Idempotency-Key") || "";
    const envelope = businessMailEnvelope(payload, businessTemplates);
    if (!envelope || !/^[A-Za-z0-9_-]{16,128}$/.test(idempotencyKey)) {
      return proxyError(400, "invalid_business_email_request");
    }
    const rendered = renderBusinessMailTemplate(envelope.template, envelope.variables);
    return sendResend(
      {
        to: [envelope.recipient],
        subject: rendered.subject,
        html: rendered.html,
        text: rendered.text,
        tags: [
          { name: "purpose", value: envelope.purpose },
          { name: "site", value: identity.siteId },
          { name: "template", value: envelope.template.template_id },
        ],
      },
      idempotencyKey,
      businessSenderDisplayName,
      env,
    );
  }

  return Object.freeze({
    identity,
    redisCommandBatchIsValid,
    redisOutbound,
    resendAuthOutbound,
    resendAuthPayloadIsValid,
    resendBusinessOutbound,
    resendBusinessPayloadIsValid,
    resendOutbound,
    resendPayloadIsValid,
  });
}
