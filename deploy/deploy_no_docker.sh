#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────
# Aziro Hiring Platform — Deploy WITHOUT Docker
# Uses: system Nginx + Gunicorn (in venv) + SQLite
# Run: bash deploy/deploy_no_docker.sh
# ──────────────────────────────────────────────────────────────
set -euo pipefail

APP_DIR="$HOME/app/aziro-hiring-platform"
VENV_DIR="$APP_DIR/venv"

echo "═══════════════════════════════════════════"
echo "  Aziro Hiring Platform — Deploy (no Docker)"
echo "═══════════════════════════════════════════"

# ── 1. Pull latest code ──
echo ""
echo "▸ Pulling latest code from origin/main..."
cd "$APP_DIR"
git pull origin main

# ── 2. Activate venv & install deps ──
echo ""
echo "▸ Installing Python dependencies..."
source "$VENV_DIR/bin/activate"
pip install --upgrade pip -q
pip install gunicorn -q
pip install -r requirements.txt -q

# ── 3. Create runtime directories ──
echo ""
echo "▸ Creating runtime directories..."
mkdir -p app/uploads app/runtime/reports app/runtime/proctoring \
         app/runtime/coding_exec_tmp instance

# ── 4. Create .env if missing ──
if [ ! -f "$APP_DIR/.env" ]; then
    echo ""
    echo "▸ Creating .env file (edit with your actual keys)..."
    cat > "$APP_DIR/.env" << 'ENVEOF'
SECRET_KEY=aziro-prod-secret-change-me
GEMINI_API_KEY=your-gemini-api-key-here
AUTH_DISABLED=true
ENVEOF
    echo "  ⚠ EDIT .env with your actual GEMINI_API_KEY!"
fi

# ── 5. Install coding round compilers (if not already) ──
echo ""
echo "▸ Checking coding round compilers..."
for cmd in gcc g++ javac node mcs mono; do
    if command -v $cmd &>/dev/null; then
        echo "  ✓ $cmd found"
    else
        echo "  ✗ $cmd NOT found (install separately if needed)"
    fi
done

# Ensure mono-runtime is installed (mcs compiles, mono executes .exe on Linux)
if ! command -v mono &>/dev/null; then
    echo "  ⚠ Installing mono-runtime (needed to run compiled C# on Linux)..."
    sudo apt install -y mono-runtime 2>/dev/null || echo "  ✗ Could not install mono-runtime automatically"
fi

# ── 6. Setup systemd service for Gunicorn ──
echo ""
echo "▸ Setting up Gunicorn systemd service..."
sudo tee /etc/systemd/system/aziro.service > /dev/null << SVCEOF
[Unit]
Description=Aziro Hiring Platform (Gunicorn)
After=network.target

[Service]
User=$USER
Group=$USER
WorkingDirectory=$APP_DIR
EnvironmentFile=$APP_DIR/.env
ExecStart=$VENV_DIR/bin/gunicorn --bind 127.0.0.1:8000 --workers 1 --threads 8 --timeout 300 wsgi:app
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
SVCEOF

sudo systemctl daemon-reload
sudo systemctl enable aziro
sudo systemctl restart aziro
echo "  ✓ Gunicorn service started on 127.0.0.1:8000"

# ── 7. Setup Nginx ──
echo ""
echo "▸ Configuring Nginx..."
sudo tee /etc/nginx/sites-available/aziro > /dev/null << 'NGXEOF'
# ─── Redirect HTTP → HTTPS ──────────────────────────────────────
server {
    listen 80;
    server_name azirohire.aziro.com;
    return 301 https://$host$request_uri;
}

# ─── HTTPS server ───────────────────────────────────────────────
server {
    listen 443 ssl http2;
    server_name azirohire.aziro.com;

    # ── SSL certificate ──
    ssl_certificate     /etc/nginx/ssl/aziro.com.pem;
    ssl_certificate_key /etc/nginx/ssl/aziro.com.key;

    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_prefer_server_ciphers on;
    ssl_ciphers ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305:DHE-RSA-AES128-GCM-SHA256:DHE-RSA-AES256-GCM-SHA384;
    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 10m;

    # ── Security headers ──
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;
    add_header Permissions-Policy "display-capture=(self), camera=(self), microphone=(self), fullscreen=(self)" always;

    # ── Body size (PDF uploads, resumes) ──
    client_max_body_size 25M;    # ── Static files — served directly by Nginx ──
    location /static/ {
        alias __APP_DIR__/app/static/;
        expires 1h;
        add_header Cache-Control "public, must-revalidate";
    }

    # ── Proxy to Gunicorn ──
    location / {
        proxy_pass http://127.0.0.1:8000;

        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # WebSocket support
        proxy_http_version 1.1;
        proxy_set_header Upgrade    $http_upgrade;
        proxy_set_header Connection "upgrade";

        # Timeouts for long AI/PDF generation calls
        proxy_connect_timeout 60s;
        proxy_send_timeout    300s;
        proxy_read_timeout    300s;
    }
}
NGXEOF

# Replace placeholder with actual app directory
sudo sed -i "s|__APP_DIR__|$APP_DIR|g" /etc/nginx/sites-available/aziro

# Fix permissions so Nginx (www-data) can read static files
echo "  Setting static file permissions..."
sudo chmod -R o+rX "$APP_DIR/app/static/"
sudo chmod o+x "$HOME" "$HOME/app" "$APP_DIR" "$APP_DIR/app"

# Enable site & remove default
sudo ln -sf /etc/nginx/sites-available/aziro /etc/nginx/sites-enabled/aziro
sudo rm -f /etc/nginx/sites-enabled/default

# Test & reload nginx
sudo nginx -t && sudo systemctl reload nginx
echo "  ✓ Nginx configured and reloaded"

# ── 8. Status check ──
echo ""
echo "═══════════════════════════════════════════"
echo "  ✓ Deployment complete!"
echo "═══════════════════════════════════════════"
echo ""
echo "  App URL:  https://azirohire.aziro.com"
echo "  Gunicorn: sudo systemctl status aziro"
echo "  Nginx:    sudo systemctl status nginx"
echo "  Logs:     sudo journalctl -u aziro -f"
echo ""
echo "  To redeploy after code changes:"
echo "    cd $APP_DIR"
echo "    git pull origin main"
echo "    sudo systemctl restart aziro"
echo ""
