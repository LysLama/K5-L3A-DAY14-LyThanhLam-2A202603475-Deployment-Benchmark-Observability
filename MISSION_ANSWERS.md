# Day 14 Lab — Mission Answers

> **Họ và tên:** Lý Thành Lâm  
> **MSSV:** 2A202603475  
> **Lớp:** K5-L3A  
> **Ngày thực hiện:** 2026-11-25

---

## Part 1: Localhost vs Production

### Exercise 1.1: Anti-patterns phát hiện trong `01-localhost-vs-production/develop/app.py`

1. **Hardcode secrets trực tiếp trong mã nguồn** (dòng 17–18):
   - `OPENAI_API_KEY = "sk-hardcoded-fake-key-never-do-this"`
   - `DATABASE_URL = "postgresql://admin:password123@localhost:5432/mydb"`
   - Nếu đẩy lên GitHub công khai, thông tin nhạy cảm bị lộ ngay lập tức và còn lưu trong lịch sử git.
2. **Log ra bí mật và dùng `print()` thay vì structured logging** (dòng 33–34, 38):
   - `print(f"[DEBUG] Using key: {OPENAI_API_KEY}")` làm rò rỉ API key ra stdout/log collector; log dạng chuỗi tự do khó lọc/phân tích trên Datadog/Loki/Cloud Logging.
3. **Không có cơ chế quản lý cấu hình theo môi trường** (dòng 21–22):
   - Cố định `DEBUG = True` và `MAX_TOKENS = 500` trong code, không thể chuyển đổi giữa `development` / `staging` / `production` mà không sửa code.
4. **Không có Health Check / Readiness endpoints** (dòng 42–43):
   - Thiếu `GET /health` (liveness) và `GET /ready` (readiness) khiến nền tảng cloud hoặc load balancer không biết container còn sống hay sẵn sàng nhận traffic để tự restart hoặc ngừng route.
5. **Bind cứng `host="localhost"`, `port=8000` và bật `reload=True`** (dòng 49–54):
   - `host="localhost"` không nhận được kết nối từ bên ngoài container; `port=8000` bỏ qua biến `PORT` do Railway/Render/Cloud Run cấp; `reload=True` gây tốn tài nguyên và mất an toàn trong production.
6. **Không có Graceful Shutdown và thiếu input validation rõ ràng**:
   - Không có `lifespan` hay xử lý `SIGTERM`, khi tắt đột ngột có thể cắt ngang request đang chạy; endpoint `/ask` nhận `question` qua query parameter thay vì JSON body có schema validation.

### Exercise 1.2: Kết quả chạy bản `develop`

Chạy `uvicorn app:app` trong `01-localhost-vs-production/develop/` và gọi `POST /ask?question=Hello`:

```text
HTTP/1.1 200 OK
date: Wed, 25 Nov 2026 09:09:13 GMT
server: uvicorn
content-length: 95
content-type: application/json

{"answer":"Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé."}
```

### Exercise 1.3: Bảng so sánh `develop` vs `production`

Kết quả kiểm tra bản `01-localhost-vs-production/production/app.py`:

```text
GET /health -> HTTP/1.1 200 OK
{"status":"ok","uptime_seconds":0.3,"version":"1.0.0","environment":"development","timestamp":"2026-11-25T09:09:14.768931+00:00"}

GET /ready -> HTTP/1.1 200 OK
{"ready":true}

POST /ask -> HTTP/1.1 200 OK
{"question":"Hello","answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận.","model":"gpt-4o-mini"}
```

