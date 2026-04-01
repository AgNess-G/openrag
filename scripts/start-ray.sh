#!/usr/bin/env bash
set -euo pipefail

NUM_WORKERS="${1:-2}"

echo "=== Starting Ray Head Node ==="
ray start --head --port=6379 --dashboard-host=0.0.0.0

echo ""
echo "Ray Dashboard:  http://localhost:8265"
echo "Ray Address:    ray://localhost:10001"
echo ""
echo "Update config/pipeline.yaml:"
echo "  execution:"
echo "    backend: ray"
echo "    ray:"
echo "      address: auto"
echo ""

if [ "$NUM_WORKERS" -gt 0 ]; then
    echo "=== Starting $NUM_WORKERS local worker(s) ==="
    for i in $(seq 1 "$NUM_WORKERS"); do
        ray start --address=localhost:6379 --num-cpus=2
        echo "  Worker $i started"
    done
fi

echo ""
echo "Ray cluster ready with $NUM_WORKERS worker(s)."
echo "Stop with: ray stop"
