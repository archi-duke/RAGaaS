# RAGaaS Frontend — Module Federation remote 빌드 + nginx 정적 서빙
# (플랫폼 셸이 ${gateway}/ragaas/remoteEntry.js 로 로드. build context = 레포 루트)
FROM node:22-slim AS builder

WORKDIR /app

# 의존성 먼저 (레이어 캐시)
COPY frontend/package*.json ./
# Kendo 5.x peer 는 react ^18 까지지만 셸(React 19 singleton)과 정렬 필요 → legacy-peer-deps
RUN npm install --legacy-peer-deps

# 소스 + 빌드 (vite base='/ragaas/', federation remoteEntry.js 산출)
COPY frontend/ .
RUN npm run build

# ── 서빙 ────────────────────────────────────────────────────────────────────
FROM nginx:alpine
COPY --from=builder /app/dist /usr/share/nginx/html
COPY deploy/images/frontend/nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