| Feature | Develop (`develop/app.py`) | Production (`production/app.py` + `config.py`) | Tại sao quan trọng? |
| :--- | :--- | :--- | :--- |
| **Config & Secrets** | Hardcode `OPENAI_API_KEY`, `DATABASE_URL`, `PORT=8000`, `DEBUG=True` (dòng 17–22, 52) | Đọc từ biến môi trường qua `Settings` (`os.getenv`) trong `config.py` (dòng 17–35) và fail-fast bằng `validate()` (dòng 37–46) | Tuân thủ 12-Factor App: cùng một artifact/image chạy được trên dev/staging/prod mà không sửa code, không lộ secret lên git. |
| **Network binding** | `host="localhost"`, `port=8000`, `reload=True` (dòng 51–53) | `host="0.0.0.0"`, `port=settings.port`, `reload=settings.debug` (dòng 196–198) | Trong container phải nghe trên `0.0.0.0` và đúng cổng `PORT` do cloud platform inject; tắt auto-reload ở production để ổn định hiệu năng. |
| **Health check** | Không có (`404 Not Found`) | Có `GET /health` (liveness, dòng 135–149), `GET /ready` (readiness trả `503` khi chưa sẵn sàng, dòng 152–161) và `GET /metrics` (dòng 164–173) | Giúp orchestrator biết khi nào cần restart container bị treo (`/health`) và khi nào được phép route traffic vào (`/ready`). |
| **Logging** | `print()` plain text và in cả `OPENAI_API_KEY` (dòng 33–38) | Structured JSON logging (`logging.basicConfig` định dạng JSON, `json.dumps`, dòng 28–31, 111–122), chỉ log độ dài câu hỏi và IP, không log secret | Dễ ingest, truy vấn và tạo cảnh báo trên hệ thống tập trung (Loki, Datadog, Cloud Logging) đồng thời bảo vệ thông tin nhạy cảm. |
| **Shutdown** | Tắt đột ngột, không giải phóng tài nguyên | Dùng `lifespan` context manager (dòng 39–67) chuyển `is_ready = False`, chờ request hoàn thành và đăng ký `signal.SIGTERM` (dòng 180–189) | Tránh cắt ngang request đang xử lý (zero-downtime rolling deploy) và đóng kết nối DB/Redis an toàn. |
| **CORS & Input** | Không cấu hình CORS, nhận `question` qua query param | Cấu hình `CORSMiddleware` theo `ALLOWED_ORIGINS` (dòng 77–82), nhận JSON body và trả `422` khi thiếu `question` (dòng 102–108) | Kiểm soát nguồn truy cập hợp lệ từ trình duyệt và chuẩn hoá hợp đồng API. |

---

## Part 2: Docker Containerization

### Exercise 2.1: Phân tích `02-docker/develop/Dockerfile`

1. **Base image là gì?** `python:3.11` (dòng 8) — bản Debian đầy đủ đi kèm Python 3.11 và nhiều công cụ build/OS (~1+ GB).
2. **Working directory là gì?** `/app` (`WORKDIR /app`, dòng 11) — thư mục làm việc mặc định cho mọi lệnh `COPY`, `RUN`, `CMD` bên trong container.
3. **Tại sao `COPY requirements.txt` đứng trước `COPY app.py`?** Để tận dụng **Docker layer cache**: mỗi lệnh trong Dockerfile tạo một layer bất biến. Khi chỉ sửa mã nguồn `app.py` mà không đổi `requirements.txt`, Docker tái sử dụng cache của bước `RUN pip install`, rút ngắn thời gian build từ hàng phút xuống vài giây.
4. **`CMD` vs `ENTRYPOINT` khác nhau thế nào?**
   - `CMD` định nghĩa lệnh hoặc tham số mặc định khi chạy container và **dễ bị ghi đè** bởi tham số truyền sau `docker run <image> <command>`.
   - `ENTRYPOINT` cố định chương trình thực thi chính của container; tham số truyền thêm ở `docker run` (hoặc `CMD`) sẽ được nối vào làm đối số cho `ENTRYPOINT`.

### Exercise 2.2: Build và chạy `my-agent:develop`

Build từ thư mục gốc repo:

```bash
docker build -f 02-docker/develop/Dockerfile -t my-agent:develop .
docker run -d --rm --name p2-dev -p 8000:8000 my-agent:develop
curl -X POST "http://localhost:8000/ask?question=What%20is%20Docker?"
```

Kết quả thực tế nhận được từ container:

```text
HTTP 200: {"answer":"Container là cách đóng gói app để chạy ở mọi nơi. Build once, run anywhere!"}
```

### Exercise 2.3: Multi-stage build (`02-docker/production/Dockerfile`) và so sánh dung lượng

