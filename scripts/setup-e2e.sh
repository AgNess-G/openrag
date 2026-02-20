#!/bin/bash
set -e

# Go to project root
cd "$(dirname "$0")/.."

# Environment file for E2E tests
E2E_ENV="frontend/.env.test"

# Detect container runtime
if command -v docker >/dev/null 2>&1; then
    CONTAINER_RUNTIME="docker"
else
    CONTAINER_RUNTIME="podman"
fi

echo "Using container runtime: $CONTAINER_RUNTIME"
echo "Starting E2E Setup using $E2E_ENV..."

# Clean up using make
echo "Cleaning up..."
make factory-reset FORCE=true ENV_FILE=$E2E_ENV

# Start infrastructure using make (this will use the new .env)
echo "Starting infrastructure..."
make dev-local-cpu ENV_FILE=$E2E_ENV

echo "Waiting for OpenSearch..."
until curl -s -k https://localhost:9200 >/dev/null; do
    sleep 5
    echo "Waiting for OpenSearch..."
done

echo "Waiting for Langflow..."
until curl -s http://localhost:7860/health >/dev/null; do
    sleep 5
    echo "Waiting for Langflow..."
done

echo "Infrastructure Ready!"
