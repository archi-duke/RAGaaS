# Build stage
FROM ubuntu:22.04 AS builder

ENV DEBIAN_FRONTEND=noninteractive

WORKDIR /app

# Install Node.js 22 (LTS) — @module-federation/vite(undici)가 Node 20+ 전역 File 요구
RUN apt-get update && apt-get install -y \
    curl \
    ca-certificates \
    && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# Copy package files (+ .npmrc — React19 + Kendo 5.8 peer 완화, frontend/.npmrc 참고)
COPY package*.json .npmrc ./

# Copy license file if it exists (optional, for local builds)
COPY telerik-license.txt* ./

# Accept license key as build argument (for CI/CD)
ARG TELERIK_LICENSE
ENV TELERIK_LICENSE=${TELERIK_LICENSE}

# Install dependencies
RUN npm install

# Copy source code
COPY . .

# Build the application
RUN npm run build

# Production stage
FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

# Install nginx
RUN apt-get update && apt-get install -y \
    nginx \
    && rm -rf /var/lib/apt/lists/*

# Copy built assets from builder
COPY --from=builder /app/dist /usr/share/nginx/html

# Remove default nginx site and copy custom configuration
RUN rm -f /etc/nginx/sites-enabled/default
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Runtime env injection (플랫폼 계약 05 §5) — 기동 시 env → env.js 생성 후 nginx 실행
COPY entrypoint.sh /entrypoint.sh
RUN sed -i 's/\r$//' /entrypoint.sh && chmod +x /entrypoint.sh

# Expose port
EXPOSE 80

# Start via entrypoint (env.js 생성 → nginx)
CMD ["/entrypoint.sh"]
