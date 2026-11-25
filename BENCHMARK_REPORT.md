# Benchmark & Observability Report — Day 14

**Họ tên:** Lý Thành Lâm (MSSV: 2A202603475)  
**Ngày chạy:** 2026-11-25  
**Môi trường:** Windows 11 + WSL2 Ubuntu / Linux Docker `29.10.0` + Docker Compose `v5.8.0` (Python `3.12.3`)

---

## 1. SLO của agent

| SLI | SLO | Lý do chọn ngưỡng này |
| :--- | :--- | :--- |
| p95 latency `/ask` | `< 500 ms` | Với mock LLM nền `120–180 ms` và tỉ lệ tail latency mặc định `3%` (`< 5%`), 95% request bình thường hoàn thành quanh `200–250 ms`. Ngưỡng `500 ms` vừa đảm bảo trải nghiệm mượt vừa cho phép phát hiện sớm khi tỉ lệ request chậm vượt `5%` hoặc hệ thống bão hoà kết nối. |
| Error rate `/ask` | `< 2.0%` | Upstream mock LLM có xác suất lỗi ngẫu nhiên `1%` (`MOCK_ERROR_RATE=0.01`). Đặt SLO lỗi `< 2.0%` tạo error budget hợp lý cho dao động tự nhiên, nhưng vẫn fail ngay khi lỗi upstream hoặc lỗi kết nối tăng bất thường. |
| Accuracy trên golden dataset | `≥ 80%` (mục tiêu `100%`, 0 regression) | Đảm bảo agent v2 trả lời đúng kiến thức cốt lõi trước khi deploy; mọi thay đổi làm giảm accuracy dưới ngưỡng hoặc gây regression trên câu cũ phải bị chặn ở CI. |

---

## 2. Benchmark hiệu năng (develop, `load_test.py`)

### 2.1 Concurrency vs latency (agent v2)

Số liệu khớp trực tiếp với `reports/load_v2_c1.json`, `load_v2_c10.json`, `load_v2_c50.json`, `load_v2_c100.json` (`--requests 300`):

| Concurrency | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Error rate | SLO |
| ---: | ---: | ---: | ---: | ---: | ---: | :---: |
| 1 | 3.90 | 195.0 | 225.6 | 1708.8 | 2.00% (`6×503`) | ✅ PASS |
| 10 | 37.06 | 189.9 | 223.0 | 1693.6 | 0.67% (`2×503`) | ✅ PASS |
| 50 | 115.95 | 202.6 | 245.2 | 1699.3 | 21.67% (`62×ConnectError, 3×503`) | ❌ FAIL |
| 100 | 157.13 | 292.9 | 1598.6 | 1758.5 | 79.00% (`236×ConnectError, 1×503`) | ❌ FAIL |

**Nhận xét:** RPS **không tăng tuyến tính** khi đẩy concurrency lên cao:
- Từ `c=1` (`3.90 req/s`) lên `c=10` (`37.06 req/s`), RPS tăng gần tuyến tính (~9.5×) và p50/p95 giữ ổn định (`~190 ms / ~223 ms`) vì tác vụ là async I/O-bound (`asyncio.sleep` mô phỏng gọi retrieval + LLM), 1 process `uvicorn` xử lý tốt 10 luồng song song.
- Từ `c=50` (`115.95 req/s`) lên `c=100` (`157.13 req/s`), tốc độ tăng RPS chậm lại rõ rệt và hệ thống **bão hoà kết nối ở một process đơn**: `ConnectError` tăng vọt lên `21.67%` ở `c=50` và `79.00%` ở `c=100`, đồng thời p50 tăng lên `292.9 ms` và p95 vọt lên `1598.6 ms` (vi phạm cả hai SLO). Muốn chịu tải lớn hơn phải scale nhiều instance sau load balancer.

### 2.2 Tail latency

Số liệu khớp trực tiếp với `reports/load_v2_slow_0.json`, `load_v2_slow_0.03.json`, `load_v2_slow_0.1.json` (`--requests 300 --concurrency 20`):

| `MOCK_SLOW_RATE` | avg (ms) | p95 (ms) | p99 (ms) |
| :--- | ---: | ---: | ---: |
| `0` | 193.6 | 221.6 | 226.3 |
| `0.03` (mặc định) | 239.8 | 221.8 | 1700.1 |
| `0.1` | 355.5 | 1692.3 | 1714.8 |

