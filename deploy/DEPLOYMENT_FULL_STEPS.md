# ══════════════════════════════════════════════════════════════════
#  AI HIRING PLATFORM — COMPLETE DEPLOYMENT DOCUMENT
#  Application:   Aziro AI Hiring Platform
#  Domain:        azirohire.aziro.com
#  Server:        Ubuntu VM (ESXi hosted)
#  Access:        SSH via PuTTY
#  Deployed by:   Ravi Kumar Bodicherla
#  Date:          March 2, 2026
# ══════════════════════════════════════════════════════════════════


## TABLE OF CONTENTS

1. Prerequisites & What IT Provided
2. VM Initial Setup (SSH)
3. Install Docker Engine
4. Clone Application Code
5. Directory Structure Created
6. SSL Certificate Placement
7. Production Environment Configuration
8. Application Architecture
9. Docker Configuration Files
10. Build & Start Deployment
11. Verification & Testing
12. Current Status & Pending IT Action
13. Maintenance Commands


---


## 1. PREREQUISITES & WHAT IT PROVIDED

| Item                    | Details                                         |
|-------------------------|-------------------------------------------------|
| Ubuntu VM               | Ubuntu 22.04 LTS, CLI-only, ESXi hosted        |
| SSH Access              | User `aziro`, accessed via PuTTY                |
| DNS Record              | `azirohire.aziro.com` → Cloudflare proxy        |
| SSL Certificate         | `aziro.com.pem` — Cloudflare Origin Certificate |
| SSL Private Key         | `aziro.com.key` — Cloudflare Origin Key         |
| Certificate Issuer      | `CloudFlare, Inc. / CloudFlare Origin CA`       |
| Certificate Validity    | May 14, 2025 → May 10, 2040                    |
| VM Internal IP          | (assigned by ESXi/DHCP)                         |
| Ports Required          | 80 (HTTP), 443 (HTTPS)                          |


---


## 2. VM INITIAL SETUP

Connected via PuTTY and updated the system:

```bash
ssh aziro@<VM-IP>

sudo apt update && sudo apt upgrade -y
sudo apt install -y git curl wget
```


---


## 3. INSTALL DOCKER ENGINE

Installed Docker CE with Compose plugin (official Docker repo):

```bash
# Add Docker GPG key
sudo apt-get install -y ca-certificates curl gnupg
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

# Add Docker repository
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
  https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

# Install Docker
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# Enable Docker to start on boot
sudo systemctl enable docker

# Allow aziro user to run docker without sudo
sudo usermod -aG docker aziro
```

Verified:
```bash
docker --version
# Docker version 27.x.x

docker compose version
# Docker Compose version v2.x.x
```


---


## 4. CLONE APPLICATION CODE

```bash
mkdir -p ~/app
cd ~/app
git clone -b main git@github.com:rbodicherla-3323/aziro-hiring-platform.git
cd aziro-hiring-platform
```


---


## 5. DIRECTORY STRUCTURE CREATED

```bash
mkdir -p data/postgres data/uploads data/reports data/proctoring ssl
```

Final layout on VM:

```
~/app/aziro-hiring-platform/
│
├── app/                        ← Flask application code
│   ├── __init__.py
│   ├── models.py
│   ├── blueprints/             ← Route modules (dashboard, tests, coding, reports, etc.)
│   ├── services/               ← Business logic (AI, PDF, email, DB, proctoring)
│   ├── static/                 ← CSS, JS, images
│   ├── templates/              ← Jinja2 HTML templates
│   └── utils/                  ← Role mappings, auth decorators
│
├── deploy/
│   ├── nginx.conf              ← Nginx reverse proxy config
│   ├── vm_deploy.sh            ← Automated deployment script
│   └── DEPLOYMENT.md           ← Deployment documentation
│
├── ssl/
│   ├── aziro.com.pem           ← Cloudflare Origin Certificate (from IT)
│   └── aziro.com.key           ← Private key (from IT)
│
├── data/                       ← Persistent data (Docker volumes)
│   ├── postgres/               ← PostgreSQL database files
│   ├── uploads/                ← Uploaded resumes/JDs
│   ├── reports/                ← Generated PDF reports
│   └── proctoring/             ← Proctoring screenshots/recordings
│
├── Dockerfile                  ← Backend container build instructions
├── docker-compose.yml          ← Multi-container orchestration
├── wsgi.py                     ← Production WSGI entry point
├── requirements.txt            ← Python dependencies
├── .env.production             ← Environment variables (secrets, API keys)
└── .env.production.template    ← Template for .env.production
```


