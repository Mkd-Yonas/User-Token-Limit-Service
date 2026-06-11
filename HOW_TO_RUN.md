# How to Run This Project

## 1. Start
```bash
cd ~/user-token-limit/tls-service
docker compose -f docker/docker-compose.yml up -d
```

## 2. Check it's running
```bash
curl http://localhost:8000/health/ready
```
Expected result:
```json
{"status":"ok","postgres":"ok","redis":"ok"}
```

## 3. Open in browser
```
http://localhost:8000/docs
```

## 4. Authorize in browser
- Click the **Authorize** button (top right)
- Enter: `sk-tls-changeme`
- Click **Authorize** → **Close**

## 5. Test an endpoint
- Click `POST /v1/limits/check`
- Click **Try it out** → **Execute**
- You should see `"allowed": true` ✓

> **Note:** The `422 Validation Error` shown at the bottom of each endpoint is just a documentation example — not a real error.

---

## Stop (keeps data)
```bash
docker compose -f docker/docker-compose.yml down
```

## Remove everything (data + volumes)
```bash
docker compose -f docker/docker-compose.yml down -v --rmi all
```

## Check what is running
```bash
docker ps
```