**Nhận xét:**
- **p99 và p95 nhạy nhất** với request chậm:
  - Khi `MOCK_SLOW_RATE` tăng từ `0` lên `0.03` (3% request bị cộng thêm `1500 ms`), `avg` chỉ tăng nhẹ `+46.2 ms` (`193.6 → 239.8 ms`) và `p95` gần như không đổi (`221.8 ms`), nhưng **`p99` nhảy vọt gấp ~7.5 lần** từ `226.3 ms` lên **`1700.1 ms`**.
  - Khi `MOCK_SLOW_RATE = 0.1` (10% request chậm > ngưỡng 5%), **`p95` lập tức vọt lên `1692.3 ms`** (gấp ~7.6 lần), trong khi `avg` mới ở mức `355.5 ms`.
- **Vì sao SLO không nên đặt theo average?** Giá trị trung bình bị làm loãng bởi 90–97% request nhanh nên **che giấu nhóm người dùng ở đuôi phân phối (tail latency)** phải chờ gần 2 giây. Đặt SLO theo `p95` hoặc `p99` phản ánh trung thực trải nghiệm tệ nhất mà phần đông/nhóm nhạy cảm của người dùng gặp phải.

---

## 3. Benchmark chất lượng (develop, `eval/run_eval.py`)

Số liệu khớp trực tiếp với `reports/eval_v1.json`, `reports/eval_v2.json`, `reports/eval_v2_fixed.json`:

| Chỉ số | Agent v1 | Agent v2 | Agent v2 (sau khi sửa KB) |
| :--- | :---: | :---: | :---: |
| Accuracy | 4.3% (`1/23`) | 91.3% (`21/23`) | **100.0% (`23/23`)** |
| Avg tokens / câu | 57.3 | 108.8 | 113.8 |
| Tổng cost (USD) | `$0.000408` | `$0.000758` | `$0.000792` |
| Cost / câu đúng (USD) | `$0.00040755` | `$0.00003607` | **`$0.00003443`** |
| Quality gate | ❌ FAIL | ✅ PASS | ✅ PASS (0 regression) |

**Những câu v2 trả lời sai ban đầu và cách sửa** (trong `06-lab-complete/benchmark-observability/develop/utils/mock_llm.py` và đồng bộ sang `production/utils/mock_llm.py`):

| ID | Keyword bị thiếu | Đã sửa gì |
| :--- | :--- | :--- |
| `security-02` | `token`, `hết hạn`, `chữ ký` | Thêm entry vào `KNOWLEDGE_BASE` với từ khoá `["jwt"]` giải thích sự khác nhau giữa API key cố định và JWT (token có chữ ký số, chứa thông tin user và thời điểm hết hạn, xác minh không cần tra DB). |
| `scaling-03` | `cpu`, `memory`, `custom metrics` | Thêm entry vào `KNOWLEDGE_BASE` với từ khoá `["hpa", "kubernetes", "autoscal"]` mô tả Kubernetes HPA scale số pod dựa trên CPU, memory hoặc custom metrics (RPS, độ dài hàng đợi). |

**Nhận xét trade-off chất lượng / chi phí / latency giữa v1 và v2:**
- `v2` bổ sung bước retrieval (RAG) nên prompt dài hơn (`avg_tokens` tăng ~2× từ `57.3 → 113.8`), tổng chi phí tăng gần gấp đôi (`$0.000408 → $0.000792`) và latency p50 tăng thêm `~20–27 ms` (`167.7 → 194.3 ms`) do bước tìm kiếm tài liệu.
- Tuy nhiên, độ chính xác tăng vọt từ `4.3%` lên `100.0%` (`+95.7 điểm %`), khiến **chi phí trên mỗi câu trả lời đúng (`cost / câu đúng`) giảm gần 12 lần** (`$0.00040755 → $0.00003443`). Vì vậy đánh giá bằng `cost / câu đúng` phản ánh đúng hiệu quả đầu tư của RAG hơn là chỉ nhìn tổng chi phí.

**Quality gate trong CI (Exercise 7.3):**
- Đã cấu hình workflow tại [.github/workflows/eval.yml](.github/workflows/eval.yml) chạy trên mỗi `pull_request`.
- Cơ chế chặn merge: `eval/run_eval.py` kiểm tra 2 điều kiện `accuracy >= --min-accuracy` và không có câu nào bị regression so với `--baseline`. Nếu vi phạm, script kết thúc với **exit code `1`** (đã kiểm chứng thực tế khi chạy `eval` cho `v1` với `--baseline reports/eval_v2_fixed.json` → báo `22` câu regression và trả `exit code 1`), làm GitHub Actions job fail và chặn merge PR.

---

## 4. Observability stack (production)

### 4.1 Screenshot & trả lời Exercise 7.1 / 7.4

