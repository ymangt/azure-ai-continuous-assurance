FROM node:26-alpine@sha256:e88a35be04478413b7c71c455cd9865de9b9360e1f43456be5951032d7ac1a66 AS build
WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .
ARG VITE_DATA_SOURCE=api
ARG VITE_API_BASE_URL=/api/v1
ARG VITE_REPLAY_ONLY=false
ENV VITE_DATA_SOURCE=$VITE_DATA_SOURCE \
    VITE_API_BASE_URL=$VITE_API_BASE_URL \
    VITE_REPLAY_ONLY=$VITE_REPLAY_ONLY
RUN npm run build

FROM nginxinc/nginx-unprivileged:1.31.3-alpine@sha256:a718212f9cf21e241f14067333000a3f0930292f5354fe0db269e9a2a2596b9e
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
USER 101:101
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 CMD wget -q -O /dev/null http://127.0.0.1:8080/healthz || exit 1
CMD ["nginx", "-g", "daemon off;"]
