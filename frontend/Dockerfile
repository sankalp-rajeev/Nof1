FROM node:22-bookworm-slim AS build
WORKDIR /srv/frontend
ENV NEXT_TELEMETRY_DISABLED=1
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend ./
ARG API_INTERNAL_URL=http://backend:8000
ENV API_INTERNAL_URL=${API_INTERNAL_URL}
RUN npm run build

FROM node:22-bookworm-slim AS run
WORKDIR /srv/frontend
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 HOSTNAME=0.0.0.0 PORT=3000
COPY --from=build --chown=node:node /srv/frontend/.next/standalone ./
COPY --from=build --chown=node:node /srv/frontend/.next/static ./.next/static
USER node
EXPOSE 3000
CMD ["node", "server.js"]
