const BASIC_PREFIX = "Basic ";
export const BASIC_USERNAME = "bench";

function constantTimeEqual(left, right) {
  const leftBytes = new TextEncoder().encode(left);
  const rightBytes = new TextEncoder().encode(right);
  const length = Math.max(leftBytes.length, rightBytes.length);
  let mismatch = leftBytes.length ^ rightBytes.length;
  for (let index = 0; index < length; index += 1) mismatch |= (leftBytes[index] || 0) ^ (rightBytes[index] || 0);
  return mismatch === 0;
}

export function secretMatches(actual, expected) {
  return Boolean(expected) && constantTimeEqual(String(actual || ""), String(expected));
}

export function requestIsAuthorized(request, expectedPassword) {
  const value = request.headers.get("Authorization") || "";
  if (!expectedPassword || !value.startsWith(BASIC_PREFIX)) return false;
  let decoded = "";
  try { decoded = new TextDecoder("utf-8", { fatal: true }).decode(Uint8Array.from(atob(value.slice(BASIC_PREFIX.length).trim()), (character) => character.charCodeAt(0))); } catch { return false; }
  const separator = decoded.indexOf(":");
  return separator >= 0 && constantTimeEqual(decoded.slice(0, separator), BASIC_USERNAME) && constantTimeEqual(decoded.slice(separator + 1), expectedPassword);
}

export function unauthorizedResponse(siteLabel) {
  return new Response("Authentication required", { status: 401, headers: { "Cache-Control": "no-store", "Content-Type": "text/plain; charset=utf-8", "WWW-Authenticate": `Basic realm="${siteLabel}", charset="UTF-8"`, "X-Content-Type-Options": "nosniff", "X-Robots-Tag": "noindex, nofollow, noarchive" } });
}
