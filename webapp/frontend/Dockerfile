# syntax=docker/dockerfile:1
#
# edbo frontend image — Vite/TypeScript build served by nginx, which also
# reverse-proxies /api to the backend service.
#
# Build context is the REPOSITORY ROOT (see webapp/docker-compose.yml).
#
#   docker build -f webapp/frontend/Dockerfile -t edbo-frontend .

# ---------------------------------------------------------------- build stage
FROM node:20-alpine AS build

# Overridable npm registry for slow / restricted networks, e.g.
#   docker compose build --build-arg NPM_CONFIG_REGISTRY=https://registry.npmmirror.com
ARG NPM_CONFIG_REGISTRY=https://registry.npmjs.org
ENV NPM_CONFIG_REGISTRY=${NPM_CONFIG_REGISTRY}

WORKDIR /app

# Install deps from the lockfile first for better layer caching.
# (The root .dockerignore excludes webapp/frontend/node_modules, so it is
#  rebuilt here and never copied from the host.)
COPY webapp/frontend/package.json webapp/frontend/package-lock.json ./
RUN --mount=type=cache,target=/root/.npm \
    npm ci --no-audit --no-fund --fetch-retries=5 --fetch-timeout=120000

COPY webapp/frontend/ ./
RUN npm run build            # tsc -b && vite build  ->  /app/dist

# --------------------------------------------------------------- serve stage
FROM nginx:1.27-alpine
COPY webapp/frontend/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80
# nginx:alpine's default CMD already runs `nginx -g 'daemon off;'`.
