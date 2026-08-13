import { Container, ContainerProxy, getContainer } from "@cloudflare/containers";
import {
  containerInstanceName,
  normalizeContainerHealth,
} from "./health.js";
import { requestIsAuthorized, secretMatches, unauthorizedResponse } from "./auth.js";
import {
  buildContainerRequest,
  isStripeWebhookRequest,
  redisOutbound,
  resendOutbound,
  securedResponse,
  stripeOutbound,
  verifyStripeWebhook,
} from "./proxy.js";
import { injectTurnstileClient, verifyTurnstileEmailEntry } from "../../shared/turnstile.js";

export { ContainerProxy };

export class GenericCloneContainer extends Container {
  defaultPort = 10000;
  requiredPorts = [10000];
  sleepAfter = "10m";
  enableInternet = false;
  allowedHosts = ["redis.internal", "resend.internal", "stripe.internal"];
  envVars = { PORT: "10000", WEBSITEBENCH_DATA_DIR: "/data", PUBLIC_CLONE_AUTH_REDIS_REST_URL: "http://redis.internal", PUBLIC_CLONE_AUTH_RESEND_API_URL: "http://resend.internal/emails", PUBLIC_CLONE_AUTH_TRUST_PROXY_HEADERS: "1" };

  constructor(ctx, env) {
    super(ctx, env);
    this.envVars = {
      ...this.envVars,
      PUBLIC_CLONE_SMOKE_TOKEN: String(env.PUBLIC_CLONE_SMOKE_TOKEN || ""),
    };
  }
}
GenericCloneContainer.outboundByHost = { "redis.internal": redisOutbound, "resend.internal": resendOutbound, "stripe.internal": stripeOutbound };

function notFound(env) { return securedResponse(new Response("Not Found", { status: 404 }), env); }

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.hostname !== env.PUBLIC_HOST) return notFound(env);
    const container = getContainer(
      env.SITE_CONTAINER,
      containerInstanceName(env),
    );
    if (isStripeWebhookRequest(request, env)) {
      const verified = await verifyStripeWebhook(request, env);
      if (verified === null) return securedResponse(new Response("Invalid Stripe webhook", { status: 400 }), env);
      return securedResponse(
        await container.fetch(buildContainerRequest(request, { stripeWebhookVerified: true })),
        env,
      );
    }
    if (url.pathname === env.HEALTH_PATH && ["GET", "HEAD"].includes(request.method)) {
      const response = await container.fetch(buildContainerRequest(request));
      let bodyText = "";
      if (request.method === "GET" && response.ok) {
        bodyText = await response.text();
      }
      const normalized = normalizeContainerHealth(
        request,
        response,
        env,
        bodyText,
      );
      if (normalized.stale) await container.stop();
      return securedResponse(normalized.response, env);
    }
    if (!env.BASIC_AUTH_PASSWORD) {
      return securedResponse(
        new Response("Cloudflare deployment secret is not configured", {
          status: 503,
          headers: { "Content-Type": "text/plain; charset=utf-8" },
        }),
        env,
      );
    }
    if (!requestIsAuthorized(request, env.BASIC_AUTH_PASSWORD)) {
      return securedResponse(unauthorizedResponse(env.SITE_LABEL), env);
    }
    if (url.pathname.startsWith("/__bench/")) return notFound(env);
    const checked = await verifyTurnstileEmailEntry(request, env);
    if (checked.response) return securedResponse(checked.response, env);
    const registrationSmokeVerified =
      request.method === "POST" &&
      url.pathname === "/api/auth/send-code" &&
      secretMatches(
        request.headers.get("X-WebsiteBench-Registration-Smoke-Secret"),
        env.PUBLIC_CLONE_AUTH_SMOKE_SECRET,
      );
    return securedResponse(injectTurnstileClient(await container.fetch(buildContainerRequest(
      checked.request,
      { registrationSmokeVerified },
    )), env), env);
  },
};
