#!/usr/bin/env bash
# 로컬에서 블로그를 바로 띄워 확인하는 스크립트.
# - 옵시디언 노트를 docs/ 로 동기화하고
# - mkdocs 개발 서버를 라이브 리로드로 실행한다.
#
# 사용법:
#   tools/serve.sh                 # 동기화 후 http://127.0.0.1:8000 서빙
#   tools/serve.sh --no-sync       # 동기화 건너뛰고 서빙
#   tools/serve.sh --build         # 서빙 대신 --strict 빌드만 (배포 전 점검용)
#   PORT=8080 tools/serve.sh       # 포트 변경
set -euo pipefail

# 저장소 루트로 이동 (이 스크립트는 tools/ 안에 있다)
cd "$(dirname "$0")/.."

PORT="${PORT:-8000}"
DO_SYNC=1
MODE="serve"
for arg in "$@"; do
  case "$arg" in
    --no-sync) DO_SYNC=0 ;;
    --build)   MODE="build" ;;
    *) echo "알 수 없는 옵션: $arg" >&2; exit 2 ;;
  esac
done

if [ "$DO_SYNC" -eq 1 ]; then
  echo "▶ 옵시디언 노트 동기화..."
  uv run python tools/sync_obsidian.py
fi

if [ "$MODE" = "build" ]; then
  echo "▶ 빌드 점검 (--strict)..."
  uv run mkdocs build --strict
  echo "✓ 빌드 성공. site/ 에 생성됨."
else
  echo "▶ 개발 서버 시작: http://127.0.0.1:${PORT}  (Ctrl+C로 종료)"
  uv run mkdocs serve --dev-addr "127.0.0.1:${PORT}"
fi
