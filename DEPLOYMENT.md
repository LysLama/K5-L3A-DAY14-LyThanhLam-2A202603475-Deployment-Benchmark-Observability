# Deployment Information — Day 14 Production Agent

## Public URL
https://agent-production-f69af683.up.railway.app

## Platform
Railway (deploy trực tiếp từ thư mục `06-lab-complete/` bằng `railway.toml` + `Dockerfile` multi-stage, kèm managed Redis service `Redis`)

## Environment Variables Set on Platform
- `PORT` *(do Railway tự cấp — `8080`, `Dockerfile` dùng `exec uvicorn ... --port ${PORT:-8000}`)*
- `ENVIRONMENT=production`
- `REDIS_URL=${{Redis.REDIS_URL}}` *(trỏ tới managed Redis service trong cùng Railway project)*
- `AGENT_API_KEY` *(đặt trên Railway, không commit vào mã nguồn hay git)*
- `RATE_LIMIT_PER_MINUTE=10`
- `DAILY_BUDGET_USD=1.0`
- `MONTHLY_BUDGET_USD=10.0`

## Test Commands (4 lệnh tự kiểm CP6)

```bash
export BASE="https://agent-production-f69af683.up.railway.app"
export AGENT_API_KEY="<YOUR_API_KEY>"

# 1. Liveness probe -> 200
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/health"

# 2. Readiness probe (kết nối Redis thành công) -> 200
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/ready"

# 3. Gọi /ask không có API key -> 401
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" \
  -H 'Content-Type: application/json' \
  -d '{"question":"Hello"}'

# 4. Gọi /ask có API key hợp lệ -> 200
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" \
  -H 'Content-Type: application/json' \
  -H "X-API-Key: $AGENT_API_KEY" \
  -d '{"question":"Hello"}'
```

### Kết quả kiểm chứng thực tế

```text
1. GET  /health              -> 200  {"status":"ok","environment":"production","uptime_seconds":10.8}
2. GET  /ready               -> 200  {"status":"ready"}
3. POST /ask (no X-API-Key)  -> 401  {"detail":"Invalid or missing X-API-Key"}
4. POST /ask (valid key)     -> 200  {"question":"Hello","answer":"Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé.","usage":{"input_tokens":1,"output_tokens":16,"cost_usd":1e-05}}
```

## Screenshots
- [Deployment dashboard](screenshots/dashboard.png)
- [Service running](screenshots/running.png)
- [Test results](screenshots/test.png)
