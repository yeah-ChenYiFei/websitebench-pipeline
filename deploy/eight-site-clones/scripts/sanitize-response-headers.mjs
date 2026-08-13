import { stdin, stdout } from "node:process";
import { fileURLToPath } from "node:url";

const SAFE_HEADER_NAMES = new Set([
  "x-robots-tag",
  "x-websitebench-build-id",
  "x-websitebench-container-build-id",
  "x-websitebench-worker-version",
]);

export function sanitizeResponseHeaders(rawHeaders) {
  const safeLines = [];

  for (const line of rawHeaders.split(/\r?\n/u)) {
    if (/^HTTP\/\d(?:\.\d)?\s+\d{3}(?:\s|$)/iu.test(line)) {
      safeLines.push(line);
      continue;
    }

    const separator = line.indexOf(":");
    if (separator === -1) {
      continue;
    }
    const name = line.slice(0, separator).trim().toLowerCase();
    if (SAFE_HEADER_NAMES.has(name)) {
      safeLines.push(line);
    }
  }

  return safeLines.length > 0 ? `${safeLines.join("\n")}\n` : "";
}

async function main() {
  stdin.setEncoding("utf8");
  let rawHeaders = "";
  for await (const chunk of stdin) {
    rawHeaders += chunk;
  }
  stdout.write(sanitizeResponseHeaders(rawHeaders));
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
  await main();
}
