import { createHash } from "node:crypto";
import { cp, lstat, mkdir, readFile, readdir, rm, writeFile } from "node:fs/promises";
import { dirname, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import {
  CONTEXT_ROOT,
  DEPLOY_ROOT,
  GENERATED_COMPOSE,
  GENERATED_CONFIG,
  REPOSITORY_ROOT,
  buildWranglerConfig,
  loadDeployment,
  staysWithin,
} from "./config.mjs";
import { buildComposeConfig } from "./compose.mjs";

const SCRIPT_PATH = fileURLToPath(import.meta.url);
const EXCLUDED = new Set([".git", ".pytest_cache", ".runtime", "__pycache__", "data", "node_modules", "runtime", "runtime-data", "tests"]);

function shouldCopy(
  sourceRoot,
  sourcePath,
  excludeLegacyClawbench = false,
) {
  const path = relative(sourceRoot, sourcePath);
  if (path === "") return true;
  const parts = path.split(/[\\/]/u);
  return !parts.some((part) => EXCLUDED.has(part))
    && !(excludeLegacyClawbench && parts[0] === "clawbench");
}

async function assertReadableTree(path, label) {
  const stat = await lstat(path);
  if (stat.isSymbolicLink() || !stat.isDirectory()) throw new TypeError(`${label} must be a real directory: ${path}`);
}

async function assertNoCopiedSymlinks(
  sourceRoot,
  path,
  label,
  excludeLegacyClawbench = false,
) {
  const stat = await lstat(path);
  if (stat.isSymbolicLink()) throw new TypeError(`${label} contains a symbolic link: ${path}`);
  if (!stat.isDirectory()) return;
  for (const name of await readdir(path)) {
    const child = resolve(path, name);
    if (shouldCopy(sourceRoot, child, excludeLegacyClawbench)) {
      await assertNoCopiedSymlinks(
        sourceRoot,
        child,
        label,
        excludeLegacyClawbench,
      );
    }
  }
}

async function digestCopiedTree(
  sourceRoot,
  path = sourceRoot,
  hash = createHash("sha256"),
  excludeLegacyClawbench = false,
) {
  const entries = (await readdir(path, { withFileTypes: true }))
    .filter((entry) => shouldCopy(
      sourceRoot,
      resolve(path, entry.name),
      excludeLegacyClawbench,
    ))
    .sort((left, right) => left.name.localeCompare(right.name, "en"));
  for (const entry of entries) {
    const child = resolve(path, entry.name);
    const name = relative(sourceRoot, child).replaceAll("\\", "/");
    hash.update(entry.isDirectory() ? `D\0${name}\0` : `F\0${name}\0`);
    if (entry.isDirectory()) {
      await digestCopiedTree(
        sourceRoot,
        child,
        hash,
        excludeLegacyClawbench,
      );
    }
    else hash.update(await readFile(child));
  }
  return hash;
}

async function updateClosureDigest(hash, label, path, root = path) {
  const stat = await lstat(path);
  if (stat.isSymbolicLink()) {
    throw new TypeError(`deployment closure contains a symbolic link: ${path}`);
  }
  const name = relative(root, path).replaceAll("\\", "/") || ".";
  hash.update(`${stat.isDirectory() ? "D" : "F"}\0${label}\0${name}\0`);
  if (stat.isDirectory()) {
    const entries = (await readdir(path, { withFileTypes: true }))
      .filter((entry) => shouldCopy(root, resolve(path, entry.name)))
      .sort((left, right) => left.name.localeCompare(right.name, "en"));
    for (const entry of entries) {
      await updateClosureDigest(hash, label, resolve(path, entry.name), root);
    }
  } else {
    hash.update(await readFile(path));
  }
}

export async function prepareDeployment(
  configPath,
  {
    repositoryRoot = REPOSITORY_ROOT,
    deployRoot = DEPLOY_ROOT,
    contextRoot = CONTEXT_ROOT,
    generatedConfig = GENERATED_CONFIG,
    generatedCompose = GENERATED_COMPOSE,
    checkOnly = false,
  } = {},
) {
  const root = resolve(repositoryRoot);
  const deployment = await loadDeployment(configPath, root);
  const usesLegacyRuntime =
    deployment.schema_version === "clawbench.generic-public-clone-deployment.v1"
    || deployment.backend_contract?.schema_version
      === "clawbench.site-backend-runtime.v1";
  const excludeLegacyClawbench = !usesLegacyRuntime;
  const sourceRoot = resolve(root, deployment.source_dir);
  if (!staysWithin(root, sourceRoot)) throw new TypeError("clone source escaped repository root");
  await assertReadableTree(sourceRoot, "clone source");
  await assertNoCopiedSymlinks(
    sourceRoot,
    sourceRoot,
    "clone source",
    excludeLegacyClawbench,
  );
  const candidateSha256 = (
    await digestCopiedTree(
      sourceRoot,
      sourceRoot,
      createHash("sha256"),
      excludeLegacyClawbench,
    )
  ).digest("hex");
  for (const item of deployment.runtime.support_paths) {
    const support = resolve(root, item.source);
    if (!staysWithin(root, support)) throw new TypeError(`support source escaped repository: ${item.source}`);
    await lstat(support);
    await assertNoCopiedSymlinks(support, support, `support source ${item.source}`);
  }
  const closureHash = createHash("sha256")
    .update(`deployment\0${JSON.stringify(deployment)}\0`)
    .update(`candidate\0${candidateSha256}\0`);
  const closurePaths = [
    ["shared-websitebench-init", resolve(root, "src", "websitebench", "__init__.py")],
    ["shared-local-auth", resolve(root, "src", "websitebench", "local_clone_auth")],
    ["shared-site-backend", resolve(root, "src", "websitebench", "site_backend")],
    ["generic-dockerfile", resolve(DEPLOY_ROOT, "Dockerfile")],
    ["generic-runtime", resolve(DEPLOY_ROOT, "runtime")],
    ["generic-worker", resolve(DEPLOY_ROOT, "src")],
    ["effects-gateway", resolve(DEPLOY_ROOT, "effects-gateway")],
    ["deployment-scripts", resolve(DEPLOY_ROOT, "scripts")],
    ["generic-package", resolve(DEPLOY_ROOT, "package.json")],
    ["generic-lock", resolve(DEPLOY_ROOT, "package-lock.json")],
    ["shared-auth-proxy", resolve(REPOSITORY_ROOT, "deploy", "shared", "public-clone-auth-proxy.js")],
    ["shared-stripe-proxy", resolve(REPOSITORY_ROOT, "deploy", "shared", "stripe-test-proxy.js")],
  ];
  if (usesLegacyRuntime) {
    closurePaths.push(
      ["legacy-clawbench-init", resolve(root, "src", "clawbench", "__init__.py")],
      ["legacy-local-auth", resolve(root, "src", "clawbench", "local_clone_auth")],
      ["legacy-site-backend", resolve(root, "src", "clawbench", "site_backend")],
    );
  }
  for (const item of deployment.runtime.support_paths) {
    closurePaths.push([
      `support:${item.destination}`,
      resolve(root, item.source),
    ]);
  }
  for (const [label, path] of closurePaths) {
    await updateClosureDigest(closureHash, label, path);
  }
  const deploymentSha256 = closureHash.digest("hex");
  const profile = deployment.backend_contract.deployment.profiles[deployment.deployment_profile];
  const wrangler = deployment.deployment_profile === "cloudflare-review"
    ? buildWranglerConfig(deployment, {
        candidate_sha256: candidateSha256,
        deployment_sha256: deploymentSha256,
        build_id: process.env.SOURCE_REF || process.env.GITHUB_SHA || "",
      })
    : null;
  const compose = deployment.deployment_profile === "docker-volume"
    ? buildComposeConfig(deployment)
    : null;
  if (checkOnly) {
    return {
      status: "valid",
      deployment,
      wrangler,
      compose,
      context_root: contextRoot,
      deployment_profile: deployment.deployment_profile,
      persistence: profile.persistence,
      compatibility: deployment.compatibility,
      candidate_sha256: candidateSha256,
      deployment_sha256: deploymentSha256,
      warnings: deployment.compatibility === "v1"
        ? ["v1 compatibility mode is ephemeral and must migrate to backend runtime v2"]
        : [],
    };
  }

  const expectedContext = resolve(deployRoot, ".container-context");
  if (resolve(contextRoot) !== expectedContext && resolve(deployRoot) === DEPLOY_ROOT) {
    throw new TypeError("context root must be the deployment-owned .container-context");
  }
  await rm(contextRoot, { recursive: true, force: true });
  await mkdir(contextRoot, { recursive: true });
  const cloneTarget = resolve(contextRoot, "clone");
  await cp(sourceRoot, cloneTarget, {
    recursive: true,
    force: true,
    filter: (path) => shouldCopy(
      sourceRoot,
      path,
      excludeLegacyClawbench,
    ),
  });

  const sharedTarget = resolve(contextRoot, "shared-src", "websitebench");
  const sharedRoot = resolve(root, "src", "websitebench");
  await mkdir(sharedTarget, { recursive: true });
  await cp(resolve(sharedRoot, "__init__.py"), resolve(sharedTarget, "__init__.py"));
  await cp(resolve(sharedRoot, "local_clone_auth"), resolve(sharedTarget, "local_clone_auth"), { recursive: true, force: true, filter: (path) => shouldCopy(resolve(sharedRoot, "local_clone_auth"), path) });
  await cp(resolve(sharedRoot, "site_backend"), resolve(sharedTarget, "site_backend"), { recursive: true, force: true, filter: (path) => shouldCopy(resolve(sharedRoot, "site_backend"), path) });
  if (usesLegacyRuntime) {
    const legacyTarget = resolve(contextRoot, "shared-src", "clawbench");
    const legacyRoot = resolve(root, "src", "clawbench");
    await mkdir(legacyTarget, { recursive: true });
    await cp(resolve(legacyRoot, "__init__.py"), resolve(legacyTarget, "__init__.py"));
    await cp(resolve(legacyRoot, "local_clone_auth"), resolve(legacyTarget, "local_clone_auth"), { recursive: true, force: true, filter: (path) => shouldCopy(resolve(legacyRoot, "local_clone_auth"), path) });
    await cp(resolve(legacyRoot, "site_backend"), resolve(legacyTarget, "site_backend"), { recursive: true, force: true, filter: (path) => shouldCopy(resolve(legacyRoot, "site_backend"), path) });
  }

  const supportTarget = resolve(contextRoot, "site-root");
  await mkdir(supportTarget, { recursive: true });
  for (const item of deployment.runtime.support_paths) {
    const source = resolve(root, item.source);
    const target = resolve(supportTarget, item.destination);
    if (!staysWithin(supportTarget, target)) throw new TypeError(`support destination escaped context: ${item.destination}`);
    await mkdir(dirname(target), { recursive: true });
    await cp(source, target, { recursive: true, force: true, filter: (path) => shouldCopy(source, path) });
  }

  const runtimeRoot = resolve(contextRoot, "runtime");
  await mkdir(runtimeRoot, { recursive: true });
  await writeFile(resolve(runtimeRoot, "deployment.json"), `${JSON.stringify(deployment, null, 2)}\n`);
  if (deployment.compatibility === "v2") {
    await writeFile(resolve(runtimeRoot, "backend-runtime.json"), `${JSON.stringify(deployment.backend_contract, null, 2)}\n`);
  }
  await writeFile(resolve(runtimeRoot, "requirements.txt"), `${deployment.runtime.python_requirements.join("\n")}\n`);
  if (wrangler) await writeFile(generatedConfig, `${JSON.stringify(wrangler, null, 2)}\n`);
  if (compose) await writeFile(generatedCompose, `${JSON.stringify(compose, null, 2)}\n`);
  return {
    status: "prepared",
    site_id: deployment.site_id,
    context_root: contextRoot,
    wrangler_config: wrangler ? generatedConfig : null,
    compose_config: compose ? generatedCompose : null,
    domain: deployment.domain,
    deployment_profile: deployment.deployment_profile,
    persistence: profile.persistence,
    compatibility: deployment.compatibility,
    candidate_sha256: candidateSha256,
    deployment_sha256: deploymentSha256,
    warnings: deployment.compatibility === "v1"
      ? ["v1 compatibility mode is ephemeral and must migrate to backend runtime v2"]
      : [],
  };
}

function parseArguments(argv) {
  let config = resolve(DEPLOY_ROOT, "deployment.local.json");
  let checkOnly = false;
  for (let index = 0; index < argv.length; index += 1) {
    if (argv[index] === "--config") config = resolve(argv[++index]);
    else if (argv[index] === "--check-only") checkOnly = true;
    else throw new TypeError(`unknown argument: ${argv[index]}`);
  }
  return { config, checkOnly };
}

if (resolve(process.argv[1] || "") === SCRIPT_PATH) {
  const options = parseArguments(process.argv.slice(2));
  console.log(JSON.stringify(await prepareDeployment(options.config, { checkOnly: options.checkOnly }), null, 2));
}
