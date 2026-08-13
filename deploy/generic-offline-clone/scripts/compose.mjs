const SITE_ID = /^[a-z0-9]+(?:-[a-z0-9]+)*$/u;

function interpolation(name) {
  return `\${${name}:?${name} is required}`;
}

function composeLiteral(value) {
  // Compose interpolates every `$` found in environment values. Runtime mail
  // templates deliberately contain `${variable}` placeholders, so escape
  // them here and let Compose deliver a single literal `$` to the container.
  return value.replaceAll("$", () => "$$");
}

export function buildComposeConfig(deployment) {
  if (deployment.schema_version !== "websitebench.generic-public-clone-deployment.v2") {
    throw new TypeError("docker-volume requires a v2 deployment descriptor");
  }
  if (deployment.deployment_profile !== "docker-volume") {
    throw new TypeError("Compose config requires docker-volume");
  }
  if (!SITE_ID.test(deployment.site_id)) throw new TypeError("invalid site_id");
  const profile = deployment.backend_contract?.deployment?.profiles?.["docker-volume"];
  if (!profile || profile.persistence !== "persistent-volume") {
    throw new TypeError("docker-volume must declare persistent-volume");
  }
  const slug = `websitebench-${deployment.site_id}`;
  const networkKey = "site-internal";
  const volumeKey = "site-data";
  const remoteMail = profile.mail_adapter === "effects-gateway";
  const stripeTest = profile.payment_adapter === "stripe-test";
  const legacyClawRuntime =
    deployment.backend_contract.schema_version
      === "clawbench.site-backend-runtime.v1";
  const registration = deployment.backend_contract.mail.purposes.registration;
  const mailTemplates = composeLiteral(
    JSON.stringify(deployment.backend_contract.mail.purposes),
  );
  const registrationTemplate = registration
    ? composeLiteral(
        JSON.stringify({
          sender_display_name:
            deployment.backend_contract.mail.sender.display_name,
          subject: registration.subject,
          lead: registration.lead,
          body: registration.body,
          expiry: registration.expiry,
          footer: registration.footer,
        }),
      )
    : "";
  const appEnvironment = {
    PORT: "10000",
    WEBSITEBENCH_DATA_DIR: "/data",
    WEBSITEBENCH_SITE_BACKEND_RUNTIME: "/app/runtime/backend-runtime.json",
    WEBSITEBENCH_BACKEND_PROFILE: "docker-volume",
    WEBSITEBENCH_DATABASE_PERSISTENCE: profile.persistence,
    WEBSITEBENCH_PAYMENT_ADAPTER: profile.payment_adapter,
    PUBLIC_CLONE_AUTH_MODE: remoteMail ? "redis-resend" : "local",
    PUBLIC_CLONE_AUTH_SITE_ID: deployment.site_id,
    PUBLIC_CLONE_AUTH_SITE_LABEL: deployment.site_label,
    PUBLIC_CLONE_AUTH_REDIS_REST_URL: "http://redis.internal:8080",
    PUBLIC_CLONE_AUTH_RESEND_API_URL: "http://resend.internal:8080/emails",
    PUBLIC_CLONE_AUTH_EFFECTS_TOKEN: interpolation(`${deployment.site_id.toUpperCase().replaceAll("-", "_")}_EFFECTS_INTERNAL_TOKEN`),
    PUBLIC_CLONE_AUTH_TRUST_PROXY_HEADERS: "1",
    PUBLIC_CLONE_AUTH_MAIL_TEMPLATE: registrationTemplate,
    WEBSITEBENCH_MAIL_TEMPLATES: mailTemplates,
    ...(remoteMail ? { WEBSITEBENCH_RESEND_INTERNAL_ORIGIN: "http://resend.internal:8080" } : {}),
    PAYMENT_ADAPTER: profile.payment_adapter,
    ...(stripeTest ? { STRIPE_INTERNAL_ORIGIN: "http://stripe.internal:8080" } : {}),
    ...(stripeTest ? { WEBSITEBENCH_EFFECTS_INTERNAL_TOKEN: interpolation(`${deployment.site_id.toUpperCase().replaceAll("-", "_")}_EFFECTS_INTERNAL_TOKEN`) } : {}),
  };
  const gatewayEnvironment = {
    SITE_ID: deployment.site_id,
    SITE_LABEL: deployment.site_label,
    PUBLIC_HOST: deployment.domain,
    EFFECTS_PORT: "8080",
    BASIC_AUTH_PASSWORD: interpolation(`${deployment.site_id.toUpperCase().replaceAll("-", "_")}_BASIC_AUTH_PASSWORD`),
    EFFECTS_INTERNAL_TOKEN: interpolation(`${deployment.site_id.toUpperCase().replaceAll("-", "_")}_EFFECTS_INTERNAL_TOKEN`),
    PUBLIC_CLONE_AUTH_MAIL_TEMPLATE: registrationTemplate,
    REDIS_REST_URL: interpolation(`${deployment.site_id.toUpperCase().replaceAll("-", "_")}_REDIS_REST_URL`),
    REDIS_REST_TOKEN: interpolation(`${deployment.site_id.toUpperCase().replaceAll("-", "_")}_REDIS_REST_TOKEN`),
    RESEND_API_KEY: interpolation(`${deployment.site_id.toUpperCase().replaceAll("-", "_")}_RESEND_API_KEY`),
    [deployment.backend_contract.mail.sender.address_env]: interpolation("RESEND_FROM_EMAIL"),
    MAIL_SENDER_ADDRESS_ENV: deployment.backend_contract.mail.sender.address_env,
    MAIL_SENDER_DISPLAY_NAME: deployment.backend_contract.mail.sender.display_name,
    MAIL_TEMPLATES: mailTemplates,
    PAYMENT_ADAPTER: profile.payment_adapter,
    WEBSITEBENCH_LEGACY_CLAW_RUNTIME: legacyClawRuntime ? "1" : "0",
    ...(stripeTest
      ? {
          [deployment.backend_contract.payments.stripe_test.secret_key_env]: interpolation(`${deployment.site_id.toUpperCase().replaceAll("-", "_")}_STRIPE_TEST_SECRET_KEY`),
          [deployment.backend_contract.payments.stripe_test.webhook_secret_env]: interpolation(`${deployment.site_id.toUpperCase().replaceAll("-", "_")}_STRIPE_TEST_WEBHOOK_SECRET`),
          STRIPE_SECRET_KEY_ENV: deployment.backend_contract.payments.stripe_test.secret_key_env,
          STRIPE_WEBHOOK_SECRET_ENV: deployment.backend_contract.payments.stripe_test.webhook_secret_env,
          STRIPE_PUBLIC_ORIGIN: deployment.backend_contract.payments.stripe_test.public_origin,
          STRIPE_RETURN_PATH: deployment.backend_contract.payments.stripe_test.return_path,
          STRIPE_WEBHOOK_PATH: deployment.backend_contract.payments.stripe_test.webhook_path,
          STRIPE_MAX_LINE_ITEMS: String(deployment.backend_contract.payments.stripe_test.max_line_items),
          PAYMENT_CURRENCY: deployment.backend_contract.payments.currency,
        }
      : {}),
  };
  return {
    name: slug,
    services: {
      app: {
        build: {
          context: ".",
          dockerfile: "Dockerfile",
          args: {
            SITE_ID: deployment.site_id,
            SITE_LABEL: deployment.site_label,
            AUTH_MODE: remoteMail ? "redis-resend" : "local",
          },
        },
        environment: appEnvironment,
        restart: "unless-stopped",
        read_only: true,
        tmpfs: ["/tmp"],
        volumes: [`${volumeKey}:/data`],
        networks: [networkKey],
        depends_on: {
          "effects-gateway": { condition: "service_healthy" },
        },
      },
      "effects-gateway": {
        build: {
          context: "../..",
          dockerfile: "deploy/generic-offline-clone/effects-gateway/Dockerfile",
        },
        environment: gatewayEnvironment,
        restart: "unless-stopped",
        read_only: true,
        cap_drop: ["ALL"],
        security_opt: ["no-new-privileges:true"],
        networks: {
          [networkKey]: {
            aliases: ["redis.internal", "resend.internal", "stripe.internal"],
          },
          "effects-egress": {},
        },
        // Compose allocates a loopback-only host port, so site stacks cannot
        // collide through a shared fixed port.
        ports: ["127.0.0.1::8080"],
        healthcheck: {
          test: ["CMD", "node", "-e", "fetch('http://127.0.0.1:8080/healthz').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"],
          interval: "10s",
          timeout: "3s",
          retries: 6,
        },
      },
    },
    networks: {
      [networkKey]: {
        name: `${slug}-internal`,
        internal: true,
      },
      "effects-egress": {
        name: `${slug}-effects-egress`,
      },
    },
    volumes: {
      [volumeKey]: {
        name: `${slug}-data`,
      },
    },
  };
}
