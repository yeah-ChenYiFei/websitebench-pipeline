import { readFile } from "node:fs/promises";
import { spawnSync } from "node:child_process";
import { delimiter, dirname, relative, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";

const SCRIPT_ROOT = dirname(fileURLToPath(import.meta.url));
export const DEPLOY_ROOT = resolve(SCRIPT_ROOT, "..");
export const REPOSITORY_ROOT = resolve(DEPLOY_ROOT, "..", "..");
export const CONTEXT_ROOT = resolve(DEPLOY_ROOT, ".container-context");
export const GENERATED_CONFIG = resolve(DEPLOY_ROOT, "wrangler.generated.jsonc");
export const GENERATED_COMPOSE = resolve(DEPLOY_ROOT, "compose.generated.json");

const PATH_PART = /^[A-Za-z0-9._@+-]+$/u;
const SITE_ID = /^[a-z0-9]+(?:-[a-z0-9]+)*$/u;
const DOMAIN = /^(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,63}$/u;
const REQUIREMENT = /^[A-Za-z0-9_.-]+(?:\[[A-Za-z0-9_,.-]+\])?==[A-Za-z0-9_.+!-]+$/u;
const RUNTIME_V1 = "clawbench.generic-public-clone-deployment.v1";
const RUNTIME_V2 = "websitebench.generic-public-clone-deployment.v2";

function canonicalBackendRuntime(value) {
  const configured =
    value?.schema_version === "clawbench.site-backend-runtime.v1"
      ? process.env.CLAWBENCH_PYTHON
      : process.env.WEBSITEBENCH_PYTHON;
  const virtualEnvironmentPython = resolve(
    REPOSITORY_ROOT,
    ".venv",
    process.platform === "win32" ? "Scripts/python.exe" : "bin/python",
  );
  const candidates = [
    ...(configured ? [configured] : []),
    virtualEnvironmentPython,
    ...(process.platform === "win32" ? ["python"] : ["python3", "python"]),
  ];
  const env = {
    ...process.env,
    PYTHONPATH: [
      resolve(REPOSITORY_ROOT, "src"),
      ...(process.env.PYTHONPATH ? [process.env.PYTHONPATH] : []),
    ].join(delimiter),
  };
  for (const command of candidates) {
    const validationModule =
      value?.schema_version === "clawbench.site-backend-runtime.v1"
        ? "clawbench.site_backend.validation_cli"
        : "websitebench.site_backend.validation_cli";
    const result = spawnSync(
      command,
      ["-m", validationModule],
      {
        encoding: "utf8",
        env,
        input: JSON.stringify(value),
        maxBuffer: 4 * 1024 * 1024,
        windowsHide: true,
      },
    );
    if (result.error?.code === "ENOENT") continue;
    if (result.error) {
      throw new TypeError(
        `canonical backend runtime validator failed to start: ${result.error.message}`,
      );
    }
    if (result.status !== 0) {
      const detail = String(result.stderr || "").trim() || "invalid runtime";
      throw new TypeError(`canonical backend runtime rejected contract: ${detail}`);
    }
    try {
      return JSON.parse(result.stdout);
    } catch (error) {
      throw new TypeError(
        `canonical backend runtime validator returned invalid JSON: ${error.message}`,
      );
    }
  }
  throw new TypeError(
    "Python is required for canonical backend runtime validation",
  );
}

export function staysWithin(parent, child) {
  const path = relative(parent, child);
  return path === "" || (!path.startsWith(`..${sep}`) && path !== "..");
}

function validateRelativePath(value, label) {
  if (
    typeof value !== "string" ||
    !value ||
    value.startsWith("/") ||
    value.includes("\\") ||
    value.split("/").some((part) => !part || part === ".." || !PATH_PART.test(part))
  ) {
    throw new TypeError(`${label} must be a safe repository-relative path`);
  }
}

export function filesystemPath(value) {
  if (value instanceof URL) return fileURLToPath(value);
  if (typeof value !== "string") throw new TypeError("path must be a string or file URL");
  if (value.startsWith("file:")) return fileURLToPath(new URL(value));
  if (process.platform === "win32" && /^\/[A-Za-z]:\//u.test(value)) {
    return decodeURIComponent(value.slice(1));
  }
  return decodeURIComponent(value);
}

function exactKeys(value, expected, label) {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new TypeError(`${label} must be an object`);
  if (JSON.stringify(Object.keys(value).sort()) !== JSON.stringify([...expected].sort())) {
    throw new TypeError(`${label} has missing or unknown fields`);
  }
}

function validateRuntimeDefinition(runtime, { legacy }) {
  const expected = legacy
    ? ["auth_mode", "command", "health_path", "port", "python_requirements", "support_paths"]
    : ["command", "health_path", "port", "python_requirements", "support_paths"];
  exactKeys(runtime, expected, "runtime");
  if (!Array.isArray(runtime.command) || runtime.command.length < 1 || runtime.command.length > 32 || runtime.command.some((part) => typeof part !== "string" || !part || /[\0\r\n]/u.test(part))) {
    throw new TypeError("runtime.command must be a non-empty safe argv array");
  }
  if (runtime.port !== 10000) throw new TypeError("runtime.port must be 10000");
  if (typeof runtime.health_path !== "string" || !runtime.health_path.startsWith("/") || /[?#\r\n]/u.test(runtime.health_path)) throw new TypeError("invalid health_path");
  if (legacy && !["local", "redis-resend"].includes(runtime.auth_mode)) throw new TypeError("invalid auth_mode");
  if (!Array.isArray(runtime.python_requirements) || runtime.python_requirements.some((item) => !REQUIREMENT.test(item))) throw new TypeError("python_requirements must use exact package==version pins");
  if (!Array.isArray(runtime.support_paths)) throw new TypeError("support_paths must be an array");
  const supportDestinations = [];
  for (const [index, item] of runtime.support_paths.entries()) {
    exactKeys(item, ["destination", "source"], `support_paths[${index}]`);
    validateRelativePath(item.source, `support_paths[${index}].source`);
    validateRelativePath(item.destination, `support_paths[${index}].destination`);
    if (["clone", "data", "repository-src", "runtime"].includes(item.destination.split("/", 1)[0])) {
      throw new TypeError(`support_paths[${index}].destination targets a reserved runtime path`);
    }
    if (supportDestinations.some((path) => item.destination === path || item.destination.startsWith(`${path}/`) || path.startsWith(`${item.destination}/`))) {
      throw new TypeError(`support_paths[${index}].destination overlaps another support destination`);
    }
    supportDestinations.push(item.destination);
  }
}

function validateCloudflare(cloudflare) {
  exactKeys(cloudflare, ["worker_name", "compatibility_date", "instance_type", "max_instances"], "cloudflare");
  if (!SITE_ID.test(cloudflare.worker_name) || cloudflare.worker_name.length > 63) throw new TypeError("invalid worker_name");
  if (!/^\d{4}-\d{2}-\d{2}$/u.test(cloudflare.compatibility_date)) throw new TypeError("invalid compatibility_date");
  if (!["dev", "basic", "standard"].includes(cloudflare.instance_type)) throw new TypeError("invalid instance_type");
  if (!Number.isInteger(cloudflare.max_instances) || cloudflare.max_instances < 1 || cloudflare.max_instances > 10) throw new TypeError("invalid max_instances");
}

export function validateDeployment(value, repositoryRoot = REPOSITORY_ROOT) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new TypeError("deployment config must be an object");
  }
  const legacy = value.schema_version === RUNTIME_V1;
  const modern = value.schema_version === RUNTIME_V2;
  if (!legacy && !modern) throw new TypeError("unsupported deployment schema_version");
  const topKeys = Object.keys(value).sort();
  const expected = legacy
    ? ["cloudflare", "domain", "runtime", "schema_version", "site_id", "site_label", "source_dir"]
    : ["backend_runtime", "cloudflare", "deployment_profile", "runtime", "schema_version", "source_dir"];
  if (JSON.stringify(topKeys) !== JSON.stringify(expected)) {
    throw new TypeError("deployment config has missing or unknown top-level fields");
  }
  if (legacy) {
    if (!SITE_ID.test(value.site_id)) throw new TypeError("invalid site_id");
    if (typeof value.site_label !== "string" || !value.site_label.trim() || value.site_label.length > 120) {
      throw new TypeError("invalid site_label");
    }
    if (!DOMAIN.test(value.domain)) throw new TypeError("invalid public domain");
  }
  validateRelativePath(value.source_dir, "source_dir");
  const source = resolve(repositoryRoot, value.source_dir);
  if (!staysWithin(repositoryRoot, source)) throw new TypeError("source_dir escaped repository");
  validateRuntimeDefinition(value.runtime, { legacy });
  validateCloudflare(value.cloudflare);
  if (modern) {
    validateRelativePath(value.backend_runtime, "backend_runtime");
    const backendPath = resolve(repositoryRoot, value.backend_runtime);
    if (!staysWithin(repositoryRoot, backendPath)) throw new TypeError("backend_runtime escaped repository");
    if (!["cloudflare-review", "docker-volume"].includes(value.deployment_profile)) throw new TypeError("invalid deployment_profile");
  }
  return value;
}

export function validateBackendRuntime(value) {
  // The Python deep module is the sole authority. Keeping deployment tooling
  // on this path prevents a second validator from silently accepting a
  // contract the runtime itself will reject.
  return canonicalBackendRuntime(value);
}

export async function loadDeployment(path, repositoryRoot = REPOSITORY_ROOT) {
  const resolvedPath = resolve(filesystemPath(path));
  let value;
  try {
    value = JSON.parse(await readFile(resolvedPath, "utf8"));
  } catch (error) {
    throw new TypeError(`cannot read deployment config ${resolvedPath}: ${error.message}`);
  }
  const root = resolve(repositoryRoot);
  const deployment = validateDeployment(value, root);
  if (deployment.schema_version === RUNTIME_V2) {
    const runtimePath = resolve(root, deployment.backend_runtime);
    let backend;
    try {
      backend = JSON.parse(await readFile(runtimePath, "utf8"));
    } catch (error) {
      throw new TypeError(`cannot read backend runtime ${runtimePath}: ${error.message}`);
    }
    const backendContract = validateBackendRuntime(backend, deployment);
    const publicOrigin = new URL(backendContract.site.public_origin);
    return {
      ...deployment,
      site_id: backendContract.site.id,
      site_label: backendContract.site.label,
      domain: publicOrigin.hostname,
      compatibility: "v2",
      backend_contract: backendContract,
    };
  }
  return {
    ...deployment,
    compatibility: "v1",
    deployment_profile: "cloudflare-review",
    backend_contract: {
      schema_version: "compatibility.v1",
      site: {
        id: deployment.site_id,
        label: deployment.site_label,
        public_origin: `https://${deployment.domain}`,
      },
      mail: { sender: { display_name: deployment.site_label, address_env: "RESEND_FROM_EMAIL" }, purposes: {} },
      payments: { default_adapter: "local-sandbox", currency: "USD", stripe_test: null },
      deployment: {
        profiles: {
          "cloudflare-review": {
            persistence: "ephemeral-reset",
            mail_adapter: deployment.runtime.auth_mode === "redis-resend" ? "redis-resend" : "local-outbox",
            payment_adapter: "local-sandbox",
          },
        },
      },
    },
  };
}

export function buildWranglerConfig(deployment, releaseIdentity = {}) {
  const profileName = deployment.deployment_profile || "cloudflare-review";
  const compatibilityContract = deployment.schema_version === RUNTIME_V1
    ? {
        mail: {
          sender: {
            display_name: deployment.site_label,
            address_env: "RESEND_FROM_EMAIL",
          },
          purposes: {},
        },
        payments: { currency: "USD", stripe_test: null },
        deployment: {
          profiles: {
            "cloudflare-review": {
              persistence: "ephemeral-reset",
              mail_adapter: deployment.runtime.auth_mode === "redis-resend" ? "redis-resend" : "local-outbox",
              payment_adapter: "local-sandbox",
            },
          },
        },
      }
    : null;
  const contract = deployment.backend_contract || compatibilityContract;
  const profile = contract?.deployment?.profiles?.[profileName];
  if (!profile) throw new TypeError("deployment is missing a resolved backend profile");
  if (profileName !== "cloudflare-review") throw new TypeError("Wrangler config requires cloudflare-review");
  const remoteAuth = profile.mail_adapter === "redis-resend";
  const stripeTest = profile.payment_adapter === "stripe-test";
  const stripe = contract.payments.stripe_test;
  const registration = contract.mail?.purposes?.registration;
  const mailTemplates = JSON.stringify(contract.mail?.purposes || {});
  const registrationTemplate = registration
    ? JSON.stringify({
        sender_display_name: contract.mail.sender.display_name,
        subject: registration.subject,
        lead: registration.lead,
        body: registration.body,
        expiry: registration.expiry,
        footer: registration.footer,
      })
    : "";
  const deploymentBuildId = /^[0-9a-f]{40}$/u.test(
    releaseIdentity.build_id || "",
  )
    ? releaseIdentity.build_id
    : null;
  const registrationSmoke = remoteAuth && deployment.site_id === "tripit";
  return {
    $schema: "./node_modules/wrangler/config-schema.json",
    name: deployment.cloudflare.worker_name,
    main: "./src/index.js",
    compatibility_date: deployment.cloudflare.compatibility_date,
    secrets: {
      required: [
        "BASIC_AUTH_PASSWORD",
        ...(remoteAuth ? ["REDIS_REST_URL", "REDIS_REST_TOKEN", "RESEND_API_KEY", contract.mail.sender.address_env] : []),
        ...(registrationSmoke ? ["PUBLIC_CLONE_AUTH_SMOKE_SECRET"] : []),
        ...(stripeTest ? [stripe.secret_key_env, stripe.webhook_secret_env] : []),
      ],
    },
    vars: {
      PUBLIC_HOST: deployment.domain,
      SITE_ID: deployment.site_id,
      SITE_LABEL: deployment.site_label,
      HEALTH_PATH: deployment.runtime.health_path,
      BACKEND_PROFILE: profileName,
      DATABASE_PERSISTENCE: profile.persistence,
      MAIL_ADAPTER: profile.mail_adapter,
      MAIL_SENDER_ADDRESS_ENV: contract.mail.sender.address_env,
      MAIL_SENDER_DISPLAY_NAME: contract.mail.sender.display_name,
      MAIL_TEMPLATES: mailTemplates,
      PAYMENT_ADAPTER: profile.payment_adapter,
      PAYMENT_CURRENCY: contract.payments.currency,
      ...(deploymentBuildId
        ? { DEPLOYMENT_BUILD_ID: deploymentBuildId }
        : {}),
      // This generator refuses any profile but cloudflare-review above, and that
      // profile serves registration behind the shared basic-auth boundary, so
      // Turnstile is opted out rather than demanding a keypair per deployment.
      // Emitted explicitly so the choice is visible in the generated config;
      // drop it and restore TURNSTILE_SECRET_KEY above to turn the boundary on.
      ...(remoteAuth ? { AUTH_REQUIRE_TURNSTILE: "false" } : {}),
      ...(/^[0-9a-f]{64}$/u.test(releaseIdentity.candidate_sha256 || "")
        ? { CANDIDATE_SHA256: releaseIdentity.candidate_sha256 }
        : {}),
      ...(/^[0-9a-f]{64}$/u.test(releaseIdentity.deployment_sha256 || "")
        ? { DEPLOYMENT_SHA256: releaseIdentity.deployment_sha256 }
        : {}),
      ...(stripeTest ? {
        STRIPE_PUBLIC_ORIGIN: stripe.public_origin,
        STRIPE_RETURN_PATH: stripe.return_path,
        STRIPE_WEBHOOK_PATH: stripe.webhook_path,
        STRIPE_SECRET_KEY_ENV: stripe.secret_key_env,
        STRIPE_WEBHOOK_SECRET_ENV: stripe.webhook_secret_env,
        STRIPE_MAX_LINE_ITEMS: String(stripe.max_line_items),
      } : {}),
      ...(remoteAuth ? { MAIL_REGISTRATION_TEMPLATE: registrationTemplate } : {}),
    },
    version_metadata: { binding: "CF_VERSION_METADATA" },
    workers_dev: false,
    preview_urls: false,
    routes: [{ pattern: deployment.domain, custom_domain: true }],
    containers: [
      {
        class_name: "GenericCloneContainer",
        image: "./Dockerfile",
        image_build_context: ".",
        image_vars: {
          SITE_ID: deployment.site_id,
          SITE_LABEL: deployment.site_label,
          AUTH_MODE: remoteAuth ? "redis-resend" : "local",
          BACKEND_PROFILE: profileName,
          DATABASE_PERSISTENCE: profile.persistence,
          PAYMENT_ADAPTER: profile.payment_adapter,
          ...(deploymentBuildId
            ? { DEPLOYMENT_BUILD_ID: deploymentBuildId }
            : {}),
          MAIL_SENDER_ADDRESS_ENV: contract.mail.sender.address_env,
          MAIL_TEMPLATES: mailTemplates,
          ...(remoteAuth ? { MAIL_REGISTRATION_TEMPLATE: registrationTemplate } : {}),
        },
        max_instances: deployment.cloudflare.max_instances,
        instance_type: deployment.cloudflare.instance_type,
      },
    ],
    durable_objects: {
      bindings: [{ name: "SITE_CONTAINER", class_name: "GenericCloneContainer" }],
    },
    migrations: [{ tag: "v1", new_sqlite_classes: ["GenericCloneContainer"] }],
    observability: { enabled: true },
  };
}
