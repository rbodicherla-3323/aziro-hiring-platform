# AZIRO AI HIRING PLATFORM -- PRODUCTION DEPLOYMENT DOCUMENT

```
Application:   Aziro AI Hiring Platform
Domain:        https://azirohire.aziro.com
Server:        Ubuntu 22.04 LTS VM (ESXi hosted)
Stack:         Python 3.10 / Flask 3.1 / Gunicorn / Nginx / SQLite
SSL:           Cloudflare Origin Certificate (valid 2025-2040)
Deployed by:   Ravi Kumar Bodicherla
Date:          March 2026
```

---

## TABLE OF CONTENTS

| #  | Section                                     |
|----|---------------------------------------------|
| 1  | Architecture Overview                       |
| 2  | Prerequisites -- What IT Provided           |
| 3  | VM Initial Setup (SSH + System Packages)    |
| 4  | Install Coding-Round Compilers              |
| 5  | Clone Application Code                      |
| 6  | Python Virtual Environment and Dependencies |
| 7  | SSL Certificate Placement                   |
| 8  | Environment Configuration (.env)            |
| 9  | Gunicorn -- Application Server (systemd)    |
| 10 | Nginx -- Reverse Proxy and Static Files     |
| 11 | File Permissions (Critical)                 |
| 12 | DNS and Cloudflare Configuration            |
| 13 | Verification and Smoke Tests                |
| 14 | Automated Deploy Script                     |
| 15 | Maintenance and Operations                  |
| 16 | Troubleshooting                             |
| 17 | Reference -- All File Paths                 |
| 18 | Quick-Reference: Full Deploy From Scratch   |