- [x] Dashboard Grafana khi đang có tải (thấy rõ 4 hàng: Golden Signals, Latency & Traffic, LLM, Instances): [screenshots/grafana-dashboard.png](screenshots/grafana-dashboard.png)
- [x] Một trace chậm trong Jaeger (thấy span chiếm thời gian và `gen_ai.*` attributes): [screenshots/jaeger-slow-trace.png](screenshots/jaeger-slow-trace.png)
- [x] Một trace lỗi trong Jaeger (có `error=true` và event `exception` mở rộng): [screenshots/jaeger-error-trace.png](screenshots/jaeger-error-trace.png)
- [x] Trang Alerts của Prometheus với **4/4 alert đang firing** cùng lúc: [screenshots/prometheus-alert-firing.png](screenshots/prometheus-alert-firing.png)

**Trả lời Exercise 7.1 (Metrics local):**
- Ví dụ 3 loại metric trong `/metrics`:
  - **Counter:** `http_requests_total{method="POST",route="/ask",status="200"}` (chỉ tăng).
  - **Gauge:** `agent_in_flight_requests` hoặc `agent_info{model="mock-llm-small",version="v2"}` (lên/xuống theo trạng thái).
  - **Histogram:** `http_request_duration_seconds_bucket` và metric tự thêm `agent_question_length_chars_bucket` trong `develop/app.py`.
- **Tại sao dùng `route.path` thay vì `request.url.path`?** Nếu gắn URL thực làm label khi bot quét hàng nghìn đường dẫn rác (`/wp-admin`, `/.env`, `/a1b2c3`...), mỗi URL sinh ra một time series mới làm **bùng nổ cardinality**, khiến Prometheus cạn RAM và chậm truy vấn. Gom về `route.path` (và `"unmatched"` cho URL không khớp) giữ số series nhỏ và cố định.

**Trả lời Exercise 7.4 (Observability stack với 30 users):**
1. **p95 và avg:** Đo thực tế từ Prometheus khi đang tải (`30 users`, 2 replicas): `avg = 226.2 ms`, `p95 = 292.2 ms`, `p99 = 1793.4 ms`. Khoảng cách nhỏ giữa `avg` và `p95` cho thấy 95% request ổn định, còn khoảng cách lớn tới `p99` (`~1.8s`) chứng tỏ tồn tại tail latency ở ~3% request chậm.
2. **Nginx có chia đều traffic cho 2 instance không?** Có — Prometheus ghi nhận `172.18.0.3:8000 = 3.81 req/s` và `172.18.0.2:8000 = 3.74 req/s` (gần như 50/50 nhờ cơ chế round-robin của Nginx).
3. **Vì sao `input tokens/s` lớn hơn `output tokens/s`?** Đo thực tế `input = 577.4 tok/s` vs `output = 300.9 tok/s` (~1.9×) vì agent `v2` (RAG) ghép `SYSTEM_PROMPT` + tài liệu truy xuất từ `KNOWLEDGE_BASE` + câu hỏi người dùng vào input prompt trước khi gửi LLM, trong khi câu trả lời output ngắn gọn hơn.
4. **`curl -i http://localhost:8080/metrics` trả về gì? Vì sao?** Trả về **`HTTP/1.1 404 Not Found`** (cấu hình `location = /metrics { return 404; }` trong `nginx/nginx.conf`). Endpoint `/metrics` chỉ phục vụ Prometheus scrape trong mạng Docker nội bộ (`obs_net`), không được public ra ngoài để tránh lộ thông tin nội bộ hệ thống (route, lưu lượng, chi phí, phiên bản).

### 4.2 Thí nghiệm "phá hệ thống" (Chaos & Alerts)

Đã chạy unit test alert rules trước khi thử nghiệm:
`promtool test rules /p/alert_rules_test.yml` → **`SUCCESS`**.

Kết quả kích hoạt thực tế (giữ Locust `30 users` chạy liên tục):

