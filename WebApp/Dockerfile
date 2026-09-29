# Build from the repository root: docker build -f WebApp/Dockerfile .
FROM node:24-alpine@sha256:ebfe2f90462722a7a4de65e91990e97fe0d401c70e0e762c5b53302f905ec1c1 AS build
WORKDIR /WebApp
COPY WebApp/package.json WebApp/package-lock.json ./
RUN npm ci
COPY WebApp/index.html WebApp/tsconfig.json WebApp/vite.config.ts ./
COPY WebApp/Src ./Src
RUN npm run build

# Static artifact image. Nginx serving/proxy configuration belongs to Step4.
FROM scratch AS artifacts
COPY --from=build /WebApp/Build /Site
