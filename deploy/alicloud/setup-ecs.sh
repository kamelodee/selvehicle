#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# setup-ecs.sh  —  Bootstrap a fresh Alibaba Cloud ECS instance (Ubuntu 22.04)
#
# Run once as root (or with sudo) immediately after provisioning the ECS:
#   bash setup-ecs.sh
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

ACR_REGISTRY="${ACR_REGISTRY:-registry.cn-hangzhou.aliyuncs.com}"

echo "==> [1/5] Updating system packages…"
apt-get update -qq && apt-get upgrade -y -qq

echo "==> [2/5] Installing Docker (using Alibaba Cloud mirror for speed in China)…"
apt-get install -y -qq ca-certificates curl gnupg

install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://mirrors.aliyun.com/docker-ce/linux/ubuntu/gpg \
  | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
chmod a+r /etc/apt/keyrings/docker.gpg

echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
  https://mirrors.aliyun.com/docker-ce/linux/ubuntu \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
  > /etc/apt/sources.list.d/docker.list

apt-get update -qq
apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-compose-plugin

systemctl enable --now docker

echo "==> [3/5] Configuring Docker daemon (Alibaba Cloud mirror registry)…"
cat > /etc/docker/daemon.json <<'EOF'
{
  "registry-mirrors": [
    "https://registry.cn-hangzhou.aliyuncs.com"
  ],
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "50m",
    "max-file": "5"
  }
}
EOF
systemctl restart docker

echo "==> [4/5] Logging in to ACR (enter your RAM user AccessKey or sub-account password when prompted)…"
docker login "${ACR_REGISTRY}"

echo "==> [5/5] Creating app directory…"
mkdir -p /opt/sel_server
echo ""
echo "Setup complete. Next steps:"
echo "  1. Copy your project files to /opt/sel_server  (scp or git clone)"
echo "  2. cd /opt/sel_server"
echo "  3. cp deploy/alicloud/.env.alicloud.example .env.prod"
echo "  4. Fill in all secrets in .env.prod"
echo "  5. docker compose -f deploy/alicloud/docker-compose.prod.yml --env-file .env.prod up -d"
