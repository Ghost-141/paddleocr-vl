# Async PaddleOCR-VL API

Authenticated document parsing for one NVIDIA GPU. FastAPI accepts work, SQLite
stores durable page tasks, a fixed GPU layout service produces cropped document
regions, and a separate fixed VLM pool keeps vLLM supplied from that queue.

Only FastAPI is published, on `APP_PORT` (8080 by default). PaddleOCR and
PaddlePaddle are not installed in the API/worker image.

## Run

Requirements: Docker Compose v2, NVIDIA Container Toolkit, and one supported
NVIDIA GPU with room for both PP-DocLayoutV3 and PaddleOCR-VL.

```bash
cp .env.example .env
openssl rand -hex 32  # put this value in PUBLIC_API_KEY
docker compose up --build
```

`layout` runs one GPU-backed PaddleX `PP-DocLayoutV3` model. VLM workers send
cropped regions directly to the shared vLLM server.

The one-shot `model-setup` service only downloads the pinned PP-DocLayoutV3
model. The direct VLM client uses vLLM's OpenAI-compatible endpoint.

## Hardware tuning

Start with the profile closest to the deployment host, then change one value at
a time and compare pages/second, p95 job latency, layout memory, vLLM waiting
requests, and GPU memory. These are starting points, not capacity guarantees.

| Host | Layout service | Layout workers | VLM workers |
|---|---|---:|---:|
| One 24 GB GPU | 1 GPU process | 2 | 4 × 32 |

The main controls are in different files:

| Control | File | Effect |
|---|---|---|
| Layout workers | `.env`: `LAYOUT_WORKER_REPLICAS` | Render pages and feed the layout pool |
| VLM dispatchers | `.env`: `VLM_WORKER_REPLICAS` | Long-lived region consumers feeding vLLM |
| Requests per dispatcher | `.env`: `VLM_DISPATCH_CONCURRENCY` | Bounded concurrent, keep-alive vLLM requests |
| Lease batch size | `.env`: `VLM_CLAIM_BATCH_SIZE` | Regions leased per SQLite write transaction |
| Per-document page depth | `.env`: `MAX_PAGES_PER_JOB` | Bounded number of in-flight pages from one PDF; preserves a durable, fair producer queue |
| Per-page region bound | `.env`: `MAX_REGIONS_PER_PAGE` | Protects disk, queue depth, and latency on dense pages |

Keep one layout service, start with two layout workers plus four VLM dispatchers
at 32 requests each. The layout model and vLLM share the GPU, so use vLLM
memory headroom before raising dispatcher concurrency.

### Tune GPU layout production

GPU layout is fixed at one service to avoid loading another PP-DocLayoutV3
copy onto the GPU. `LAYOUT_WORKER_REPLICAS` is the only layout setting to tune;
it controls how many pages can render and wait to call that service.

| Load-test observation | `LAYOUT_WORKER_REPLICAS` action |
|---|---|
| vLLM `waiting` is near zero and GPU use is low | Raise one step: `2 → 3 → 4`. Retest after each step. |
| vLLM has a sustained waiting queue | Keep it at `2`; layout is already supplying enough work. |
| Layout service errors, higher page latency, or GPU memory pressure | Return to `2`; do not add layout replicas. |

Change the value in `.env` and recreate only the producer pool:

```bash
docker compose up -d --build --force-recreate layout-worker
```

If VLM workers are idle, add layout capacity. If the stored region queue grows
continually, the GPU is full and the fixed pool is correctly applying
backpressure. vLLM batches independent region requests across all documents.

Docker CPU percentages are per core: on a 32-core host, `3200%` is the whole
machine and `100%` is one core.

vLLM limits are in `deploy/vllm_config.yaml`. Start with the profile matching
the GPU arrangement, then change one value and repeat the same load test.

```yaml
gpu-memory-utilization: 0.55
max-num-seqs: 64
max-model-len: 8192
max-num-batched-tokens: 32768
enforce-eager: false
mm-processor-cache-gb: 0
```

### Tune vLLM for available hardware

| Hardware arrangement | GPU memory utilization | Max sequences | Batched tokens | Notes |
|---|---:|---:|---:|---|
| 16 GB GPU shared with GPU layout | `0.40` | `32` | `16384` | Conservative starting point; leave memory for layout. |
| 24 GB GPU shared with GPU layout | `0.55` | `64` | `32768` | Recommended starting point for this deployment. |
| 24 GB GPU, vLLM only | `0.70` | `128` | `49152` | Use only when layout runs on CPU or another GPU. |
| 48 GB+ GPU, vLLM only | `0.75` | `128` | `65536` | Raise further only after measuring throughput and VRAM. |

`gpu-memory-utilization` reserves VRAM for vLLM's weights, activations, and KV
cache. Leave room for the layout model when it shares the GPU. `max-num-seqs`
limits concurrently admitted requests. `max-num-batched-tokens` limits how much
prefill work vLLM packs into one scheduler step. `max-model-len` is a request
ceiling, not a throughput control; keep it at `8192` unless documents require
more context. `mm-processor-cache-gb: 0` is appropriate because OCR regions are
normally unique images.

Use the scheduler gauges and GPU monitoring to choose the next change:

| Observation during a steady load test | Change |
|---|---|
| `waiting` stays above zero; GPU is below 70%; VRAM has headroom | Raise `max-num-batched-tokens` one step: `16384 → 32768 → 49152`. |
| `waiting` stays above zero; GPU is below 70%; batched tokens are already at 49152 | Raise `max-num-seqs` one step: `32 → 64 → 96 → 128`. |
| GPU is below 70%; waiting is near zero | Do not raise vLLM limits; increase layout/region production or incoming load. |
| GPU is above 85%; waiting grows; latency rises | The GPU is saturated; do not add VLM workers. |
| CUDA OOM, layout failures, or little free VRAM | Lower `gpu-memory-utilization` by `0.05`, then lower sequences if needed. |

