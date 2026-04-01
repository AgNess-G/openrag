#!/usr/bin/env bash
set -euo pipefail

# Usage: ./scripts/start-ray.sh [--stop-first] [num_workers]
#   --stop-first  run `ray stop` before starting (clears a previous local cluster)
STOP_FIRST=0
while [ "${1:-}" = "--stop-first" ]; do
    STOP_FIRST=1
    shift
done
NUM_WORKERS="${1:-2}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

# Ray is optional (pyproject extra `ray`). Prefer `uv run` so no global install is required.
if command -v ray >/dev/null 2>&1; then
    RAY=(ray)
elif command -v uv >/dev/null 2>&1; then
    RAY=(uv run ray)
else
    echo "Ray is not installed. From the repo root run:" >&2
    echo "  uv sync" >&2
    echo "Or use Docker:  docker compose --profile ray up -d ray-head ray-worker" >&2
    exit 1
fi

if [ "$STOP_FIRST" -eq 1 ]; then
    echo "=== Stopping any existing local Ray on this machine ==="
    "${RAY[@]}" stop || true
fi

if "${RAY[@]}" status &>/dev/null; then
    echo "Ray is already running (GCS on port 6379 is in use by a Ray cluster)." >&2
    echo "" >&2
    echo "Choose one:" >&2
    echo "  1) Stop it and start fresh:  ./scripts/start-ray.sh --stop-first ${NUM_WORKERS}" >&2
    echo "  2) Stop manually:             ${RAY[*]} stop" >&2
    echo "  3) If Ray is Docker:          docker compose stop ray-head ray-worker   (or adjust ports)" >&2
    exit 1
fi

# Ray treats extra `ray start --address=...` processes as multi-node; macOS/Windows block that unless set.
if [ "$NUM_WORKERS" -gt 0 ]; then
    case "$(uname -s)" in
        Darwin|MINGW*|MSYS*|CYGWIN*)
            export RAY_ENABLE_WINDOWS_OR_OSX_CLUSTER=1
            echo "Note: Enabling local multi-process workers on $(uname -s) (RAY_ENABLE_WINDOWS_OR_OSX_CLUSTER=1)."
            ;;
    esac
fi

echo "=== Starting Ray Head Node ==="
"${RAY[@]}" start --head --port=6379 --dashboard-host=0.0.0.0

echo ""
echo "Ray Dashboard:  http://localhost:8265"
echo "Ray Address:    ray://localhost:10001"
echo ""
echo "Update src/pipeline/presets/pipeline.yaml:"
echo "  execution:"
echo "    backend: ray"
echo "    ray:"
echo "      address: auto"
echo ""

if [ "$NUM_WORKERS" -gt 0 ]; then
    echo "=== Starting $NUM_WORKERS local worker(s) ==="
    for i in $(seq 1 "$NUM_WORKERS"); do
        "${RAY[@]}" start --address=localhost:6379 --num-cpus=2
        echo "  Worker $i started"
    done
fi

echo ""
echo "Ray cluster ready with $NUM_WORKERS worker(s)."
echo "Stop with: ${RAY[*]} stop"
