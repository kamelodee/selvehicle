# Alibaba Cloud Deployment Guide — sel_server

## Architecture

```
Internet
  │
  ├── TCP :8808  ──►  SLB (TCP listener)  ──►  ECS :8808  (vehicle terminals)
  │
  └── HTTP/HTTPS  ──►  SLB (HTTP/443 listener)  ──►  ECS :80/:443  ──►  Nginx  ──►  app :8000
                                                                             ↓
                                                                    RDS for MySQL (VPC internal)
```

---

## Prerequisites

| Resource | Recommended spec |
|----------|-----------------|
| **ECS** | ecs.c6.large (2 vCPU, 4 GB) · Ubuntu 22.04 LTS |
| **RDS** | RDS for MySQL 8.0, 1-Core 2 GB (rds.mysql.s1.small) |
| **SLB** | Standard, classic network or VPC |
| **ACR** | Free tier is sufficient |
| **VPC** | ECS and RDS in the same VPC + VSwitch |

---

## Step 1 — Create Alibaba Cloud Resources

### 1a. VPC & Security Group
- Create a VPC with a VSwitch in your target region.
- Security Group inbound rules:

| Port | Protocol | Source | Purpose |
|------|----------|--------|---------|
| 22 | TCP | your IP only | SSH |
| 80 | TCP | 0.0.0.0/0 | HTTP (redirect to HTTPS) |
| 443 | TCP | 0.0.0.0/0 | HTTPS REST API |
| 8808 | TCP | 0.0.0.0/0 | Vehicle terminal connections |

### 1b. RDS for MySQL
1. Create RDS instance in the same VPC as ECS.
2. Create a database named `vehi_db`.
3. Create a database account `vehi_user` with read/write access to `vehi_db`.
4. Note the **internal endpoint** (`rm-xxxx.mysql.rds.aliyuncs.com`) — use this, not the public endpoint.
5. Add ECS's private IP to the RDS whitelist.

### 1c. ACR (Container Registry)
1. Alibaba Cloud Console → Container Registry → Create Namespace (e.g. `my-company`).
2. Create a repository named `sel-server` (type: **Private**).
3. Note your registry address: `registry.cn-<region>.aliyuncs.com`.

---

## Step 2 — Build & Push the Docker Image

From your **local machine** (or CI):

```bash
# Log in to ACR
docker login registry.cn-hangzhou.aliyuncs.com

# Build for linux/amd64 and push
cp deploy/alicloud/.env.alicloud.example .env.prod
# Edit .env.prod — set ACR_* variables at minimum
chmod +x deploy/alicloud/push-acr.sh
./deploy/alicloud/push-acr.sh v1.0.0
```

---

## Step 3 — Bootstrap the ECS Instance

SSH into the ECS and run:

```bash
curl -fsSL https://raw.githubusercontent.com/your-org/sel_server/main/deploy/alicloud/setup-ecs.sh | bash
# Or copy the file and run: bash setup-ecs.sh
```

This installs Docker using the Alibaba Cloud mirror (fast in China) and logs you in to ACR.

---

## Step 4 — Deploy the Application

```bash
cd /opt/sel_server

# Clone or copy project files
git clone https://github.com/your-org/sel_server.git .

# Create production env file
cp deploy/alicloud/.env.alicloud.example .env.prod
nano .env.prod   # Fill in all CHANGE_ME values

# Start services
docker compose -f deploy/alicloud/docker-compose.prod.yml --env-file .env.prod up -d

# Check status
docker compose -f deploy/alicloud/docker-compose.prod.yml --env-file .env.prod ps
docker compose -f deploy/alicloud/docker-compose.prod.yml --env-file .env.prod logs -f server
```

---

## Step 5 — Create the Database Schema & Admin User

Run once after the first deployment:

```bash
# Enter the running container
docker compose -f deploy/alicloud/docker-compose.prod.yml --env-file .env.prod \
  exec server python seed.py
```

---

## Step 6 — SSL Certificate (optional but recommended)

**Option A: Alibaba Cloud SSL Certificate Service**
1. Purchase or apply for a free DV certificate in the console.
2. Download the Nginx PEM + KEY files.
3. Upload to `/etc/letsencrypt/live/yourdomain.com/` on the ECS (or adjust the path in `nginx.conf`).

**Option B: Let's Encrypt via Certbot**
```bash
apt-get install -y certbot
certbot certonly --standalone -d yourdomain.com
# Certificates land in /etc/letsencrypt/live/yourdomain.com/
```

Update `nginx.conf` `server_name` and certificate paths, then:
```bash
docker compose -f deploy/alicloud/docker-compose.prod.yml --env-file .env.prod restart nginx
```

---

## Step 7 — Configure the SLB

| Listener | Frontend port | Backend port | Protocol |
|----------|--------------|-------------|---------|
| Vehicle terminals | 8808 | 8808 | TCP |
| Admin API (HTTP) | 80 | 80 | HTTP |
| Admin API (HTTPS) | 443 | 443 | HTTPS (if terminating at SLB) |

Add the ECS instance as a backend server in each listener.

---

## Updating the Application

```bash
# 1. Build and push new image
./deploy/alicloud/push-acr.sh v1.1.0

# 2. Update IMAGE_TAG in .env.prod
# 3. Pull and restart on ECS
docker compose -f deploy/alicloud/docker-compose.prod.yml --env-file .env.prod pull
docker compose -f deploy/alicloud/docker-compose.prod.yml --env-file .env.prod up -d
```

---

## Health Check

```bash
curl http://<ECS-public-IP>/health
# Expected: {"status": "ok", "online_terminals": N}
```
