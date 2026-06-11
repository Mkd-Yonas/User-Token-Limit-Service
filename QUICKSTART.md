# Quick Start Guide

## What You Need
- A Linux server with Docker installed
- Terminal access (SSH or direct)

---

## Step 1 — Clone the project
```bash
git clone https://github.com/Mkd-Yonas/User-Token-Limit-Service.git
cd User-Token-Limit-Service
```

## Step 2 — Create config file
```bash
cp .env.example .env
```

## Step 3 — Start everything
```bash
docker compose -f docker/docker-compose.yml up -d
```
> Wait 15 seconds for everything to start.

## Step 4 — Check it's running
```bash
curl http://localhost:8000/health/ready
```
You should see:
```json
{"status":"ok","postgres":"ok","redis":"ok"}
```

## Step 5 — Open the API in browser
```
http://localhost:8000/docs
```
> If you're on a remote server, first run this on your **local PC**:
> ```bash
> ssh -L 8000:localhost:8000 your-user@your-server-ip -p your-port
> ```
> Then open `http://localhost:8000/docs` in your browser.

---

## Stop the project
```bash
docker compose -f docker/docker-compose.yml down
```

## Restart the project
```bash
docker compose -f docker/docker-compose.yml up -d
```

## Check what's running
```bash
docker ps
```

---

## Default API Keys
| Key | Value | Used For |
|-----|-------|---------|
| Service key | `sk-tls-changeme` | Spring API calls |
| Admin key | `sk-tls-admin-changeme` | Admin operations |

> Change these in `.env` before going to production.
