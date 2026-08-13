FROM python:3.12-slim-bookworm

ARG SITE_ID
ARG SITE_LABEL
ARG AUTH_MODE="local"
ARG BACKEND_PROFILE="cloudflare-review"
ARG DATABASE_PERSISTENCE="ephemeral-reset"
ARG PAYMENT_ADAPTER="local-sandbox"
ARG MAIL_REGISTRATION_TEMPLATE=""
ARG DEPLOYMENT_BUILD_ID=""

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/repository-src \
    PORT=10000 \
    WEBSITEBENCH_DATA_DIR=/data \
    WEBSITEBENCH_BACKEND_PROFILE=${BACKEND_PROFILE} \
    WEBSITEBENCH_DATABASE_PERSISTENCE=${DATABASE_PERSISTENCE} \
    WEBSITEBENCH_PAYMENT_ADAPTER=${PAYMENT_ADAPTER} \
    WEBSITEBENCH_PUBLIC_INDEX_ROOT=/app/public-indexes \
    DEPLOYMENT_BUILD_ID=${DEPLOYMENT_BUILD_ID} \
    PUBLIC_CLONE_AUTH_MODE=${AUTH_MODE} \
    PUBLIC_CLONE_AUTH_SITE_ID=${SITE_ID} \
    PUBLIC_CLONE_AUTH_SITE_LABEL=${SITE_LABEL} \
    PUBLIC_CLONE_AUTH_MAIL_TEMPLATE=${MAIL_REGISTRATION_TEMPLATE} \
    PUBLIC_CLONE_AUTH_REDIS_REST_URL=http://redis.internal \
    PUBLIC_CLONE_AUTH_RESEND_API_URL=http://resend.internal/emails \
    PUBLIC_CLONE_AUTH_TRUST_PROXY_HEADERS=1

COPY .container-context/runtime/requirements.txt /tmp/requirements.txt
RUN apt-get update \
    && apt-get install --yes --no-install-recommends gosu \
    && rm -rf /var/lib/apt/lists/* \
    && if [ -s /tmp/requirements.txt ]; then pip install --no-cache-dir -r /tmp/requirements.txt; fi \
    && groupadd --system --gid 10001 websitebench-clone \
    && useradd --system --uid 10001 --gid websitebench-clone --home-dir /app websitebench-clone \
    && mkdir -p /app/clone /app/repository-src /app/runtime /data \
    && chown -R websitebench-clone:websitebench-clone /app /data

WORKDIR /app/clone
COPY --chown=websitebench-clone:websitebench-clone .container-context/shared-src/ /app/repository-src/
COPY --chown=websitebench-clone:websitebench-clone .container-context/clone/ /app/clone/
COPY --chown=websitebench-clone:websitebench-clone .container-context/site-root/ /app/
COPY --chown=websitebench-clone:websitebench-clone .container-context/runtime/deployment.json /app/runtime/deployment.json
COPY --chown=websitebench-clone:websitebench-clone .container-context/runtime/ /app/runtime/
COPY --chown=websitebench-clone:websitebench-clone runtime/launch.py /app/runtime/launch.py

LABEL org.opencontainers.image.description="Machine-validated protected offline-clone deployment" \
      org.opencontainers.image.site-id="${SITE_ID}"

EXPOSE 10000
STOPSIGNAL SIGTERM
CMD ["sh", "-c", "mkdir -p /data && chown websitebench-clone:websitebench-clone /data && exec gosu websitebench-clone:websitebench-clone python /app/runtime/launch.py"]