- **Stage 1 (`builder`, `FROM python:3.11-slim AS builder`)**: Cài `gcc`, `libpq-dev` và biên dịch/cài toàn bộ thư viện Python từ `requirements.txt` vào `/root/.local` bằng `pip install --no-cache-dir --user`.
- **Stage 2 (`runtime`, `FROM python:3.11-slim AS runtime`)**: Tạo image sạch mới hoàn toàn, tạo non-root user `appuser`, chỉ `COPY --from=builder /root/.local /home/appuser/.local` cùng mã nguồn `main.py` và `utils/mock_llm.py`, bổ sung `HEALTHCHECK` và chạy `uvicorn` với `--workers 2`.
- **Tại sao image nhỏ hơn?** Vì toàn bộ compiler (`gcc`), header hệ thống (`libpq-dev`), cache apt và công cụ build ở Stage 1 bị loại bỏ hoàn toàn khỏi image cuối, đồng thời stage cuối dùng base `python:3.11-slim` thay vì `python:3.11` đầy đủ.

**Kết quả đo thực tế bằng `docker images` và `docker image inspect`:**

```text
REPOSITORY   TAG        SIZE
my-agent     advanced   240MB
my-agent     develop    1.67GB
```

- **Develop (`my-agent:develop`):** `1.67 GB` (`1,667,792,367` bytes ≈ `1,590.5 MiB` / `1,667.8 MB`)
- **Production (`my-agent:advanced`):** `240 MB` (`239,815,374` bytes ≈ `228.7 MiB` / `239.8 MB`)
- **Chênh lệch:** Giảm **85.6%** dung lượng (nhỏ hơn ~6.95 lần).

### Exercise 2.4: Docker Compose stack (`02-docker/production/docker-compose.yml`)

**Sơ đồ kiến trúc stack:**

```text
Client (HTTP :80)
       │
       ▼
┌──────────────────────────────┐
│  nginx (nginx:alpine)        │  Reverse proxy + rate limit (10r/s) + security headers
│  ports: 80:80, 443:443       │
└──────────────┬───────────────┘
               │ network: internal (bridge)
               ▼
┌──────────────────────────────┐
│  agent (FastAPI + uvicorn)   │  Không mở port ra host, chỉ nhận traffic từ Nginx
│  port nội bộ: 8000           │
└───────┬──────────────┬───────┘
        │              │
        ▼              ▼
┌───────────────┐ ┌──────────────────┐
│ redis :6379   │ │ qdrant :6333     │
│ (redis:7-alp) │ │ (qdrant:v1.9.0)  │
│ vol:redis_data│ │ vol:qdrant_data  │
└───────────────┘ └──────────────────┘
```

- Các service khởi động: `redis` (healthcheck `redis-cli ping`), `qdrant` (healthcheck TCP 6333), `agent` (`depends_on` cả `redis` và `qdrant` với `condition: service_healthy`), và `nginx`. Tất cả giao tiếp qua mạng bridge nội bộ `internal` bằng tên service DNS (`redis`, `qdrant`, `agent`).

**Kết quả test thực tế qua Nginx (`docker compose -p k5-day14-docker up -d`):**

```text
GET http://127.0.0.1/health -> HTTP 200
{"status":"ok","uptime_seconds":8.2,"version":"2.0.0","timestamp":"2026-11-25T09:10:02.458541"}

POST http://127.0.0.1/ask -d '{"question":"Explain microservices"}' -> HTTP 200
{"answer":"Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé."}
```

---

## Part 3: Cloud Deployment

### Exercise 3.1 / 3.2: Deploy Agent Part 6 (`06-lab-complete/`)

- **Nền tảng chính:** Railway (project `day14-production-agent`, gồm 2 service: `agent` build từ `06-lab-complete/Dockerfile` + `06-lab-complete/railway.toml` và managed database `Redis` nối qua `REDIS_URL=${{Redis.REDIS_URL}}`).
- **Public URL:** https://agent-production-f69af683.up.railway.app (chi tiết biến môi trường và kết quả kiểm thử xem [DEPLOYMENT.md](DEPLOYMENT.md)).
- **Kết quả 4 lệnh tự kiểm CP6:**
  - `GET /health` → `200` (`{"status":"ok","environment":"production",...}`)
  - `GET /ready` → `200` (`{"status":"ready"}` — xác nhận kết nối thành công tới Redis trên Railway)
  - `POST /ask` không có `X-API-Key` → `401`
  - `POST /ask` có `X-API-Key` hợp lệ → `200`
- **Screenshots:** [screenshots/dashboard.png](screenshots/dashboard.png), [screenshots/running.png](screenshots/running.png), [screenshots/test.png](screenshots/test.png).

