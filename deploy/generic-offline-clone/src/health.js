export function publicHealthPayload(env, applicationVersion) {
  return {
    ok: true,
    site_id: env.SITE_ID,
    ...(applicationVersion ? { application_version: applicationVersion } : {}),
    ...(env.CANDIDATE_SHA256 ? { candidate_sha256: env.CANDIDATE_SHA256 } : {}),
    ...(env.DEPLOYMENT_SHA256 ? { deployment_sha256: env.DEPLOYMENT_SHA256 } : {}),
    ...(env.CF_VERSION_METADATA?.id
      ? { worker_version_id: env.CF_VERSION_METADATA.id }
      : {}),
  };
}

const COMMIT_BUILD_ID = /^[0-9a-f]{40}$/u;
const SAFE_SITE_ID = /^[a-z0-9](?:[a-z0-9-]{0,30}[a-z0-9])?$/u;
const MAX_INSTANCE_NAME_LENGTH = 63;

export function deploymentBuildId(env) {
  const buildId = String(env.DEPLOYMENT_BUILD_ID || "");
  if (!COMMIT_BUILD_ID.test(buildId)) {
    throw new TypeError("deployment build identity is missing or malformed");
  }
  return buildId;
}

export function containerInstanceName(env) {
  const siteId = String(env.SITE_ID || "");
  if (!SAFE_SITE_ID.test(siteId)) {
    throw new TypeError("container site identity is missing or malformed");
  }
  const name = `clone-${siteId}-${deploymentBuildId(env).slice(0, 12)}`;
  if (name.length > MAX_INSTANCE_NAME_LENGTH) {
    throw new RangeError("container instance identity exceeds the platform limit");
  }
  return name;
}

export function normalizeContainerHealth(request, response, env, bodyText = "") {
  const expectedBuildId = deploymentBuildId(env);
  const actualBuildId =
    response.headers.get("X-WebsiteBench-Container-Build-ID") ||
    response.headers.get("X-WebsiteBench-Build-ID");
  const stale =
    (actualBuildId !== null && actualBuildId !== expectedBuildId) ||
    (actualBuildId === null && response.ok);
  if (stale || actualBuildId === null) {
    return {
      stale,
      response: new Response("Container revision is not ready", {
        status: 503,
        headers: {
          "Content-Type": "text/plain; charset=utf-8",
          "Retry-After": "1",
        },
      }),
    };
  }
  if (!response.ok) return { stale: false, response };

  let applicationVersion = null;
  if (request.method === "GET") {
    try {
      const payload = JSON.parse(bodyText);
      if (
        typeof payload.version === "string" &&
        payload.version.length <= 200
      ) {
        applicationVersion = payload.version;
      }
    } catch (_) {
      return {
        stale: false,
        response: new Response("Invalid container health payload", {
          status: 502,
        }),
      };
    }
  }
  return {
    stale: false,
    response: new Response(
      request.method === "HEAD"
        ? null
        : JSON.stringify(publicHealthPayload(env, applicationVersion)),
      {
        status: 200,
        headers: {
          "Content-Type": "application/json; charset=utf-8",
          "X-WebsiteBench-Container-Build-ID": actualBuildId,
        },
      },
    ),
  };
}