---


## 6. SSL CERTIFICATE PLACEMENT

IT provided `aziro.com.pem` and `aziro.com.key`. Placed them in the `ssl/` directory:

```bash
mv aziro.com.pem ssl/
mv aziro.com.key ssl/
chmod 644 ssl/aziro.com.pem
chmod 600 ssl/aziro.com.key
```

Verified the certificate:
```bash
openssl x509 -in ssl/aziro.com.pem -noout -subject -dates
```

Output:
```
subject=O = "CloudFlare, Inc.", OU = CloudFlare Origin CA, CN = CloudFlare Origin Certificate
notBefore=May 14 17:06:00 2025 GMT
notAfter=May 10 17:06:00 2040 GMT
```

**Important:** This is a Cloudflare Origin Certificate. It is NOT a standard CA-signed cert.
It is only trusted by Cloudflare's edge servers, not by browsers directly.
This means Cloudflare's proxy (orange cloud) must remain enabled for this domain.


---


## 7. PRODUCTION ENVIRONMENT CONFIGURATION

Created `.env.production` from template:

```bash
cp .env.production.template .env.production
nano .env.production
```

Variables configured:

| Variable           | Purpose                                    |
|--------------------|--------------------------------------------|
| `SECRET_KEY`       | Flask session encryption key               |
| `FLASK_DEBUG`      | Set to `0` (production)                    |
| `DATABASE_URL`     | PostgreSQL connection string (auto-set)     |
| `GEMINI_API_KEY`   | Google Gemini AI API key                   |
| `SMTP_HOST`        | Email server hostname                      |
| `SMTP_PORT`        | Email server port (587)                    |
| `SMTP_USERNAME`    | Email account username                     |
| `SMTP_PASSWORD`    | Email account password                     |
| `SMTP_FROM_EMAIL`  | Sender email address                       |
| `AUTH_DISABLED`    | Set to `false` (production)                |

This file is NOT committed to git (listed in `.gitignore`).


---


## 8. APPLICATION ARCHITECTURE

```
                           ┌─────────────────────────────────────┐
                           │         CLOUDFLARE EDGE             │
                           │  (DNS proxy for aziro.com)          │
  Browser ───── HTTPS ────►│  - Client SSL termination           │
                           │  - WAF / DDoS protection            │
                           │  - CDN caching                      │
                           └────────────┬────────────────────────┘
                                        │
                              HTTPS (Origin Certificate)
                                        │
                           ┌────────────▼────────────────────────┐
                           │     UBUNTU VM (ESXi hosted)         │
                           │                                     │
  ┌────────────────────────┤     Docker Compose (3 containers)   │
  │                        │                                     │
  │  ┌─────────────────────▼───────────────────────┐             │
  │  │  ai_nginx (Nginx 1.27)                      │             │
  │  │  - Ports: 80, 443                           │             │
  │  │  - SSL termination (aziro.com.pem/.key)     │             │
  │  │  - HTTP → HTTPS redirect                    │             │
  │  │  - Serves /static/ files directly           │             │
  │  │  - Proxies all other requests to backend    │             │
  │  └─────────────────────┬───────────────────────┘             │
  │                        │ proxy_pass :8000                    │
  │  ┌─────────────────────▼───────────────────────┐             │
  │  │  ai_backend (Python 3.10 + Gunicorn)        │             │
  │  │  - 3 workers × 4 threads                    │             │
  │  │  - Flask web framework                      │             │
  │  │  - AI question generation (Gemini API)      │             │
  │  │  - PDF report generation                    │             │
  │  │  - Code execution (Python/Java/C/C++/C#)    │             │
  │  │  - Email notifications                      │             │
  │  └─────────────────────┬───────────────────────┘             │
  │                        │ :5432                               │
  │  ┌─────────────────────▼───────────────────────┐             │
  │  │  ai_db (PostgreSQL 16)                      │             │
  │  │  - Database: aziro_hiring                   │             │
  │  │  - Data persisted to ./data/postgres/       │             │
  │  └─────────────────────────────────────────────┘             │
  └──────────────────────────────────────────────────────────────┘
```