### So sánh `railway.toml` với `render.yaml`

| Tiêu chí | `railway.toml` (Railway) | `render.yaml` (Render Blueprint) | Vì sao khác nhau? |
| :--- | :--- | :--- | :--- |
| **Định dạng & phạm vi** | TOML, cấu hình cho **một service** (`[build]`, `[deploy]`). | YAML (Infrastructure as Code), khai báo **nhiều resource cùng lúc** trong `services:` (web service, Redis, database, disk). | Railway quản lý tài nguyên (như Redis add-on, biến môi trường) trực tiếp trên dashboard/CLI theo project, còn Render Blueprint hướng tới đồng bộ toàn bộ hạ tầng từ Git. |
| **Cách khai báo build** | `builder = "DOCKERFILE"` (hoặc `NIXPACKS`) và `dockerfilePath`. | `type: web`, `runtime: docker` (hoặc `python`) kèm `dockerfilePath` / `buildCommand`. | Cả hai đều hỗ trợ Dockerfile nhưng Render gắn thêm cấu hình hạ tầng như `region`, `plan`, `autoDeploy`. |
| **Health check & Restart** | `healthcheckPath = "/health"`, `healthcheckTimeout`, `restartPolicyType = "ON_FAILURE"`, `restartPolicyMaxRetries`. | `healthCheckPath: /health` (nền tảng tự quản lý retry/zero-downtime deploy). | Railway cho chỉnh chi tiết chính sách restart trực tiếp trong file config. |
| **Quản lý Secrets / Env** | Không khai báo env vars trong `railway.toml`; đặt qua `railway variables set` hoặc Dashboard. | Khai báo danh sách `envVars` ngay trong `render.yaml`, dùng `generateValue: true` (tự sinh secret) hoặc `sync: false` (nhập tay trên Dashboard, không ghi đè khi sync lại). | Giúp nhóm phát triển khai báo rõ schema biến môi trường ngay trong repo mà vẫn tránh commit giá trị bí mật. |

### Exercise 3.3: Phân tích CI/CD Pipeline trên GCP Cloud Run (`03-cloud-deployment/production-cloud-run/`)

Đọc `cloudbuild.yaml` và `service.yaml`, pipeline CI/CD tự động chạy qua **4 bước tuần tự** (`waitFor`) khi push code lên nhánh `main`:
1. **`test`**: Chạy container `python:3.11-slim`, cài `requirements.txt` + `pytest` và chạy toàn bộ bộ test (`pytest tests/`); nếu fail thì dừng pipeline ngay.
2. **`build`**: Dùng `gcr.io/cloud-builders/docker` build Docker image tận dụng `--cache-from` từ bản `:latest` và gắn 2 tag (`:$COMMIT_SHA` để truy vết chính xác commit và `:latest`).
3. **`push`**: Đẩy tất cả các tag image vừa build lên Google Container Registry (`gcr.io/$PROJECT_ID/ai-agent`).
4. **`deploy`**: Dùng `gcloud run deploy` triển khai image `:$COMMIT_SHA` lên Cloud Run khu vực `asia-southeast1` với cấu hình tương ứng `service.yaml` (`minScale: 1` tránh cold start, `maxScale: 10`, `containerConcurrency: 80`, giới hạn `1 CPU / 512Mi RAM`, `livenessProbe` ở `/health`, `startupProbe` ở `/ready`, và nạp secret an toàn từ GCP Secret Manager qua `secretKeyRef`).

---

## Part 4: API Security

### Exercise 4.1: API Key Authentication (`04-api-gateway/develop/app.py`)

- **API key được kiểm tra ở đâu?** Trong dependency `verify_api_key` (dòng 39–54) dùng `APIKeyHeader(name="X-API-Key", auto_error=False)`, được gắn vào endpoint `POST /ask` qua `Depends(verify_api_key)` (dòng 70). Các endpoint `/`, `/health` vẫn công khai.
- **Điều gì xảy ra nếu thiếu hoặc sai key?** Thiếu header `X-API-Key` trả `401 Unauthorized`; gửi sai key trả `403 Forbidden`.
- **Cách rotate key an toàn (không downtime):** Hỗ trợ đồng thời nhiều key hợp lệ (`AGENT_API_KEYS=old-key,new-key`) từ biến môi trường → phát key mới cho client chuyển dần → kiểm tra log không còn request dùng key cũ → xoá key cũ khỏi biến môi trường và redeploy/reload.

