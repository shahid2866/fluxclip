# FluxClip Studio web app (Next.js standalone build)
FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci --no-audit --no-fund

FROM node:22-alpine AS build
WORKDIR /app
# Rewrites (/api, /files -> Python API) are resolved at build time.
ARG FLUXCLIP_API_URL=http://api:8000
ENV FLUXCLIP_API_URL=$FLUXCLIP_API_URL NEXT_TELEMETRY_DISABLED=1
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

FROM node:22-alpine
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3000 HOSTNAME=0.0.0.0
COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static ./.next/static
COPY --from=build /app/public ./public
EXPOSE 3000
CMD ["node", "server.js"]