| # | Thay đổi | Alert nào firing | Thời gian từ lúc đổi → firing | Panel nào phản ánh rõ nhất |
| :--- | :--- | :--- | :--- | :--- |
| A | `MOCK_ERROR_RATE=0.2` | `AgentHighErrorRate` (`for: 1m`, giá trị đo `18.98% > 5%`) | **75 giây** | Golden Signals — **Error rate** (chuyển đỏ) & LLM calls error |
| B | `MOCK_SLOW_RATE=0.3` | `AgentHighLatencyP95` (`for: 2m`, giá trị đo `1.93s > 1s`) | **135 giây** | Golden Signals — **p95 latency** & Latency `/ask` |
| C | `LLM_MODEL=mock-llm-large` | `LLMCostBurnRateHigh` (`for: 2m`, giá trị đo `$11.46/giờ > $2/giờ`) | **~145 giây** | LLM — **Cost USD/giờ** & LLM latency p95 |
| D | `docker pause` `agent-2` | `AgentInstanceDown` (`for: 30s`, `up{instance="172.18.0.3:8000"} == 0`) | **47 giây** | Golden Signals — **Instances up** (giảm 2 → 1) & Requests/s theo instance |
| E | `AGENT_VERSION=v1` | **Không có alert nào firing** | Không firing | LLM — **Retrieval hit ratio** mất dữ liệu, **Tokens/s** giảm, bảng **Version** đổi sang `v1` |

- **Thí nghiệm E không làm alert nào firing. Phát hiện loại sự cố này trong production bằng cách nào?**  
  Metric hạ tầng (HTTP 200, latency, CPU, error rate) đều hoàn toàn xanh dù chất lượng câu trả lời tụt từ `100%` xuống `4.3%`. Để phát hiện trong production cần kết hợp:
  1. **Eval quality gate trong CI/CD** (chạy `run_eval.py` trên golden dataset trước mọi lần deploy, chặn merge khi có regression).
  2. **Giám sát metric chất lượng/nghiệp vụ**: theo dõi `agent_retrieval_total{result="hit"}` (cảnh báo nếu retrieval hit ratio tụt đột ngột hoặc bằng 0), độ dài/phân bố token bất thường.
  3. **Online evaluation & phản hồi người dùng**: lấy mẫu traffic thật chấm bằng LLM-as-judge định kỳ (shadow/canary eval) và theo dõi tỉ lệ thumbs-down / retry của user.
- **Lưu ý ở thí nghiệm D (`docker pause` & lỗi 504):**
  - Dùng `docker pause` giữ container trong Docker DNS nên Prometheus vẫn scrape và thấy `up == 0` để bắn `AgentInstanceDown` (còn `docker stop` xoá IP khỏi DNS nên target biến mất khỏi service discovery).
  - Các lỗi `504 Gateway Timeout` phát sinh ở tầng Nginx (quá `proxy_read_timeout 10s`) **không xuất hiện trên metric error rate của agent** vì request bị kẹt chưa bao giờ trả response từ FastAPI. Trong production cần giám sát thêm metric từ tầng Load Balancer / Ingress hoặc synthetic probe từ bên ngoài.

### 4.3 Debug bằng trace

Chọn 1 trace chậm nhất thu được trong Jaeger ([screenshots/jaeger-slow-trace.png](screenshots/jaeger-slow-trace.png)):

- **`trace_id`:** `1fbd433d21c715269f4aa99cbd4db969`
- **Tổng thời gian:** `1717.93 ms` (`POST /ask`)
  - `agent.run`: `1714.45 ms`
  - `agent.retrieve_context`: `23.03 ms` (`1.3%`)
  - `chat mock-llm-small`: **`1691.20 ms` (`98.4%`)**
- **Span chiếm nhiều thời gian nhất:** `chat mock-llm-small` (`1691.20 ms`, chiếm `98.4%` tổng thời gian request) — chứng tỏ độ trễ đến từ lời gọi LLM upstream chứ không phải code retrieval hay FastAPI.
- **Dòng log JSON tương ứng (grep theo `trace_id` từ log container `agent-2`):**

```json
{"ts": "2026-11-25T09:35:44.822430+00:00", "level": "INFO", "service": "observable-agent", "instance": "d2420a9b769d", "event": "llm_call", "trace_id": "1fbd433d21c715269f4aa99cbd4db969", "span_id": "ba897b155b7c627e", "request_id": "dee630a30839", "model": "mock-llm-small", "agent_version": "v2", "input_tokens": 74, "output_tokens": 37, "cost_usd": 3.3e-05, "llm_ms": 1689.9}
{"ts": "2026-11-25T09:35:44.823334+00:00", "level": "INFO", "service": "observable-agent", "instance": "d2420a9b769d", "event": "http_request", "trace_id": "1fbd433d21c715269f4aa99cbd4db969", "span_id": "ba897b155b7c627e", "request_id": "dee630a30839", "method": "POST", "route": "/ask", "status": 200, "ms": 1717.1}
```

- **Trace lỗi đối chiếu** ([screenshots/jaeger-error-trace.png](screenshots/jaeger-error-trace.png), `trace_id = 4d7f7189f78a9833ca80761a5fe2fdc5`): span `chat mock-llm-small` (`96.9 ms`) ghi nhận tag `error=true`, `error.type=upstream_unavailable` và event `exception` với `exception.message = Upstream LLM error: 503 Service Unavailable (mock)`, khớp dòng log:

```json
{"ts": "2026-11-25T09:35:29.458449+00:00", "level": "INFO", "service": "observable-agent", "instance": "d2420a9b769d", "event": "llm_error", "trace_id": "4d7f7189f78a9833ca80761a5fe2fdc5", "span_id": "37bd3889bd855a29", "request_id": "0f376ce453c5", "error": "Upstream LLM error: 503 Service Unavailable (mock)"}
```

---

## 5. Benchmark scaling (production, Locust headless, 100 users, 2 phút)

Số liệu khớp trực tiếp với `benchmark-results/scale_1_stats.csv` và `benchmark-results/scale_3_stats.csv`:

| Số instance | Scope | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Failures |
| :---: | :--- | ---: | ---: | ---: | ---: | :---: |
| **1** | `POST /ask` | 64.56 | 190 | 230 | 1700 | 81 / 7,104 (`1.14%`) |
| **1** | `Aggregated` | 71.14 | 190 | 230 | 1700 | 81 / 7,828 (`1.03%`) |
| **3** | `POST /ask` | 64.86 | 190 | 220 | 1700 | 76 / 7,109 (`1.07%`) |
| **3** | `Aggregated` | 71.63 | 190 | 220 | 1700 | 76 / 7,852 (`0.97%`) |

**Giải thích kết quả:**
- Scale từ `1` lên `3` instance chỉ cải thiện nhẹ p95 (`230 ms → 220 ms`) và giữ RPS gần như không đổi (`71.14 → 71.63 req/s`), còn p50 (`190 ms`) và p99 (`1700 ms`) hoàn toàn giống nhau.
- **Nút thắt nằm ở đâu?** Nút thắt **không nằm ở CPU của FastAPI agent** (1 instance async đã thừa sức phục vụ ~71 req/s với 100 virtual users có `wait_time = 0.5–2s`), mà nằm ở **độ trễ I/O từ phía LLM upstream** (`120–180 ms` + 3% slow calls `~1.7s` — như đã thấy trên Jaeger span `chat mock-llm-small` chiếm 98.4% thời gian) và giới hạn tốc độ sinh tải của 100 user giả lập.
- Dù p95 không giảm mạnh ở mức tải này, chạy 3 instance vẫn mang lại lợi ích sống còn về **High Availability** (chịu lỗi khi 1 container chết/pause mà không sập dịch vụ) và chuẩn bị sẵn năng lực khi traffic thật tăng cao hơn ngưỡng CPU/socket của 1 instance.

---

## 6. Kết luận

- **3 điều học được về benchmark & observability:**
  1. **Không bao giờ đánh giá hiệu năng chỉ bằng average latency:** tail latency (`p95`/`p99`) mới bộc lộ rõ nhóm người dùng bị chờ lâu, và SLO phải định nghĩa theo percentile kết hợp error rate.
  2. **Ba trụ cột Metrics – Traces – Logs phải liên kết chặt qua `trace_id`:** Metrics (Grafana/Prometheus) báo *có sự cố*, Traces (Jaeger) chỉ ra chính xác *bước nào chậm/lỗi*, và JSON logs kèm `trace_id` cho *ngữ cảnh chi tiết*.
  3. **Observability hạ tầng không thay thế được Benchmark chất lượng (Eval):** khi đổi về `v1`, toàn bộ dashboard và alert hạ tầng vẫn xanh trong khi độ chính xác sụp từ `100%` về `4.3%`; bắt buộc có golden dataset + quality gate trong CI.
- **Nếu đưa agent này lên production thật, cần thêm các metric / alert:**
  1. **Load balancer / Ingress metrics** (`nginx` 4xx/5xx/504, upstream timeouts) và **synthetic blackbox probe** từ bên ngoài để bắt lỗi timeout/DNS mà metric nội bộ agent không thấy.
  2. **Metric cho lớp bảo vệ & hạ tầng phụ trợ:** số lần bị chặn `401` (brute-force), `429` (rate limit), `402` (vượt budget), độ trễ & tỉ lệ lỗi Redis, và alert cho **retrieval miss ratio tăng cao** / **online eval score tụt**.
  3. **LLM streaming & chất lượng:** TTFT (*Time To First Token*), tokens/second theo model, tỉ lệ prompt bị cắt ngắn (truncation), và Alertmanager kết nối Slack/PagerDuty kèm chính sách `for` chống alert fatigue.
