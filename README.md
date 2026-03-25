# Selvehicle

Python async vehicle terminal server implementing the **JT/T 808-2019** communication protocol
with client-specific extensions from this project's V1.0.1 spec.

## Features

| Feature | Details |
|---|---|
| Protocol | JT/T 808-2019 full framing, escaping, checksum |
| Location Reports | `0x0200` + all additional info items (§2.2), custom `0xEE` alarm/ECU status |
| Control Commands | `0x8105` — power on/off, start/stop alarm (§3) |
| Parameters | `0x8103` set, `0x8106` query — ECU ignition & geo-fence switches (§4) |
| Registration | `0x0100` / `0x8100` with auth code generation |
| Authentication | `0x0102` |
| Heartbeat | `0x0002` |
| Admin REST API | FastAPI with Swagger UI at `/docs` |
| Database | SQLite (dev) or PostgreSQL (production) via SQLAlchemy |
| Deployment | Docker + Docker Compose |

---

## Quick Start (Local Dev)

```bash
git clone <this-repo>
cd jt808_server

python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt

python main.py
```

- **TCP server** listens on `0.0.0.0:8808`
- **REST API** available at `http://localhost:8000`
- **Swagger UI** at `http://localhost:8000/docs`

---

## Cloud Deployment (Docker)

### 1. Set your Postgres password
```bash
export POSTGRES_PASSWORD=your_secure_password
```

### 2. Build and start
```bash
docker-compose up -d --build
```

### 3. Check logs
```bash
docker-compose logs -f server
```

### Cloud Provider Specifics

**AWS EC2 / ECS**
- Open inbound ports `8808` (TCP) and `8000` (HTTP) in your Security Group
- Use an Application Load Balancer for the API (port 8000)
- Use a Network Load Balancer (TCP passthrough) for port 8808

**GCP Cloud Run / GKE**
- Cloud Run does not support raw TCP; use GKE or a Compute Engine VM
- Expose port 8808 via a TCP Load Balancer Service
- Expose port 8000 via an HTTP Load Balancer

**Azure Container Instances / AKS**
- Use AKS with a LoadBalancer service for both ports
- Set `DATABASE_URL` to your Azure Database for PostgreSQL connection string

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `TCP_HOST` | `0.0.0.0` | TCP bind address |
| `TCP_PORT` | `8808` | Terminal connection port |
| `HTTP_HOST` | `0.0.0.0` | API bind address |
| `HTTP_PORT` | `8000` | Admin API port |
| `DATABASE_URL` | `sqlite:///./jt808.db` | SQLAlchemy connection string |
| `IDLE_TIMEOUT_SECS` | `120` | Terminal idle timeout in seconds |
| `LOG_LEVEL` | `INFO` | `DEBUG` / `INFO` / `WARNING` |

---

## REST API Endpoints

### Terminals
| Method | Path | Description |
|---|---|---|
| GET | `/terminals` | List all terminals |
| GET | `/terminals/online` | List currently connected phones |
| GET | `/terminals/{phone}` | Get terminal details |

### Location
| Method | Path | Description |
|---|---|---|
| GET | `/terminals/{phone}/locations` | Location history (`?limit=100&offset=0`) |
| GET | `/terminals/{phone}/locations/latest` | Most recent position |

### Commands (0x8105)
| Method | Path | Body | Description |
|---|---|---|---|
| POST | `/terminals/{phone}/control` | `{"command":"power_on"}` | Send control command |

Available commands: `power_on`, `power_off`, `start_alarm`, `stop_alarm`

### Parameters
| Method | Path | Description |
|---|---|---|
| POST | `/terminals/{phone}/params/set` | Set ECU/geo-fence params (0x8103) |
| POST | `/terminals/{phone}/params/query` | Query params (0x8106) |

**Set params body example:**
```json
{
  "ecu_ignition_prohibited": true,
  "geofence_enabled": true
}
```

### Logs
| Method | Path | Description |
|---|---|---|
| GET | `/terminals/{phone}/commands` | Command send/ACK history |
| GET | `/health` | Server health + online count |

---

## Project Structure

```
jt808_server/
├── main.py               # Entry point (TCP + HTTP concurrent)
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
└── jt808/
    ├── __init__.py
    ├── protocol.py       # Full JT/T 808 codec (encode/decode/escape/checksum)
    ├── models.py         # SQLAlchemy DB models
    ├── handlers.py       # Per-message-ID business logic
    ├── server.py         # Async TCP server
    └── api.py            # FastAPI REST endpoints
```

---

## Adding Support for More Message IDs

1. Add the constant to `protocol.py`
2. Add a builder function to `protocol.py`
3. Add a handler in `handlers.py`
4. Add the `elif mid == MSG_XXX` case in `handlers.dispatch()`
5. Add the API endpoint in `api.py`