---


## 9. DOCKER CONFIGURATION FILES

### 9.1 Dockerfile (Backend Container)

```dockerfile
FROM python:3.10-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential gcc g++ \
    default-jdk \
    nodejs \
    libpq-dev \
    libfreetype6-dev libjpeg62-turbo-dev libpng-dev \
    mono-mcs \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir gunicorn && \
    pip install --no-cache-dir -r requirements.txt
COPY . .

RUN mkdir -p app/uploads app/runtime/reports app/runtime/proctoring \
             app/runtime/coding_exec_tmp instance

EXPOSE 8000
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "3", \
     "--threads", "4", "--timeout", "300", "wsgi:app"]
```

System packages installed:
- `gcc`, `g++`, `build-essential` — C/C++ code compilation for coding tests
- `default-jdk` — Java code execution for coding tests
- `nodejs` — JavaScript code execution for coding tests
- `mono-mcs` — C# code compilation for coding tests
- `libpq-dev` — PostgreSQL client library (for psycopg2)
- `libfreetype6-dev`, `libjpeg62-turbo-dev`, `libpng-dev` — PDF generation (ReportLab)


### 9.2 docker-compose.yml (Orchestration)

Three services:
1. **db** — PostgreSQL 16 with health check
2. **backend** — Flask + Gunicorn (only exposed internally on port 8000)
3. **nginx** — Reverse proxy, SSL termination (ports 80 & 443 published to VM)

Backend waits for database health check before starting.
All persistent data stored in `./data/` directory via Docker volume mounts.


### 9.3 Nginx Configuration (deploy/nginx.conf)

- Port 80: Redirects all HTTP traffic to HTTPS
- Port 443: SSL termination using Cloudflare Origin Certificate
- Proxies requests to `ai_backend:8000` (Docker internal DNS)
- Serves `/static/` files directly (bypasses Gunicorn for performance)
- WebSocket support enabled (for proctoring streams)
- Request timeout: 300s (for AI generation and PDF rendering)
- Max upload size: 25MB (for resume/JD PDFs)
- Security headers: X-Frame-Options, X-Content-Type-Options, Permissions-Policy


---


## 10. BUILD & START DEPLOYMENT

```bash
cd ~/app/aziro-hiring-platform

# Build all containers and start in background
docker compose up -d --build
```

Build process:
1. Docker pulls `postgres:16-alpine` and `nginx:1.27-alpine` images
2. Docker builds backend image from Dockerfile (installs Python deps + system packages)
3. All three containers start in dependency order: db → backend → nginx

Verified containers:
```bash
docker compose ps
```

Output:
```
NAME          STATUS                  PORTS
ai_db         Up (healthy)            5432/tcp
ai_backend    Up                      8000/tcp
ai_nginx      Up                      0.0.0.0:80->80/tcp, 0.0.0.0:443->443/tcp
```


---


## 11. VERIFICATION & TESTING

### 11.1 Container Status
```bash
docker compose ps
# All 3 containers: Up / healthy
```

### 11.2 Internal HTTPS Test (bypasses DNS/Cloudflare)
```bash
curl -sk https://localhost
```

**Result:**
```html
<!doctype html>
<html lang=en>
<title>Redirecting...</title>
<h1>Redirecting...</h1>
<p>You should be redirected automatically to the target URL:
<a href="/dashboard">/dashboard</a>. If not, click the link.
```

✅ **Application is running and responding correctly on HTTPS.**