**Kết quả test thực tế (`AGENT_API_KEY=secret-key-123`):**

```text
--- Không có key (401) ---
HTTP/1.1 401 Unauthorized
content-type: application/json

{"detail":"Missing API key. Include header: X-API-Key: <your-key>"}

--- Sai key (403) ---
HTTP/1.1 403 Forbidden
content-type: application/json

{"detail":"Invalid API key."}

--- Có key đúng (200) ---
HTTP/1.1 200 OK
content-type: application/json

{"question":"Hello","answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận."}
```

### Exercise 4.2 & 4.3: JWT Authentication & Rate Limiting (`04-api-gateway/production/`)

- **Thuật toán rate limiting:** **Sliding Window Log/Counter** trong `rate_limiter.py`: mỗi `user_id` có một `deque` lưu timestamp các request; mỗi lần gọi, xoá toàn bộ timestamp cũ hơn `now - window_seconds` (`60s`), nếu số phần tử còn lại `>= max_requests` thì trả `429 Too Many Requests` kèm header `Retry-After`, `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset`.
- **Giới hạn:** Tài khoản role `user` (`student`) giới hạn **10 requests/phút** (`rate_limiter_user`); role `admin` (`teacher`) giới hạn **100 requests/phút** (`rate_limiter_admin`).
- **Cách phân biệt/bypass cho admin:** Giải mã `role` từ payload JWT trong `verify_token()`, sau đó trong `/ask` chọn bộ limiter theo role (`limiter = rate_limiter_admin if role == "admin" else rate_limiter_user`), hoặc có thể bỏ qua bước kiểm tra hoàn toàn nếu `role == "admin"`.

**Kết quả test thực tế (`POST /auth/token` với `student`/`demo123`, token đã che):**

```text
--- Không có JWT (401) ---
HTTP/1.1 401 Unauthorized
www-authenticate: Bearer
x-content-type-options: nosniff
x-frame-options: DENY
x-xss-protection: 1; mode=block
referrer-policy: strict-origin-when-cross-origin

{"detail":"Authentication required. Include: Authorization: Bearer <token>"}

--- Lấy token thành công ---
Token (masked): eyJhbGciOiJI...BlPN98

--- Gọi /ask với Bearer token (Request #1 -> 200) ---
HTTP/1.1 200 OK
x-content-type-options: nosniff
x-frame-options: DENY

{"question":"Explain JWT","answer":"Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé.","usage":{"requests_remaining":9,"budget_remaining_usd":1.6e-05}}

--- Vòng lặp gọi liên tục (Requests #2..#11) ---
Request #2  -> HTTP/1.1 200 OK
Request #3  -> HTTP/1.1 200 OK
...
Request #10 -> HTTP/1.1 200 OK
Request #11 -> HTTP/1.1 429 Too Many Requests

--- Phản hồi 429 đầy đủ ---
HTTP/1.1 429 Too Many Requests
x-ratelimit-limit: 10
x-ratelimit-remaining: 0
x-ratelimit-reset: 1795597819
retry-after: 59
x-content-type-options: nosniff
x-frame-options: DENY
x-xss-protection: 1; mode=block
referrer-policy: strict-origin-when-cross-origin

{"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":59}}
```

### Exercise 4.4: Cách triển khai Cost Guard với Redis

- **Tại sao cần cả Rate Limit và Cost Guard?** Rate limit kiểm soát **tốc độ gọi** (chống spam/DDoS theo phút), còn Cost Guard kiểm soát **tổng chi phí tiền thực** (theo ngày/tháng) vì 1 request có prompt rất dài hoặc dùng model đắt tiền vẫn có thể tốn nhiều chi phí dù nằm dưới ngưỡng req/phút.
- **Thiết kế lưu trữ trong Redis (stateless, dùng chung giữa nhiều worker/instance):**
  1. Dùng key phân tách theo chu kỳ thời gian: `cost:daily:{YYYY-MM-DD}` (TTL 2 ngày) và `cost:monthly:{YYYY-MM}` (TTL 32 ngày) — hoặc gắn thêm `{user_id}` khi cần ngân sách theo từng user.
  2. **Trước khi gọi LLM (`check_budget`)**: đọc tổng chi phí hiện tại từ Redis (`float(r.get(key) or 0.0)`). Nếu đã vượt hoặc bằng `DAILY_BUDGET_USD` / `MONTHLY_BUDGET_USD` thì chặn ngay bằng **HTTP 402 Payment Required** (không gọi LLM nữa).
  3. **Sau khi gọi LLM (`record_cost`)**: tính chi phí từ số token thực tế (`input_tokens/1000 * PRICE_INPUT + output_tokens/1000 * PRICE_OUTPUT`), cộng nguyên tử vào Redis bằng `INCRBYFLOAT` và đặt `EXPIRE` để tự reset sang chu kỳ mới.