Set `enforce-eager: false` to allow CUDA graphs. Confirm it took effect after
restart: the vLLM startup log must not say `Cudagraph is disabled under eager
mode`. If it does, the running container is using a different configuration
file or an old container.

After editing the file, recreate vLLM and wait for it to become healthy:

```bash
docker compose up -d --force-recreate paddleocr-vlm-server
docker compose logs --tail=100 paddleocr-vlm-server
```

### Observe vLLM running and waiting requests

From the project directory, print the scheduler gauges:

```bash
docker compose exec -T paddleocr-vlm-server \
  sh -c 'curl -fsS http://localhost:8118/metrics | grep -E "vllm:num_requests_(running|waiting)"'
```

Refresh them once per second during a load test:

```bash
watch -n 1 'docker compose exec -T paddleocr-vlm-server sh -c "curl -fsS http://localhost:8118/metrics | grep -E '\''vllm:num_requests_(running|waiting)'\''"'
```

`running` is work admitted to vLLM; `waiting` is GPU backlog. A sustained
waiting value means the GPU is saturated, while both values near zero means
the layout/region producers are not supplying vLLM.

## API

`/health` is public. Every parsing, job, cancellation, and result endpoint needs:

```text
Authorization: Bearer <PUBLIC_API_KEY>
```

Submit a PDF:

```bash
curl --fail-with-body -X POST \
  'http://localhost:8080/parse/pdf?output_format=both' \
  -H "Authorization: Bearer $OCR_API_KEY" \
  -F file=@document.pdf
```

The `202 Accepted` response contains a status URL and separate JSON/Markdown
result URLs. See [docs/API.md](docs/API.md) for the full contract.

Images remain synchronous:

```bash
curl --fail-with-body -X POST http://localhost:8080/parse/image \
  -H "Authorization: Bearer $OCR_API_KEY" \
  -F file=@page.png
```

## Operations

Start the complete stack in the background:

```bash
docker compose up --build -d
docker compose ps
curl --fail-with-body http://localhost:${APP_PORT:-8080}/health
```

Stop and resume containers without deleting them:

```bash
docker compose stop
docker compose up -d
```

Restart an unchanged service after a transient failure:

```bash
docker compose restart api
```

`restart` does not apply changed environment variables, images, mounted
configuration, or Compose settings; use the `up --force-recreate` commands
below for those changes.

Stop and remove containers and the Compose network while preserving jobs,
models, and caches in named volumes:

```bash
docker compose down
```

Do not add `--volumes` unless all jobs, results, downloaded models, and caches
may be deleted.

Apply changes according to what was edited:

```bash
# Layout service configuration
docker compose up -d --force-recreate layout

# vLLM settings in deploy/vllm_config.yaml
docker compose up -d --force-recreate paddleocr-vlm-server

# API, layout-worker, or vlm-worker Python
docker compose up -d --build api layout-worker vlm-worker

# .env or compose.yaml changes across the stack
docker compose up -d --force-recreate
```

After changing fixed pool values in `.env`, recreate the pools with:

```bash
docker compose up -d --force-recreate layout layout-worker vlm-worker
```

Inspect status and logs:

```bash
docker compose ps
docker compose logs --tail=200 paddleocr-vlm-server
docker compose logs -f api layout layout-worker vlm-worker paddleocr-vlm-server
docker compose top
docker compose events
```

Validate the resolved Compose configuration before restarting:

```bash
docker compose config --quiet
docker compose config
docker compose port api 8080
```

Check API and internal service readiness:

```bash
curl --fail-with-body http://localhost:${APP_PORT:-8080}/health
docker compose exec api python -c \
  "import urllib.request; urllib.request.urlopen('http://layout:8090', timeout=5).close(); print('ready')"
```

Monitor resource pressure during a load test:

```bash
docker stats
nvidia-smi
nvidia-smi dmon -s pucm
```

When a service is unhealthy or exits, start with its first startup error rather
than the final dependency failure:

```bash
docker compose ps --all
docker compose logs --tail=300 model-setup
docker compose logs --tail=300 paddleocr-vlm-server
docker compose logs --tail=300 api layout layout-worker vlm-worker
```

For an interactive restart that keeps the failing service attached to the
terminal:

```bash
docker compose stop layout
docker compose up layout
```

Common failure checks:

| Symptom | First check |
|---|---|
| `dependency ... is unhealthy` | Read the dependency's earlier logs; the dependency message is usually only the final symptom |
| API is healthy but unreachable remotely | Run `docker compose port api 8080`, use the host IP and published port, then check the host firewall |
| API cannot reach layout | Run the internal readiness command above from the API container |
| Model setup repeatedly downloads | Check the `models` volume, `HF_TOKEN`, free disk space, and `model-setup` logs |
| Image pull or Python package download times out | Check host DNS, proxy, registry/PyPI access, and retry; host networking does not fix a missing package version |

The queue accepts 20 active PDF jobs by default. Page leases recover work after
worker crashes, transient backend failures receive three bounded retries, and
terminal jobs are removed after 24 hours. Data lives in the local `app-data`
volume; do not place the SQLite database on NFS.

The region queue is durable in SQLite, so queued regions resume after either
fixed worker pool restarts.

## Development

```bash
uv sync
uv run pytest -q
docker compose config --quiet
```
