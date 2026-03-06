# Aziro Hiring Platform — VM Deployment & Cloudflare Fix
## DNS: azirohire.aziro.com

---

## Quick Deploy (on the VM)

```bash
# 1. SSH into VM via PuTTY

# 2. Pull latest code
cd /opt/aziro-hiring-platform
git pull origin main

# 3. Place SSL certs (from IT)
#    Copy aziro.com.pem and aziro.com.key into ssl/ directory

# 4. Create production env
cp .env.production.template .env.production
nano .env.production    # fill in GEMINI_API_KEY, SECRET_KEY, SMTP creds

# 5. Deploy
sudo chmod +x deploy/vm_deploy.sh
sudo ./deploy/vm_deploy.sh
```

---

## THE CLOUDFLARE 403 ISSUE — ROOT CAUSE & FIX

### What's happening

```
You (browser)  →  Cloudflare Proxy  →  Your VM (Nginx)
                       ↑
                  403 happens HERE
```

Your IT team's DNS for `aziro.com` routes through **Cloudflare** (orange-cloud / proxy mode). When Cloudflare proxies the request, it does its own TLS handshake with the client, then makes a **separate** TLS connection to your VM. This means:

1. **Cloudflare terminates SSL first** (client → Cloudflare)
2. Cloudflare then connects to your VM origin (Cloudflare → Nginx)
3. If Cloudflare's SSL mode is set to **"Flexible"** or **"Off"**, it tries HTTP to your VM — but your Nginx redirects HTTP → HTTPS → infinite loop / 403
4. If Cloudflare's SSL mode is **"Full"** but your cert isn't trusted by Cloudflare, it may reject

### What IT needs to do (ONE of these)

#### Option A: Set Cloudflare SSL to "Full (Strict)" ✅ RECOMMENDED
In Cloudflare Dashboard → SSL/TLS → Overview:
- Set mode to **Full (Strict)**
- This means Cloudflare connects to your VM via HTTPS and validates your corporate cert
- Your IT-issued `aziro.com.pem` signed by a real CA will work perfectly

#### Option B: Set Cloudflare SSL to "Full"
- Same as above but Cloudflare won't validate the origin cert
- Works with self-signed certs too
- Less secure but simpler

#### Option C: DNS-Only mode (grey cloud) for azirohire subdomain
In Cloudflare Dashboard → DNS → find `azirohire` record:
- Click the orange cloud icon to turn it **grey** (DNS only)
- This bypasses Cloudflare proxy entirely
- Traffic goes directly: browser → your VM Nginx
- Your corporate SSL cert handles everything
- **This is the simplest fix if they don't need Cloudflare WAF/CDN for this subdomain**

### What to tell IT (copy-paste this)

> We deployed our application on the VM with Nginx handling HTTPS on ports 80/443
> using the corporate SSL certificate (aziro.com.pem + .key) you provided.
>
> The application works perfectly when accessed directly on the VM
> (`curl -sk https://localhost` returns 200).
>
> The Cloudflare 403 happens because the `azirohire.aziro.com` DNS record
> is proxied through Cloudflare (orange cloud). We need ONE of these changes:
>
> 1. **(Preferred)** Set Cloudflare SSL/TLS mode to **"Full (Strict)"** for aziro.com
> 2. **OR** Switch the `azirohire` DNS record to **DNS-only mode** (grey cloud)
>    so traffic reaches our VM directly without Cloudflare proxy
>
> The fix is a single toggle in the Cloudflare dashboard. No changes needed on our server.

---

## Verify After IT Makes the Change

```bash
# From the VM itself:
curl -I https://azirohire.aziro.com

# Expected:
# HTTP/2 200   (or 302 redirect to login)
# server: nginx/1.27
```

```bash
# Check DNS is resolving to your VM IP (not Cloudflare):
dig +short azirohire.aziro.com
# Should show your VM's IP, NOT 104.x.x.x (Cloudflare IPs)

# If it shows Cloudflare IPs, the orange cloud is still on
# If it shows your VM IP, DNS-only mode is active
```

---

## Architecture

```
┌─────────────┐    443    ┌──────────────────────────────────────┐
│   Browser   │ ────────→ │  Nginx (ai_nginx container)          │
└─────────────┘           │  - SSL termination (aziro.com.pem)   │
                          │  - /static/ served directly           │
                          │  - everything else → proxy_pass       │
                          └──────────────┬───────────────────────┘
                                         │ :8000 (internal)
                          ┌──────────────▼───────────────────────┐
                          │  Gunicorn + Flask (ai_backend)        │
                          │  - 3 workers, 4 threads each          │
                          │  - wsgi.py entry point                │
                          └──────────────┬───────────────────────┘
                                         │ :5432 (internal)
                          ┌──────────────▼───────────────────────┐
                          │  PostgreSQL 16 (ai_db)                │
                          │  - data persisted in ./data/postgres  │
                          └──────────────────────────────────────┘
```

## Container Management

```bash
# View status
docker compose ps

# View logs (follow)
docker compose logs -f

# Restart everything
docker compose restart

# Full rebuild after code changes
git pull origin main
docker compose up -d --build

# Stop everything
docker compose down

# Nuclear reset (deletes DB data!)
docker compose down -v
rm -rf data/postgres
docker compose up -d --build
```

## File Locations on VM

| What | Path |
|---|---|
| Application code | `/opt/aziro-hiring-platform/` |
| SSL certificates | `/opt/aziro-hiring-platform/ssl/` |
| Production env | `/opt/aziro-hiring-platform/.env.production` |
| Nginx config | `/opt/aziro-hiring-platform/deploy/nginx.conf` |
| DB data | `/opt/aziro-hiring-platform/data/postgres/` |
| Uploaded PDFs | `/opt/aziro-hiring-platform/data/uploads/` |
| Generated reports | `/opt/aziro-hiring-platform/data/reports/` |
| Proctoring data | `/opt/aziro-hiring-platform/data/proctoring/` |
