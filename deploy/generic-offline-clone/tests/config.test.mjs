import assert from "node:assert/strict";
import { existsSync } from "node:fs";
import { mkdtemp, mkdir, readFile, symlink, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

import {
  buildWranglerConfig,
  loadDeployment,
  validateBackendRuntime,
  validateDeployment,
} from "../scripts/config.mjs";
import { buildComposeConfig } from "../scripts/compose.mjs";
import {
  deploy,
  parseDeployArguments,
} from "../scripts/deploy.mjs";
import { prepareDeployment } from "../scripts/prepare.mjs";
import {
  buildContainerRequest,
  securedResponse,
} from "../src/proxy.js";
import {
  containerInstanceName,
  normalizeContainerHealth,
  publicHealthPayload,
} from "../src/health.js";
import {
  BASIC_USERNAME,
  requestIsAuthorized,
  secretMatches,
  unauthorizedResponse,
} from "../src/auth.js";

const valid = {
  schema_version: "clawbench.generic-public-clone-deployment.v1",
  site_id: "alpha",
  site_label: "Alpha Clone",
  domain: "alpha.example.com",
  source_dir: "materials/alpha/clone",
  runtime: {
    command: ["python", "-m", "uvicorn", "app:app", "--port", "10000"],
    port: 10000,
    health_path: "/healthz",
    auth_mode: "local",
    python_requirements: ["fastapi==0.139.2"],
    support_paths: [],
  },
  cloudflare: { worker_name: "alpha-clone", compatibility_date: "2026-07-30", instance_type: "basic", max_instances: 1 },
};

test("generic Container instances reset with each deployment", () => {
  const first = containerInstanceName({
    SITE_ID: "petfinder",
    DEPLOYMENT_BUILD_ID: "1".repeat(40),
  });
  const second = containerInstanceName({
    SITE_ID: "petfinder",
    DEPLOYMENT_BUILD_ID: "2".repeat(40),
  });
  assert.equal(first, "clone-petfinder-111111111111");
  assert.equal(second, "clone-petfinder-222222222222");
  assert.notEqual(first, second);
  assert.ok(first.length <= 63);
});

test("generic deployment config produces one isolated Cloudflare container", () => {
  const config = buildWranglerConfig(validateDeployment(structuredClone(valid), "/tmp/repo"));
  assert.equal(config.name, "alpha-clone");
  assert.deepEqual(config.routes, [{ pattern: "alpha.example.com", custom_domain: true }]);
  assert.equal(config.containers[0].class_name, "GenericCloneContainer");
  assert.equal(config.containers[0].image_vars.SITE_ID, "alpha");
  assert.deepEqual(config.secrets.required, ["BASIC_AUTH_PASSWORD"]);
});

test("generated Cloudflare health identity binds exact candidate and deployment closures", () => {
  const identity = {
    candidate_sha256: "a".repeat(64),
    deployment_sha256: "b".repeat(64),
    build_id: "c".repeat(40),
  };
  const config = buildWranglerConfig(
    validateDeployment(structuredClone(valid), "/tmp/repo"),
    identity,
  );
  assert.equal(config.vars.CANDIDATE_SHA256, identity.candidate_sha256);
  assert.equal(config.vars.DEPLOYMENT_SHA256, identity.deployment_sha256);
  assert.equal(config.vars.DEPLOYMENT_BUILD_ID, identity.build_id);
  assert.equal(
    config.containers[0].image_vars.DEPLOYMENT_BUILD_ID,
    identity.build_id,
  );

  const invalid = buildWranglerConfig(
    validateDeployment(structuredClone(valid), "/tmp/repo"),
    { candidate_sha256: "not-a-hash", deployment_sha256: "also-invalid" },
  );
  assert.equal("CANDIDATE_SHA256" in invalid.vars, false);
  assert.equal("DEPLOYMENT_SHA256" in invalid.vars, false);
  assert.equal("DEPLOYMENT_BUILD_ID" in invalid.vars, false);
  assert.equal(
    "DEPLOYMENT_BUILD_ID" in invalid.containers[0].image_vars,
    false,
  );
});

test("public health exposes only selected application and release identity", () => {
  const payload = publicHealthPayload(
    {
      SITE_ID: "petfinder",
      CANDIDATE_SHA256: "a".repeat(64),
      DEPLOYMENT_SHA256: "b".repeat(64),
      CF_VERSION_METADATA: { id: "worker-version-1", extra: "not-public" },
      REDIS_REST_TOKEN: "not-public",
    },
    "petfinder-r5",
  );
  assert.deepEqual(payload, {
    ok: true,
    site_id: "petfinder",
    application_version: "petfinder-r5",
    candidate_sha256: "a".repeat(64),
    deployment_sha256: "b".repeat(64),
    worker_version_id: "worker-version-1",
  });
});

test("generic public review authentication uses the fixed Basic boundary", () => {
  const authorization = `Basic ${Buffer.from(
    `${BASIC_USERNAME}:review:password`,
    "utf8",
  ).toString("base64")}`;
  const request = new Request("https://tripit.example.test/", {
    headers: { Authorization: authorization },
  });
  assert.equal(requestIsAuthorized(request, "review:password"), true);
  assert.equal(requestIsAuthorized(request, "wrong"), false);
  const challenge = unauthorizedResponse("TripIt offline clone");
  assert.equal(challenge.status, 401);
  assert.equal(
    challenge.headers.get("WWW-Authenticate"),
    'Basic realm="TripIt offline clone", charset="UTF-8"',
  );
});

test("generic health binds the Worker response to the exact Container build", async () => {
  const buildId = "d".repeat(40);
  const environment = {
    SITE_ID: "tripit",
    DEPLOYMENT_BUILD_ID: buildId,
    CANDIDATE_SHA256: "a".repeat(64),
    DEPLOYMENT_SHA256: "b".repeat(64),
  };
  const request = new Request("https://tripit.example.test/healthz");
  const body = JSON.stringify({ ok: true, site_id: "tripit" });
  const current = normalizeContainerHealth(
    request,
    new Response(body, {
      headers: { "X-WebsiteBench-Build-ID": buildId },
    }),
    environment,
    body,
  );
  assert.equal(current.stale, false);
  assert.equal(current.response.status, 200);
  assert.equal(
    current.response.headers.get("X-WebsiteBench-Container-Build-ID"),
    buildId,
  );
  assert.deepEqual(await current.response.json(), {
    ok: true,
    site_id: "tripit",
    candidate_sha256: "a".repeat(64),
    deployment_sha256: "b".repeat(64),
  });

  for (const containerBuildId of [null, "e".repeat(40)]) {
    const headers = containerBuildId
      ? { "X-WebsiteBench-Container-Build-ID": containerBuildId }
      : {};
    const stale = normalizeContainerHealth(
      request,
      new Response(body, { headers }),
      environment,
      body,
    );
    assert.equal(stale.stale, true);
    assert.equal(stale.response.status, 503);
  }
});

test("generic container image receives the deployment build identity", async () => {
  const dockerfile = await readFile(
    resolve(import.meta.dirname, "..", "Dockerfile"),
    "utf8",
  );
  assert.match(dockerfile, /ARG DEPLOYMENT_BUILD_ID=/u);
  assert.match(dockerfile, /DEPLOYMENT_BUILD_ID=\$\{DEPLOYMENT_BUILD_ID\}/u);
});

test("generic deployment rejects path escapes and unpinned packages", () => {
  const escaped = structuredClone(valid);
  escaped.source_dir = "../secret";
  assert.throws(() => validateDeployment(escaped, "/tmp/repo"), /safe repository-relative/u);
  const unpinned = structuredClone(valid);
  unpinned.runtime.python_requirements = ["fastapi>=1"];
  assert.throws(() => validateDeployment(unpinned, "/tmp/repo"), /exact package==version pins/u);
  const reserved = structuredClone(valid);
  reserved.runtime.support_paths = [{ source: "support", destination: "runtime/injected.py" }];
  assert.throws(() => validateDeployment(reserved, "/tmp/repo"), /reserved runtime path/u);
  const overlapping = structuredClone(valid);
  overlapping.runtime.support_paths = [
    { source: "support-a", destination: "site" },
    { source: "support-b", destination: "site/nested" },
  ];
  assert.throws(() => validateDeployment(overlapping, "/tmp/repo"), /overlaps another support destination/u);
});

test("prepare copies only the configured clone into a deployment-owned context", async () => {
  const root = await mkdtemp(resolve(tmpdir(), "generic-clone-repo-"));
  const deployRoot = resolve(root, "deploy", "generic-offline-clone");
  const source = resolve(root, "materials", "alpha", "clone");
  await mkdir(resolve(source, "tests"), { recursive: true });
  await mkdir(resolve(root, "src", "websitebench", "local_clone_auth"), { recursive: true });
  await mkdir(resolve(root, "src", "clawbench", "local_clone_auth"), { recursive: true });
  await writeFile(resolve(source, "app.py"), "app = object()\n");
  await writeFile(resolve(source, "tests", "test_app.py"), "ignored\n");
  await writeFile(resolve(root, "src", "websitebench", "__init__.py"), "\n");
  await writeFile(resolve(root, "src", "websitebench", "local_clone_auth", "__init__.py"), "\n");
  await writeFile(resolve(root, "src", "clawbench", "__init__.py"), "\n");
  await writeFile(resolve(root, "src", "clawbench", "local_clone_auth", "__init__.py"), "\n");
  await mkdir(resolve(root, "src", "websitebench", "site_backend"), { recursive: true });
  await mkdir(resolve(root, "src", "clawbench", "site_backend"), { recursive: true });
  await writeFile(resolve(root, "src", "websitebench", "site_backend", "__init__.py"), "\n");
  await writeFile(resolve(root, "src", "clawbench", "site_backend", "__init__.py"), "\n");
  await mkdir(deployRoot, { recursive: true });
  const configPath = resolve(deployRoot, "deployment.json");
  await writeFile(configPath, `${JSON.stringify(valid)}\n`);
  const contextRoot = resolve(deployRoot, ".container-context");
  const generatedConfig = resolve(deployRoot, "wrangler.generated.jsonc");

  const result = await prepareDeployment(configPath, { repositoryRoot: root, deployRoot, contextRoot, generatedConfig });

  assert.equal(result.status, "prepared");
  assert.match(await readFile(resolve(contextRoot, "clone", "app.py"), "utf8"), /object/u);
  await assert.rejects(readFile(resolve(contextRoot, "clone", "tests", "test_app.py"), "utf8"));
  assert.equal(JSON.parse(await readFile(generatedConfig, "utf8")).vars.SITE_ID, "alpha");
  assert.equal(
    JSON.parse(await readFile(generatedConfig, "utf8")).vars.CANDIDATE_SHA256,
    result.candidate_sha256,
  );
  assert.equal(
    JSON.parse(await readFile(generatedConfig, "utf8")).vars.DEPLOYMENT_SHA256,
    result.deployment_sha256,
  );
  await writeFile(
    resolve(root, "src", "websitebench", "site_backend", "__init__.py"),
    "# changed shared runtime\n",
  );
  const changed = await prepareDeployment(configPath, {
    repositoryRoot: root,
    deployRoot,
    contextRoot,
    generatedConfig,
    checkOnly: true,
  });
  assert.equal(changed.candidate_sha256, result.candidate_sha256);
  assert.notEqual(changed.deployment_sha256, result.deployment_sha256);
});

test("real deployment requires explicit yes", () => {
  assert.equal(parseDeployArguments(["--dry-run"]).dryRun, true);
  assert.equal(parseDeployArguments(["--yes"]).dryRun, false);
  assert.throws(
    () => parseDeployArguments(["--authorization", "approval.json"]),
    /unknown argument/u,
  );
  assert.throws(() => parseDeployArguments(["--unknown"]), /unknown argument/u);
});

test("deploy module can be imported from a Unicode Windows path without running CLI", () => {
  assert.equal(typeof deploy, "function");
  assert.equal(typeof parseDeployArguments, "function");
});

test("public-demo deploy runs wrangler deploy without an advisory release-gate check", async () => {
  // A cloudflare-review deploy issues exactly one command -- wrangler deploy
  // via the Node runtime -- after site-specific preparation.
  const prepared = {
    site_id: "alpha",
    deployment_profile: "cloudflare-review",
    domain: "alpha.example.com",
    deployment_sha256: "a".repeat(64),
    candidate_sha256: "b".repeat(64),
  };
  const calls = [];
  await deploy(
    {
      config: "ignored.json",
      dryRun: false,
    },
    {
      prepare: async () => prepared,
      runCommand: async (command, args) => calls.push([command, args]),
    },
  );
  assert.equal(calls.length, 1);
  assert.equal(calls[0][0], process.execPath);
  assert.match(calls[0][1][0], /wrangler[\\/]bin[\\/]wrangler\.js$/u);
  assert.equal(calls[0][1][1], "deploy");
  assert.equal(calls[0][1].includes("--dry-run"), false);
});

test("prepare rejects symbolic links in copied clone content", async () => {
  const root = await mkdtemp(resolve(tmpdir(), "generic-clone-symlink-"));
  const deployRoot = resolve(root, "deploy", "generic-offline-clone");
  const source = resolve(root, "materials", "alpha", "clone");
  await mkdir(source, { recursive: true });
  await mkdir(deployRoot, { recursive: true });
  await symlink("/etc/passwd", resolve(source, "escaped-link"));
  const configPath = resolve(deployRoot, "deployment.json");
  await writeFile(configPath, `${JSON.stringify(valid)}\n`);

  await assert.rejects(
    prepareDeployment(configPath, {
      repositoryRoot: root,
      deployRoot,
      contextRoot: resolve(deployRoot, ".container-context"),
      generatedConfig: resolve(deployRoot, "wrangler.generated.jsonc"),
    }),
    /contains a symbolic link/u,
  );
});

test("example deployment remains valid", async () => {
  const path = new URL("../deployment.example.json", import.meta.url);
  const value = await loadDeployment(path.pathname);
  assert.equal(value.site_id, "taskrabbit");
  assert.equal(value.compatibility, "v1");
  assert.equal(value.backend_contract.deployment.profiles["cloudflare-review"].persistence, "ephemeral-reset");
});

test("v2 descriptor loads its sole backend runtime contract on a Unicode Windows path", async () => {
  const path = new URL("../deployment.v2.example.json", import.meta.url);
  const value = await loadDeployment(path);
  assert.equal(value.compatibility, "v2");
  assert.equal(value.backend_contract.site.id, "taskrabbit");
  assert.equal(value.deployment_profile, "cloudflare-review");
  const wrangler = buildWranglerConfig(value);
  assert.equal(wrangler.vars.DATABASE_PERSISTENCE, "ephemeral-reset");
  assert.equal(wrangler.vars.MAIL_ADAPTER, "redis-resend");
});

// Site descriptors and their materials/<site>/backend runtimes are only
// present in checkouts that carry that site; skip instead of failing when a
// single-site pipeline checkout does not include them.
const descriptorPresent = (name) =>
  existsSync(fileURLToPath(new URL(`../${name}`, import.meta.url)));

test("edX v2 descriptor keeps the public review payment flow in the local sandbox", {
  skip: !descriptorPresent("deployment.edx.v2.json"),
}, async () => {
  const path = new URL("../deployment.edx.v2.json", import.meta.url);
  const deployment = await loadDeployment(path);
  const wrangler = buildWranglerConfig(deployment);

  assert.equal(deployment.compatibility, "v2");
  assert.equal(deployment.site_id, "edx");
  assert.equal(deployment.domain, "edx.website-bench.com");
  assert.equal(deployment.deployment_profile, "cloudflare-review");
  assert.equal(wrangler.name, "websitebench-edx-demo");
  assert.equal(wrangler.vars.PAYMENT_ADAPTER, "local-sandbox");
  assert.equal(wrangler.vars.MAIL_SENDER_DISPLAY_NAME, "edX Learning Clone");
  assert.equal(
    JSON.parse(wrangler.vars.MAIL_TEMPLATES)["enrollment-receipt"].template_id,
    "edx.enrollment-receipt.v1",
  );
  assert.equal("STRIPE_PUBLIC_ORIGIN" in wrangler.vars, false);
  assert.equal("STRIPE_RETURN_PATH" in wrangler.vars, false);
  assert.equal("STRIPE_WEBHOOK_PATH" in wrangler.vars, false);
  assert.equal(wrangler.containers[0].image_vars.PAYMENT_ADAPTER, "local-sandbox");
  assert.deepEqual(wrangler.routes, [{ pattern: "edx.website-bench.com", custom_domain: true }]);
});

test("Petfinder v2 descriptor derives Resend and local sandbox from its runtime", {
  skip: !descriptorPresent("deployment.petfinder.v2.json"),
}, async () => {
  const path = new URL("../deployment.petfinder.v2.json", import.meta.url);
  const deployment = await loadDeployment(path);
  const wrangler = buildWranglerConfig(deployment);

  assert.equal(deployment.compatibility, "v2");
  assert.equal(deployment.site_id, "petfinder");
  assert.equal(deployment.domain, "petfinder.website-bench.com");
  assert.deepEqual(deployment.runtime.support_paths, [{
    source: "materials/petfinder/clone/data",
    destination: "public-indexes",
  }]);
  assert.equal(wrangler.vars.MAIL_ADAPTER, "redis-resend");
  assert.equal(wrangler.vars.PAYMENT_ADAPTER, "local-sandbox");
  assert.equal(
    JSON.parse(wrangler.vars.MAIL_TEMPLATES)["support-receipt"].template_id,
    "petfinder.support-receipt.v1",
  );
  assert.equal("STRIPE_RETURN_PATH" in wrangler.vars, false);
  // cloudflare-review serves registration behind basic auth and opts out of
  // Turnstile, so no keypair is demanded and the switch is explicit in vars.
  assert.deepEqual(wrangler.secrets.required, [
    "BASIC_AUTH_PASSWORD",
    "REDIS_REST_URL",
    "REDIS_REST_TOKEN",
    "RESEND_API_KEY",
    "RESEND_FROM_EMAIL",
  ]);
  assert.equal(wrangler.vars.AUTH_REQUIRE_TURNSTILE, "false");
  assert.equal(wrangler.vars.TURNSTILE_SITE_KEY, undefined);
});

test("TripIt v2 descriptor derives Resend mail and Stripe test checkout", async () => {
  const path = new URL("../deployment.tripit.v2.json", import.meta.url);
  const deployment = await loadDeployment(path);
  const wrangler = buildWranglerConfig(deployment);

  assert.equal(deployment.compatibility, "v2");
  assert.equal(deployment.site_id, "tripit");
  assert.equal(deployment.domain, "tripit.website-bench.com");
  assert.equal(deployment.deployment_profile, "cloudflare-review");
  assert.equal(wrangler.name, "websitebench-tripit-demo");
  assert.deepEqual(wrangler.routes, [
    { pattern: "tripit.website-bench.com", custom_domain: true },
  ]);

  // The hosted review profile uses Stripe test mode while offline-harbor keeps
  // the deterministic local sandbox. Provider secrets stay at the edge.
  assert.equal(wrangler.vars.PAYMENT_ADAPTER, "stripe-test");
  assert.equal(wrangler.containers[0].image_vars.PAYMENT_ADAPTER, "stripe-test");
  assert.equal(wrangler.vars.STRIPE_PUBLIC_ORIGIN, "https://tripit.website-bench.com");
  assert.equal(wrangler.vars.STRIPE_RETURN_PATH, "/pro/stripe-return");
  assert.equal(wrangler.vars.STRIPE_WEBHOOK_PATH, "/api/stripe/webhook");

  assert.equal(wrangler.vars.MAIL_ADAPTER, "redis-resend");
  assert.equal(wrangler.vars.MAIL_SENDER_DISPLAY_NAME, "TripIt");
  assert.equal(wrangler.vars.DATABASE_PERSISTENCE, "ephemeral-reset");
  assert.equal(
    JSON.parse(wrangler.vars.MAIL_TEMPLATES)["pro-receipt"].template_id,
    "tripit.pro-receipt.v1",
  );
  assert.equal(
    JSON.parse(wrangler.vars.MAIL_TEMPLATES)["import-receipt"].template_id,
    "tripit.import-receipt.v1",
  );
  assert.equal(
    JSON.parse(wrangler.vars.MAIL_TEMPLATES)["share-invite"].template_id,
    "tripit.share-invite.v1",
  );

  assert.deepEqual(wrangler.secrets.required, [
    "BASIC_AUTH_PASSWORD",
    "REDIS_REST_URL",
    "REDIS_REST_TOKEN",
    "RESEND_API_KEY",
    "RESEND_FROM_EMAIL",
    "PUBLIC_CLONE_AUTH_SMOKE_SECRET",
    "STRIPE_TEST_SECRET_KEY",
    "STRIPE_TEST_WEBHOOK_SECRET",
  ]);
  assert.equal(wrangler.vars.AUTH_REQUIRE_TURNSTILE, "false");
  assert.equal(wrangler.vars.TURNSTILE_SITE_KEY, undefined);
});

test("v2 deployment delegates runtime validation to the canonical Python contract", async () => {
  const path = new URL("../backend-runtime.example.json", import.meta.url);
  const runtime = JSON.parse(await readFile(path, "utf8"));
  const deployment = { deployment_profile: "cloudflare-review" };
  assert.equal(
    validateBackendRuntime(structuredClone(runtime), deployment).site.id,
    "taskrabbit",
  );

  const invalidCases = [
    (value) => {
      value.database.legacy_unbound_migration = "false";
    },
    (value) => {
      value.mail.purposes.registration.required_variables = ["code"];
    },
    (value) => {
      value.payments.local_sandbox.scenarios[0].outcome = "maybe";
    },
    (value) => {
      value.deployment.profiles["docker-volume"].persistence = "shared";
    },
  ];
  for (const mutate of invalidCases) {
    const invalid = structuredClone(runtime);
    mutate(invalid);
    assert.throws(
      () => validateBackendRuntime(invalid, deployment),
      /canonical backend runtime rejected contract/u,
    );
  }
});

test("v2 runtime validation never reads the legacy ClawBench Python override", async () => {
  const path = new URL("../backend-runtime.example.json", import.meta.url);
  const runtime = JSON.parse(await readFile(path, "utf8"));
  const previousLegacy = process.env.CLAWBENCH_PYTHON;
  const previousCurrent = process.env.WEBSITEBENCH_PYTHON;
  process.env.CLAWBENCH_PYTHON = process.execPath;
  delete process.env.WEBSITEBENCH_PYTHON;
  try {
    assert.equal(
      validateBackendRuntime(runtime, { deployment_profile: "cloudflare-review" })
        .site.id,
      "taskrabbit",
    );
  } finally {
    if (previousLegacy === undefined) delete process.env.CLAWBENCH_PYTHON;
    else process.env.CLAWBENCH_PYTHON = previousLegacy;
    if (previousCurrent === undefined) delete process.env.WEBSITEBENCH_PYTHON;
    else process.env.WEBSITEBENCH_PYTHON = previousCurrent;
  }
});

test("docker-volume compose uses a site-exclusive named volume and internal network", async () => {
  const path = new URL("../deployment.v2.example.json", import.meta.url);
  const first = await loadDeployment(path);
  first.deployment_profile = "docker-volume";
  const firstCompose = buildComposeConfig(first);
  assert.equal(firstCompose.volumes["site-data"].name, "websitebench-taskrabbit-data");
  assert.equal(
    firstCompose.services.app.environment.WEBSITEBENCH_SITE_BACKEND_RUNTIME,
    "/app/runtime/backend-runtime.json",
  );
  assert.equal(
    Object.keys(firstCompose.services.app.environment).some(
      (name) => name.startsWith("CLAWBENCH_"),
    ),
    false,
  );
  assert.equal(firstCompose.networks["site-internal"].internal, true);
  assert.equal(firstCompose.networks["effects-egress"].internal, undefined);
  assert.deepEqual(firstCompose.services.app.volumes, ["site-data:/data"]);
  assert.deepEqual(firstCompose.services.app.networks, ["site-internal"]);
  assert.equal(firstCompose.services["effects-gateway"].volumes, undefined);
  assert.ok(firstCompose.services["effects-gateway"].networks["effects-egress"]);
  assert.equal(
    firstCompose.services.app.environment.PUBLIC_CLONE_AUTH_EFFECTS_TOKEN,
    firstCompose.services["effects-gateway"].environment.EFFECTS_INTERNAL_TOKEN,
  );
  assert.equal(
    firstCompose.services.app.environment.WEBSITEBENCH_RESEND_INTERNAL_ORIGIN,
    "http://resend.internal:8080",
  );
  assert.equal(
    firstCompose.services["effects-gateway"].environment.MAIL_SENDER_DISPLAY_NAME,
    first.backend_contract.mail.sender.display_name,
  );
  assert.match(
    firstCompose.services.app.environment.PUBLIC_CLONE_AUTH_MAIL_TEMPLATE,
    /\$\$\{code\}/u,
  );
  assert.match(
    firstCompose.services["effects-gateway"].environment.MAIL_TEMPLATES,
    /\$\$\{minutes\}/u,
  );
  assert.deepEqual(
    firstCompose.services["effects-gateway"].ports,
    ["127.0.0.1::8080"],
  );

  const second = structuredClone(first);
  second.site_id = "another-site";
  second.site_label = "Another Site";
  second.backend_contract.site = { id: "another-site", label: "Another Site" };
  const secondCompose = buildComposeConfig(second);
  assert.notEqual(
    firstCompose.volumes["site-data"].name,
    secondCompose.volumes["site-data"].name,
  );
  assert.notEqual(
    firstCompose.networks["site-internal"].name,
    secondCompose.networks["site-internal"].name,
  );
  assert.equal("site_id" in JSON.parse(await readFile(path, "utf8")), false);
});

test("v2 proxy strips both header namespaces and emits only WebsiteBench", () => {
  const request = new Request("https://alpha.example.test/api/stripe/webhook", {
    headers: {
      "CF-Connecting-IP": "198.51.100.9",
      "X-ClawBench-Client-IP": "attacker-legacy",
      "X-WebsiteBench-Client-IP": "attacker-current",
      "X-ClawBench-Stripe-Verified": "1",
      "X-WebsiteBench-Stripe-Verified": "1",
      "X-WebsiteBench-Registration-Smoke-Secret": "attacker-secret",
      "X-WebsiteBench-Registration-Smoke-Verified": "1",
    },
  });
  const forwarded = buildContainerRequest(request, {
    registrationSmokeVerified: true,
    stripeWebhookVerified: true,
  });
  assert.equal(
    forwarded.headers.get("X-WebsiteBench-Client-IP"),
    "198.51.100.9",
  );
  assert.equal(
    forwarded.headers.get("X-WebsiteBench-Stripe-Verified"),
    "1",
  );
  assert.equal(
    forwarded.headers.get("X-WebsiteBench-Registration-Smoke-Verified"),
    "1",
  );
  assert.equal(
    forwarded.headers.has("X-WebsiteBench-Registration-Smoke-Secret"),
    false,
  );
  assert.equal(forwarded.headers.has("X-ClawBench-Client-IP"), false);
  assert.equal(forwarded.headers.has("X-ClawBench-Stripe-Verified"), false);

  const response = securedResponse(new Response("ok"), {
    CF_VERSION_METADATA: { id: "version-1" },
    DEPLOYMENT_BUILD_ID: "revision-1",
    PAYMENT_ADAPTER: "stripe-test",
  });
  assert.equal(
    response.headers.get("X-WebsiteBench-Worker-Version"),
    "version-1",
  );
  assert.equal(response.headers.has("X-ClawBench-Worker-Version"), false);
  assert.equal(response.headers.get("X-WebsiteBench-Build-ID"), "revision-1");
  assert.equal(response.headers.get("X-WebsiteBench-Payment-Mode"), "stripe-test");
});

test("registration smoke secrets are compared exactly", () => {
  assert.equal(secretMatches("correct-secret", "correct-secret"), true);
  assert.equal(secretMatches("wrong-secret", "correct-secret"), false);
  assert.equal(secretMatches("", ""), false);
});
