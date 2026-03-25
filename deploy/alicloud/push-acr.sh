#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# push-acr.sh  —  Build the Docker image and push it to Alibaba Container Registry
#
# Usage:
#   chmod +x deploy/alicloud/push-acr.sh
#   ./deploy/alicloud/push-acr.sh [image-tag]        # tag defaults to 'latest'
#
# Prerequisites:
#   • Docker installed and running
#   • Logged in to ACR:  docker login registry.cn-<region>.aliyuncs.com
#   • .env.prod exists with ACR_* variables set
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

# Load env vars from .env.prod if it exists
ENV_FILE="${ENV_FILE:-.env.prod}"
if [[ -f "$ENV_FILE" ]]; then
  # shellcheck disable=SC2046
  export $(grep -v '^#' "$ENV_FILE" | grep -v '^$' | xargs)
fi

# Required variables
: "${ACR_REGISTRY:?Set ACR_REGISTRY in $ENV_FILE}"
: "${ACR_NAMESPACE:?Set ACR_NAMESPACE in $ENV_FILE}"
: "${ACR_REPO:?Set ACR_REPO in $ENV_FILE}"

IMAGE_TAG="${1:-${IMAGE_TAG:-latest}}"
FULL_IMAGE="${ACR_REGISTRY}/${ACR_NAMESPACE}/${ACR_REPO}:${IMAGE_TAG}"

echo "==> Building image: $FULL_IMAGE"
docker build \
  --platform linux/amd64 \
  --tag "$FULL_IMAGE" \
  .

echo "==> Pushing image to ACR…"
docker push "$FULL_IMAGE"

echo "==> Done. Image available at: $FULL_IMAGE"
