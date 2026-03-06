#!/bin/bash
# ════════════════════════════════════════════════════════════════════
#  AZIRO HIRING PLATFORM — DOCKER DEPLOYMENT SCRIPT
#  Run on Ubuntu VM via SSH (PuTTY)
#
#  Usage:
#    chmod +x deploy/vm_deploy.sh
#    sudo ./deploy/vm_deploy.sh
# ════════════════════════════════════════════════════════════════════
set -euo pipefail

DEPLOY_DIR="/opt/aziro-hiring-platform"
REPO_URL="git@github.com:rbodicherla-3323/aziro-hiring-platform.git"
BRANCH="main"

echo "═══════════════════════════════════════════════════"
echo "  Aziro Hiring Platform — Docker Deployment"
echo "═══════════════════════════════════════════════════"

# ── 1. Install Docker if missing ──
if ! command -v docker &>/dev/null; then
    echo "[1/7] Installing Docker..."
    apt-get update
    apt-get install -y ca-certificates curl gnupg
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    chmod a+r /etc/apt/keyrings/docker.gpg
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" > /etc/apt/sources.list.d/docker.list
    apt-get update
    apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
    systemctl enable docker
    echo "  ✓ Docker installed"
else
    echo "[1/7] Docker already installed — $(docker --version)"
fi

# ── 2. Clone / pull repo ──
if [ -d "$DEPLOY_DIR/.git" ]; then
    echo "[2/7] Pulling latest code..."
    cd "$DEPLOY_DIR"
    git fetch origin
    git checkout "$BRANCH"
    git pull origin "$BRANCH"
else
    echo "[2/7] Cloning repository..."
    git clone -b "$BRANCH" "$REPO_URL" "$DEPLOY_DIR"
    cd "$DEPLOY_DIR"
fi
echo "  ✓ Code ready at $DEPLOY_DIR"

# ── 3. Create data directories ──
echo "[3/7] Creating data directories..."
mkdir -p data/postgres data/uploads data/reports data/proctoring ssl
echo "  ✓ Directories created"

# ── 4. Check SSL certificates ──
echo "[4/7] Checking SSL certificates..."
if [ ! -f ssl/aziro.com.pem ] || [ ! -f ssl/aziro.com.key ]; then
    echo ""
    echo "  ╔══════════════════════════════════════════════════╗"
    echo "  ║  SSL CERTIFICATES NOT FOUND!                     ║"
    echo "  ║                                                  ║"
    echo "  ║  Copy your IT-provided certs to:                 ║"
    echo "  ║    $DEPLOY_DIR/ssl/aziro.com.pem                 ║"
    echo "  ║    $DEPLOY_DIR/ssl/aziro.com.key                 ║"
    echo "  ║                                                  ║"
    echo "  ║  Then re-run this script.                        ║"
    echo "  ╚══════════════════════════════════════════════════╝"
    echo ""
    exit 1
fi
# Verify cert is valid PEM
openssl x509 -in ssl/aziro.com.pem -noout -subject 2>/dev/null && echo "  ✓ SSL certificate valid" || {
    echo "  ✗ ssl/aziro.com.pem is not a valid certificate!"
    exit 1
}

# ── 5. Check .env.production ──
echo "[5/7] Checking production environment file..."
if [ ! -f .env.production ]; then
    echo "  Creating .env.production from template..."
    cp .env.production.template .env.production
    echo ""
    echo "  ╔══════════════════════════════════════════════════╗"
    echo "  ║  EDIT .env.production WITH YOUR REAL VALUES!     ║"
    echo "  ║                                                  ║"
    echo "  ║  nano $DEPLOY_DIR/.env.production                ║"
    echo "  ║                                                  ║"
    echo "  ║  At minimum set:                                 ║"
    echo "  ║    SECRET_KEY=<random-string>                    ║"
    echo "  ║    GEMINI_API_KEY=<your-key>                     ║"
    echo "  ║                                                  ║"
    echo "  ║  Then re-run this script.                        ║"
    echo "  ╚══════════════════════════════════════════════════╝"
    echo ""
    exit 1
fi
echo "  ✓ .env.production exists"

# ── 6. Build & deploy ──
echo "[6/7] Building and starting containers..."
docker compose down --remove-orphans 2>/dev/null || true
docker compose up -d --build

echo "  Waiting for containers to be healthy..."
sleep 10

# ── 7. Verify ──
echo "[7/7] Verifying deployment..."
echo ""

# Check containers
for svc in ai_db ai_backend ai_nginx; do
    status=$(docker inspect -f '{{.State.Status}}' "$svc" 2>/dev/null || echo "missing")
    if [ "$status" = "running" ]; then
        echo "  ✓ $svc — running"
    else
        echo "  ✗ $svc — $status"
    fi
done

echo ""

# Test internal connectivity
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" http://localhost 2>/dev/null || echo "000")
if [ "$HTTP_CODE" = "301" ] || [ "$HTTP_CODE" = "200" ]; then
    echo "  ✓ HTTP (port 80) → $HTTP_CODE (redirect to HTTPS)"
else
    echo "  ✗ HTTP (port 80) → $HTTP_CODE"
fi

HTTPS_CODE=$(curl -sk -o /dev/null -w "%{http_code}" https://localhost 2>/dev/null || echo "000")
if [ "$HTTPS_CODE" = "200" ] || [ "$HTTPS_CODE" = "302" ]; then
    echo "  ✓ HTTPS (port 443) → $HTTPS_CODE"
else
    echo "  ✗ HTTPS (port 443) → $HTTPS_CODE (check: docker logs ai_nginx)"
fi

echo ""
echo "═══════════════════════════════════════════════════"
echo "  Deployment complete!"
echo ""
echo "  Internal test:  curl -sk https://localhost"
echo "  External URL:   https://azirohire.aziro.com"
echo ""
echo "  Logs:  docker logs ai_nginx"
echo "         docker logs ai_backend"
echo "         docker logs ai_db"
echo "═══════════════════════════════════════════════════"
