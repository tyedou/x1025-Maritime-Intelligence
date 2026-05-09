#!/usr/bin/env bash
# Boot the SafetyAgent backend and a public cloudflared tunnel, then print the
# /chat URL to open in a browser. Ctrl+C to stop both processes cleanly.
#
# Prerequisite: run from inside a chimera SLURM allocation with GPU access.
# From a chimera login shell, before running this script:
#
#   salloc -c2 -A impact -q aicore --gres=gpu:4 --mem=32G \
#          -w chimera24 -p AICORE_H200 -t 720
#
# That opens a shell on chimera24 with 4 MIG slices visible; SafetyAgent uses
# slices 0-2 (NV-Embed, reranker, LLM). MOCK=1 skips this requirement.
#
# Tunable env vars:
#   CLOUDFLARED   path to cloudflared binary    (default: $HOME/cloudflared)
#   CONDA_ENV     conda env name to activate    (default: x1025)
#   PORT          uvicorn port on this host     (default: 8001)
#   MOCK          set to 1 to skip GPU pipeline (default: 0, real models)
#   LOG_DIR       where logs land               (default: /tmp/x1025-demo)

set -euo pipefail

CLOUDFLARED="${CLOUDFLARED:-$HOME/cloudflared}"
CONDA_ENV="${CONDA_ENV:-x1025}"
PORT="${PORT:-8001}"
MOCK="${MOCK:-0}"
LOG_DIR="${LOG_DIR:-/tmp/x1025-demo}"
mkdir -p "$LOG_DIR"

# Resolve repo root from script location so relative imports work regardless of cwd.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

if [ -f "$HOME/miniconda3/etc/profile.d/conda.sh" ]; then
    # shellcheck disable=SC1091
    . "$HOME/miniconda3/etc/profile.d/conda.sh"
    conda activate "$CONDA_ENV"
fi

[ -x "$CLOUDFLARED" ] || { echo "cloudflared not found at $CLOUDFLARED" >&2; exit 1; }
command -v uvicorn >/dev/null || { echo "uvicorn not on PATH (conda env active?)" >&2; exit 1; }

UVICORN_LOG="$LOG_DIR/uvicorn.log"
TUNNEL_LOG="$LOG_DIR/cloudflared.log"
: > "$UVICORN_LOG"
: > "$TUNNEL_LOG"

cleanup() {
    echo
    echo "stopping..."
    [ -n "${CFD_PID:-}" ] && kill "$CFD_PID" 2>/dev/null || true
    [ -n "${UVI_PID:-}" ] && kill "$UVI_PID" 2>/dev/null || true
    wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM

if [ "$MOCK" = "1" ]; then
    echo "starting uvicorn in MOCK mode (no GPU)..."
    CHAT_API_MOCK=1 uvicorn backend.chat_api.main:app \
        --host 127.0.0.1 --port "$PORT" >"$UVICORN_LOG" 2>&1 &
else
    echo "starting uvicorn in real mode (loading models, ~40s)..."
    uvicorn backend.chat_api.main:app \
        --host 127.0.0.1 --port "$PORT" >"$UVICORN_LOG" 2>&1 &
fi
UVI_PID=$!

until curl -sf "http://127.0.0.1:$PORT/api/v1/health" 2>/dev/null \
        | grep -q '"agent_loaded":true'; do
    if ! kill -0 "$UVI_PID" 2>/dev/null; then
        echo "uvicorn exited early -- last log lines:" >&2
        tail -30 "$UVICORN_LOG" >&2
        exit 1
    fi
    sleep 2
done
echo "  agent loaded."

echo "starting cloudflared tunnel..."
"$CLOUDFLARED" tunnel --url "http://localhost:$PORT" --no-autoupdate \
    >"$TUNNEL_LOG" 2>&1 &
CFD_PID=$!

URL=""
for _ in $(seq 1 60); do
    URL=$(grep -oE "https://[a-z0-9-]+\.trycloudflare\.com" "$TUNNEL_LOG" | head -1 || true)
    [ -n "$URL" ] && break
    sleep 1
done
if [ -z "$URL" ]; then
    echo "tunnel never produced a URL -- last log lines:" >&2
    tail -30 "$TUNNEL_LOG" >&2
    exit 1
fi

cat <<EOF

===================================================
  Demo URL:  $URL/chat
===================================================
  uvicorn log:   $UVICORN_LOG
  tunnel log:    $TUNNEL_LOG
  Press Ctrl+C to stop both processes.

EOF

wait "$UVI_PID" "$CFD_PID"