---

## Part 5: Scaling & Reliability

### Exercise 5.1 & 5.2: Health checks (`/health`, `/ready`) và Graceful Shutdown (`05-scaling-reliability/develop/app.py`)

- **Liveness (`/health`) vs Readiness (`/ready`):**
  - `GET /health` (Liveness probe) kiểm tra process còn sống hay không — luôn trả `200` khi process hoạt động (kể cả khi dependency như Redis mất kết nối tạm thời) để tránh platform restart vòng lặp vô ích.
  - `GET /ready` (Readiness probe) kiểm tra instance đã sẵn sàng nhận traffic chưa (đã load xong, không đang shutdown, kết nối Redis/DB thành công). Nếu trả `503`, load balancer ngừng gửi traffic mới tới instance này nhưng không kill container.
- **Kết quả thực tế khi gửi `SIGTERM` lúc đang có request in-flight:**

```text
GET /health -> HTTP/1.1 200 OK
{"status":"ok","uptime_seconds":0.4,"version":"1.0.0","environment":"development","timestamp":"2026-11-25T09:09:20.720662+00:00","checks":{"memory":{"status":"ok","used_percent":13.3}}}

GET /ready -> HTTP/1.1 200 OK
{"ready":true,"in_flight_requests":1}

--- Gửi SIGTERM ngay khi POST /ask?question=Long%20task đang chạy ---
In-flight request vẫn trả: HTTP/1.1 200 OK
{"answer":"Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé."}

--- Log shutdown từ server ---
INFO:     Shutting down
INFO:     127.0.0.1:50502 - "POST /ask?question=Long%20task HTTP/1.1" 200 OK
INFO:     Waiting for application shutdown.
2026-11-25 09:09:23,842 INFO 🔄 Graceful shutdown initiated...
2026-11-25 09:09:23,842 INFO ✅ Shutdown complete
INFO:     Application shutdown complete.
INFO:     Finished server process [526]
```

### Exercise 5.3, 5.4 & 5.5: Stateless Design, Nginx Load Balancing & Test thực tế

- **Tại sao lưu state trong RAM bị hỏng khi scale ngang?** Khi chạy 3 instance sau Nginx load balancer (round-robin), request 1 vào `agent-1` (lưu session trong RAM của `agent-1`), request 2 của cùng user vào `agent-2` sẽ không thấy lịch sử hội thoại. Đẩy toàn bộ session/rate-limit/budget ra **Redis** giúp mọi instance đều stateless và thay thế lẫn nhau được.
- **Chạy thực tế:** `docker compose -p k5-day14-scaling up -d --build --scale agent=3` rồi chạy `python test_stateless.py`:

```text
============================================================
Stateless Scaling Demo
============================================================

Session ID: 2aae3676-06cd-4182-88c6-db48e8068f84

Request 1: [instance-85721b]  Q: What is Docker?
Request 2: [instance-d8d98c]  Q: Why do we need containers?
Request 3: [instance-19c74e]  Q: What is Kubernetes?
Request 4: [instance-85721b]  Q: How does load balancing work?
Request 5: [instance-d8d98c]  Q: What is Redis used for?

------------------------------------------------------------
Total requests: 5
Instances used: {'instance-19c74e', 'instance-85721b', 'instance-d8d98c'}
✅ All requests served despite different instances!

--- Conversation History ---
Total messages: 10
✅ Session history preserved across all instances via Redis!
```

**Giải thích:** 5 request cùng `session_id` được Nginx phân phối đều sang cả 3 container khác nhau (`instance-85721b`, `instance-d8d98c`, `instance-19c74e`), nhưng khi truy vấn `/chat/{session_id}/history` vẫn đủ 10 tin nhắn (5 cặp user–assistant) vì toàn bộ lịch sử được lưu tập trung tại Redis.

