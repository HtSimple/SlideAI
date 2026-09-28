FROM node:22-bookworm-slim

RUN corepack enable && corepack prepare pnpm@12.7.0 --activate

WORKDIR /app

COPY package.json pnpm-workspace.yaml pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

COPY . .

EXPOSE 4173
CMD ["pnpm", "dev"]
