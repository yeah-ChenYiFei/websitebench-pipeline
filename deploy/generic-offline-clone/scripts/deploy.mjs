import { spawn } from "node:child_process";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";

import {
  DEPLOY_ROOT,
  GENERATED_COMPOSE,
  GENERATED_CONFIG,
  REPOSITORY_ROOT,
} from "./config.mjs";
import { prepareDeployment } from "./prepare.mjs";

const WRANGLER_BIN = resolve(
  DEPLOY_ROOT,
  "node_modules",
  "wrangler",
  "bin",
  "wrangler.js",
);
function nextArgument(argv, index, label) {
  const value = argv[index + 1];
  if (typeof value !== "string" || !value || value.startsWith("--")) {
    throw new TypeError(`${label} requires a value`);
  }
  return value;
}

export function parseDeployArguments(argv) {
  let config = resolve(DEPLOY_ROOT, "deployment.local.json");
  let dryRun = true;
  for (let index = 0; index < argv.length; index += 1) {
    if (argv[index] === "--config") {
      config = resolve(nextArgument(argv, index, "--config"));
      index += 1;
    } else if (argv[index] === "--dry-run") {
      dryRun = true;
    } else if (argv[index] === "--yes") {
      dryRun = false;
    } else {
      throw new TypeError(`unknown argument: ${argv[index]}`);
    }
  }
  return { config, dryRun };
}

function run(command, args, { env = {} } = {}) {
  return new Promise((accept, reject) => {
    const child = spawn(command, args, {
      cwd: REPOSITORY_ROOT,
      env: { ...process.env, ...env },
      stdio: "inherit",
      shell: false,
    });
    child.once("error", reject);
    child.once("exit", (code, signal) => (
      code === 0
        ? accept()
        : reject(new Error(`${command} exited ${code ?? signal}`))
    ));
  });
}

export async function deploy(
  options,
  { prepare = prepareDeployment, runCommand = run } = {},
) {
  const prepared = await prepare(options.config);
  const profile = prepared.deployment_profile;

  if (profile === "cloudflare-review") {
    const args = [WRANGLER_BIN, "deploy", "--config", GENERATED_CONFIG];
    if (options.dryRun) {
      args.push(
        "--dry-run",
        "--containers-rollout=none",
        "--outdir",
        ".wrangler/dry-run",
      );
    }
    await runCommand(process.execPath, args);
  } else if (profile === "docker-volume") {
    const args = ["compose", "-f", GENERATED_COMPOSE];
    if (options.dryRun) args.push("config", "--no-interpolate");
    else args.push("up", "-d", "--build");
    await runCommand("docker", args);
  } else if (!options.dryRun) {
    throw new TypeError("offline-harbor cannot be externally deployed");
  }

  return {
    ...prepared,
    status: options.dryRun
      ? "dry-run-complete"
      : "deployed-machine-validated",
  };
}

if (
  process.argv[1] &&
  resolve(fileURLToPath(import.meta.url)) === resolve(process.argv[1])
) {
  const result = await deploy(parseDeployArguments(process.argv.slice(2)));
  console.log(JSON.stringify(result, null, 2));
}
