FROM node:22-slim AS base

ENV NEXT_TELEMETRY_DISABLED=1

WORKDIR /app

COPY package.json package-lock.json ./
COPY apps/dashboard/package.json ./apps/dashboard/package.json
RUN npm ci

FROM base AS dev
COPY apps/dashboard ./apps/dashboard

EXPOSE 3000
CMD ["npm", "--workspace", "apps/dashboard", "run", "dev", "--", "--hostname", "0.0.0.0"]

FROM base AS build
COPY apps/dashboard ./apps/dashboard
RUN npm --workspace apps/dashboard run build

FROM node:22-slim AS runtime

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1

WORKDIR /app

COPY package.json package-lock.json ./
COPY apps/dashboard/package.json ./apps/dashboard/package.json
RUN npm ci --omit=dev

COPY --from=build /app/apps/dashboard/.next ./apps/dashboard/.next
COPY --from=build /app/apps/dashboard/app ./apps/dashboard/app
COPY --from=build /app/apps/dashboard/next-env.d.ts ./apps/dashboard/next-env.d.ts
COPY --from=build /app/apps/dashboard/tsconfig.json ./apps/dashboard/tsconfig.json

EXPOSE 3000
CMD ["npm", "--workspace", "apps/dashboard", "run", "start", "--", "--hostname", "0.0.0.0"]

