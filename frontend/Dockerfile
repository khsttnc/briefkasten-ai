FROM node:20-alpine AS build

WORKDIR /app

COPY package.json package-lock.json ./
# npm ci (not used here on purpose): its strict lockfile-must-match check
# has repeatedly failed in this exact build even right after a from-scratch
# `npm install` resync on the maintainer's Windows dev machine - the lock
# file's optional-dependency entries (esbuild/rollup native binaries) are
# platform-specific, and this image builds on linux-musl (alpine), not
# win32. npm install re-resolves those for the actual build platform
# instead of rejecting the mismatch.
RUN npm install

COPY . .
RUN npm run build

FROM nginx:1.27-alpine

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80
