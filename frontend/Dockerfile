FROM node:20-alpine AS deps

WORKDIR /app
ARG NEXT_TELEMETRY_DISABLED=1
ENV NEXT_TELEMETRY_DISABLED=${NEXT_TELEMETRY_DISABLED}

RUN apk add --no-cache libc6-compat

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

FROM node:20-alpine AS builder

WORKDIR /app
ARG NEXT_PUBLIC_PLATFORM_NAME="News Intelligence Platform"
ARG NEXT_PUBLIC_API_BASE_PATH="/api/v1"
ARG BACKEND_INTERNAL_BASE_URL="http://backend:8000"
ARG NEXT_TELEMETRY_DISABLED=1
ENV NEXT_PUBLIC_PLATFORM_NAME=${NEXT_PUBLIC_PLATFORM_NAME} \
    NEXT_PUBLIC_API_BASE_PATH=${NEXT_PUBLIC_API_BASE_PATH} \
    BACKEND_INTERNAL_BASE_URL=${BACKEND_INTERNAL_BASE_URL} \
    NEXT_TELEMETRY_DISABLED=${NEXT_TELEMETRY_DISABLED}

RUN apk add --no-cache libc6-compat

COPY --from=deps /app/node_modules ./node_modules
COPY frontend/ ./

RUN npm run build

FROM node:20-alpine AS runner

WORKDIR /app
ARG BACKEND_INTERNAL_BASE_URL="http://backend:8000"
ARG NEXT_TELEMETRY_DISABLED=1
ENV NODE_ENV=production \
    HOSTNAME=0.0.0.0 \
    PORT=3000 \
    BACKEND_INTERNAL_BASE_URL=${BACKEND_INTERNAL_BASE_URL} \
    NEXT_TELEMETRY_DISABLED=${NEXT_TELEMETRY_DISABLED}

RUN addgroup -S nextjs && adduser -S nextjs -G nextjs

COPY --from=builder /app/public ./public
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static

USER nextjs

EXPOSE 3000

CMD ["node", "server.js"]
