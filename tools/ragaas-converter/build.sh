#!/usr/bin/env bash
# ragaas-converter 서비스 패키지 빌드.
#   산출물: dist/ragaas-converter-<version>-windows-amd64.zip (+ .sha256)
#   zip 구성: ragaas-converter.exe + service.json  (런처 게이트웨이 설계 §10.1 패키지 형식)
#
# 사용: tools/ragaas-converter/build.sh
# 게시(카탈로그 PR·서명)는 GoJIRA 플랫폼 레포의 catalog 워크플로가 담당한다.
set -euo pipefail

cd "$(dirname "$0")"
VERSION=$(python -c "import json;print(json.load(open('service.json'))['version'])")
NAME=ragaas-converter
OUT=dist
PKG="$NAME-$VERSION-windows-amd64"

go vet ./...
go test ./...

rm -rf "$OUT/$PKG" && mkdir -p "$OUT/$PKG"
CGO_ENABLED=0 GOOS=windows GOARCH=amd64 go build -trimpath -ldflags "-s -w" -o "$OUT/$PKG/$NAME.exe" .
cp service.json "$OUT/$PKG/"

python - "$OUT" "$PKG" <<'EOF'
import hashlib, os, sys, zipfile
out, pkg = sys.argv[1], sys.argv[2]
zpath = os.path.join(out, pkg + ".zip")
with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
    for f in sorted(os.listdir(os.path.join(out, pkg))):
        z.write(os.path.join(out, pkg, f), f)
h = hashlib.sha256(open(zpath, "rb").read()).hexdigest()
open(zpath + ".sha256", "w").write(f"{h}  {pkg}.zip\n")
print(zpath, h)
EOF
rm -rf "$OUT/$PKG"
