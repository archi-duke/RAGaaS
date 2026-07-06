#!/bin/sh
# 컨테이너 기동 시 런타임 env → /env.js 생성 (플랫폼 계약 05 §5).
# 빌드 산출물은 host-agnostic — 재빌드 없이 env 값만 바꿔 host/scheme 교체 (폐쇄망 요건 C6).
# 규칙: 앱(src/platform/config.ts)이 소비하는 런타임 키는 아래 직렬화 목록에 반드시 포함할 것.
set -e

esc() {
  printf '%s' "$1" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g'
}

cat > /usr/share/nginx/html/env.js <<EOF
window._env_ = {
  REACT_APP_RAGAAS_API: "$(esc "$REACT_APP_RAGAAS_API")",
  REACT_APP_RAGAAS_INGEST_API: "$(esc "$REACT_APP_RAGAAS_INGEST_API")",
  REACT_APP_USE_SSO: "$(esc "$REACT_APP_USE_SSO")",
  REACT_APP_SSO_URL: "$(esc "$REACT_APP_SSO_URL")",
  REACT_APP_DEV_USER: "$(esc "$REACT_APP_DEV_USER")"
};
EOF

exec nginx -g 'daemon off;'