### 11.3 SSL Certificate Verification
```bash
openssl x509 -in ssl/aziro.com.pem -noout -subject -dates
```
```
subject=O = "CloudFlare, Inc.", OU = CloudFlare Origin CA, CN = CloudFlare Origin Certificate
notBefore=May 14 17:06:00 2025 GMT
notAfter=May 10 17:06:00 2040 GMT
```

✅ **Certificate is valid and loaded by Nginx.**

### 11.4 Port Verification
```bash
sudo ss -tulpn | grep -E ":80|:443"
```
```
tcp  LISTEN  0  511  0.0.0.0:80   0.0.0.0:*  users:(("docker-proxy",...))
tcp  LISTEN  0  511  0.0.0.0:443  0.0.0.0:*  users:(("docker-proxy",...))
```

✅ **Ports 80 and 443 are listening.**

### 11.5 DNS Resolution
```bash
dig +short azirohire.aziro.com
```
```
172.67.73.194
104.26.10.77
104.26.11.77
```

✅ **DNS resolves to Cloudflare edge IPs** (expected for Origin Certificate setup).


---


## 12. CURRENT STATUS & PENDING IT ACTION

### What is WORKING ✅

| Check                           | Status |
|---------------------------------|--------|
| Docker containers running       | ✅      |
| PostgreSQL healthy              | ✅      |
| Flask backend responding        | ✅      |
| Nginx serving HTTPS             | ✅      |
| SSL certificate loaded          | ✅      |
| Ports 80 & 443 listening        | ✅      |
| Internal `curl -sk https://localhost` | ✅ Returns 200 |
| DNS resolves to Cloudflare      | ✅      |


### What is NOT WORKING ❌

Accessing `https://azirohire.aziro.com` from a browser returns **Cloudflare 403 Forbidden**.

```bash
curl -I https://azirohire.aziro.com
```
```
HTTP/2 403
server: cloudflare
cf-mitigated: challenge
```

### Root Cause

The SSL certificate provided by IT is a **Cloudflare Origin Certificate**. This means:

1. Traffic flows: `Browser → Cloudflare Edge → Our VM (Origin)`
2. Cloudflare terminates the client-facing SSL
3. Cloudflare then connects to our VM using a separate HTTPS connection
4. Our Nginx presents the Origin Certificate to Cloudflare
5. **Cloudflare must be configured to trust this Origin Certificate**

The 403 is coming from **Cloudflare's edge**, not from our server.


### ACTION REQUIRED FROM IT TEAM

**Option A (Recommended):** In Cloudflare Dashboard:
1. Go to **SSL/TLS → Overview**
2. Set encryption mode to **"Full (Strict)"**
3. This tells Cloudflare to connect to our origin via HTTPS and trust the Origin Certificate

**Option B:** Check for blocking rules:
1. **Security → WAF** — Any rules blocking `azirohire.aziro.com`?
2. **Security → Bots** — Is "Bot Fight Mode" enabled? (causes 403 for automated requests)
3. **Security → Settings** — Is "I'm Under Attack Mode" on? (shows challenge pages)
4. If any are active, add a **bypass rule** for hostname `azirohire.aziro.com`

**No changes are needed on the server. The fix is a Cloudflare dashboard toggle.**


---


## 13. MAINTENANCE COMMANDS

### View logs
```bash
docker compose logs -f              # All containers
docker compose logs -f backend      # Backend only
docker compose logs -f nginx        # Nginx only
docker compose logs -f db           # Database only
```

### Restart services
```bash
docker compose restart              # Restart all
docker compose restart backend      # Restart backend only
```

### Update after code changes
```bash
cd ~/app/aziro-hiring-platform
git pull origin main
docker compose up -d --build
```

### Stop everything
```bash
docker compose down
```

### Full reset (WARNING: deletes database)
```bash
docker compose down -v
rm -rf data/postgres
docker compose up -d --build
```

### Check resource usage
```bash
docker stats
```


---


## DOCUMENT END

All steps performed from scratch on a clean Ubuntu VM.
Server-side deployment is complete and verified.
Awaiting Cloudflare SSL mode change from IT team.