---

## Part 6: Final Project (`06-lab-complete/`) — Kết quả `check_production_ready.py`

Chạy kiểm tra đầy đủ (tĩnh + runtime với `uvicorn --workers 2`, Redis, `SIGTERM` + build/chạy/dừng Docker image) trên môi trường Linux/WSL2:

```text
================================================================
  📋 Checklist Deliverable
     ✅ Dockerfile (multi-stage, < 500 MB)
     ✅ docker-compose.yml (agent + redis)
     ✅ .dockerignore
     ✅ Health check endpoint (GET /health)
     ✅ Readiness endpoint (GET /ready)
     ✅ API Key authentication
     ✅ Rate limiting
     ✅ Cost guard
     ✅ Config từ environment variables
     ✅ Structured logging
     ✅ Graceful shutdown
     ✅ Public URL ready (Railway / Render config)
----------------------------------------------------------------
  Result: 12/12 tiêu chí đạt · 44/44 checks passed (gồm --public-url https://agent-production-f69af683.up.railway.app)
  🎉 PASS 12/12 — PRODUCTION READY! Deploy nào!
================================================================
```

Một số thông số đo thực tế từ script chấm:
- **Docker image size:** `297 MB` (< `500 MB`), base `python:3.11-slim`, non-root `appuser`, có `HEALTHCHECK`, `uvicorn` là PID 1 qua `exec`.
- **Rate limiting & Stateless:** Trả `429` sau 5 request thành công (`RATE_LIMIT_PER_MINUTE=5`), sau khi restart agent vẫn trả `429` do state nằm trong Redis sorted set.
- **Readiness:** Khi mất kết nối Redis, `/ready` trả `503` còn `/health` vẫn trả `200`.
- **Cost guard:** Budget `0.000001 USD` trả `402` ngay khi vượt ngân sách.
- **Graceful shutdown:** Nhận `SIGTERM` lúc đang có request in-flight → request vẫn `200`, process thoát `exit code 0`; `docker stop` tắt sạch trong `0.8s` (`exit code 0`).

---

## AI Log

| Hạng mục | Đã hỏi AI gì | Nhận được gì | Tự kiểm tra và điều chỉnh |
| :--- | :--- | :--- | :--- |
| **Part 1–5** | Hỏi cách chạy và kiểm chứng các bài thực hành Part 1, 2, 4, 5 đúng quy ước K5 trên Windows/WSL2. | Hướng dẫn kiểm tra anti-pattern, đo dung lượng Docker image, test JWT/429, SIGTERM và stack stateless 3 replicas. | Tự chạy toàn bộ lệnh thực tế trên máy, đo dung lượng image (`1.67GB` vs `240MB`), xác nhận output `401/403/200/429` và kết quả `test_stateless.py` với 3 instance. |
| **Part 6 (`06-lab-complete/`)** | Hỏi cấu trúc triển khai 12 tiêu chí production (12-Factor config, `APIKeyHeader`, sliding window Redis ZSET, Redis cost guard, `JsonFormatter`, multi-stage Dockerfile, `railway.toml`/`render.yaml`). | Mã nguồn mẫu cho `app/` và cấu hình Docker/Compose/Cloud. | Chạy `check_production_ready.py` trên môi trường POSIX + Docker; kiểm tra từng check tĩnh/runtime/Docker đến khi đạt `PASS 12/12` (43/43 checks), kiểm tra không hardcode secret và không sửa script chấm. |
| **Part 7 (`benchmark-observability/`)** | Hỏi cách thêm metric Histogram `agent_question_length_chars`, bổ sung 2 chủ đề thiếu vào `KNOWLEDGE_BASE`, thiết lập workflow CI eval và quy trình chạy stack Grafana/Jaeger/Prometheus/Locust. | Gợi ý code thêm Histogram, nội dung KB cho Kubernetes HPA & JWT, file `.github/workflows/eval.yml` và lệnh chạy thí nghiệm alert/Locust. | Tự chạy toàn bộ `load_test.py`, `run_eval.py` (đạt `23/23`, 0 regression), `promtool test rules`, Locust headless (`scale_1`, `scale_3`) và đối chiếu 100% số liệu báo cáo với các file JSON/CSV thật. |
