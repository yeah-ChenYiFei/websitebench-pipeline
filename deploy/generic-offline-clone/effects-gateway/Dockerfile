FROM node:22.22.0-bookworm-slim

ENV NODE_ENV=production \
    EFFECTS_PORT=8080

WORKDIR /app
COPY --chown=node:node deploy/shared/public-clone-auth-proxy.js /app/shared/public-clone-auth-proxy.js
COPY --chown=node:node deploy/shared/stripe-test-proxy.js /app/shared/stripe-test-proxy.js
COPY --chown=node:node deploy/generic-offline-clone/effects-gateway/server.mjs /app/server.mjs

USER node
EXPOSE 8080
CMD ["node", "/app/server.mjs"]
