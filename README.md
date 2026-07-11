# PaddleOCR-VL API

<p align="left">
  <a href="https://github.com/PaddlePaddle/PaddleOCR">
    <img alt="PaddleOCR-VL" src="https://img.shields.io/badge/PaddleOCR--VL-1.6-0052CC?style=flat-square" />
  </a>
  <a href="https://docs.vllm.ai/">
    <img alt="vLLM" src="https://img.shields.io/badge/vLLM-Inference_Backend-4B32C3?style=flat-square" />
  </a>
  <a href="https://fastapi.tiangolo.com/">
    <img alt="FastAPI" src="https://img.shields.io/badge/FastAPI-API-009688?style=flat-square&amp;logo=fastapi&amp;logoColor=white" />
  </a>
  <a href="https://www.docker.com/">
    <img alt="Docker Compose" src="https://img.shields.io/badge/Docker-Compose-2496ED?style=flat-square&amp;logo=docker&amp;logoColor=white" />
  </a>
  <a href="https://developer.nvidia.com/cuda-toolkit">
    <img alt="NVIDIA CUDA 13.x" src="https://img.shields.io/badge/NVIDIA-CUDA_13.x-76B900?style=flat-square&amp;logo=nvidia&amp;logoColor=white" />
  </a>
  <a href="https://www.python.org/">
    <img alt="Python 3.10 to 3.13" src="https://img.shields.io/badge/Python-3.10--3.13-3776AB?style=flat-square&amp;logo=python&amp;logoColor=white" />
  </a>
</p>

![Architecture](docs/system.png)

This repository turns PaddleOCR-VL into a self-hosted, GPU-accelerated document-processing API. It processes images and multi-page PDFs through authenticated FastAPI endpoints and returns structured JSON, clean Markdown, or both while preserving headings, paragraphs, lists, formulas, and tables.

Designed for private OCR, RAG ingestion, search indexing, and knowledge-base creation, the system includes validation, configurable limits, automated model setup, authentication, health checks, file cleanup, and lightweight tests.

Docker Compose manages two services: a PaddleOCR vLLM inference server and a FastAPI processing layer. Both can share a single GPU, or layout analysis can run on CPU while vLLM uses the GPU, allowing flexible resource allocation.

See the [API reference](docs/API.md) for authentication, exact parameters,
response formats, examples, limits, and error codes.


## Requirements

- Linux with an NVIDIA GPU of compute capability 8.0 or newer
- NVIDIA driver capable of CUDA 13.x
- Docker Engine 19.03 or newer
- Docker Compose v2 (`docker compose`)
- NVIDIA Container Toolkit
- Internet access for the first image and model download


## Verify The Host

Confirm that the driver can see the GPU:

```bash
nvidia-smi
```

Confirm that Docker can expose it to a CUDA 13 container:

```bash
docker run --rm --gpus all \
  nvidia/cuda:13.0.0-base-ubuntu24.04 nvidia-smi
```

Resolve Docker or NVIDIA Container Toolkit errors before starting this stack.

## Configure

Create the local environment file:

```bash
cp .env.example .env
```

Generate a public API key and place it in `.env`:

```bash
openssl rand -hex 32
```

At minimum, review these runtime values in `.env`:

```dotenv
PUBLIC_API_KEY=replace-with-a-generated-secret
APP_PORT=8080
GPU_DEVICE_ID=0
DEVICE=gpu:0
MAX_FILE_SIZE_MB=100
MAX_PAGES=100
```

Important settings:

| Variable | Default | Purpose |
| --- | --- | --- |
| `PUBLIC_API_KEY` | Required | Bearer token accepted by parsing endpoints |
| `APP_PORT` | `8080` | Port exposed on the host |
| `GPU_DEVICE_ID` | `0` | NVIDIA GPU assigned to both containers |
| `DEVICE` | `gpu:0` | PaddleOCR pipeline device (`gpu:0` or `cpu`) |
| `MAX_FILE_SIZE_MB` | `100` | Maximum accepted upload size in MiB |
| `MAX_PAGES` | `100` | Maximum number of PDF page results returned per request |
| `API_BASE_IMAGE` | Official offline image | PaddleOCR API base image with bundled models |
| `VLLM_IMAGE` | Official offline image | PaddleOCR vLLM image with bundled model |
| `HF_TOKEN` | Empty | Optional Hugging Face token for faster model downloads |

### Note 
`GPU_DEVICE_ID` selects
the physical NVIDIA GPU exposed to the containers. `DEVICE` tells the API
where to run the PaddleOCR pipeline and accepts values such as `gpu:0` or
`cpu`. 

`MAX_FILE_SIZE_MB` is checked while an upload is written and requests over the
limit receive HTTP 413. `MAX_PAGES` limits the number of page results included
in the API response and assembled Markdown. 

Set `DEVICE=cpu` to run the PaddleOCR pipeline, including layout detection, on
CPU while keeping the vLLM service on the selected NVIDIA GPU. 

After changing `DEVICE`, `MAX_FILE_SIZE_MB`, or `MAX_PAGES`, apply the new
environment values without rebuilding the image:

```bash
docker compose up -d --force-recreate api
```

## Deploy

Pull the official service image, build the API, and start both services:

```bash
docker compose pull
docker compose build
docker compose up -d
```

Step by step:

1. Copy `.env.example` to `.env`, fill in `PUBLIC_API_KEY`, and review
   `DEVICE`, `MAX_FILE_SIZE_MB`, and `MAX_PAGES`.
2. Verify the host GPU with `nvidia-smi`.
3. Pull the official images with `docker compose pull`.
4. Build the API image with `docker compose build`.
5. Start the stack with `docker compose up -d`.
6. Check `docker compose ps` and `docker compose logs -f` until both services are healthy.
7. Test `http://localhost:${APP_PORT}/health`.

The `model-setup` service downloads the pinned `PP-DocLayoutV2` model to `./models/PP-DocLayoutV2` before the API starts. The API mounts it read-only, so keep the `models` directory between rebuilds. Downloads support retries and resume; set `HF_TOKEN` in `.env` for authenticated Hugging Face access.


Verify the packaged model before starting the API:

```bash
du -sh models/PP-DocLayoutV2
test -f models/PP-DocLayoutV2/inference.pdiparams
```

Model weights are bundled in those images, so startup does not depend on a
separate Paddle model-host download.
Watch initialization:

```bash
docker compose logs -f
```

Check container state:

```bash
docker compose ps
```

The API is ready when `api` reports healthy. Test it from the server:

```bash
curl http://localhost:8080/health
```

Interactive API documentation is available at:

```text
http://localhost:8080/docs
```

## Debugging

Use these commands when startup stalls or a request fails:

```bash
nvidia-smi
docker compose ps
docker compose logs -f paddleocr-vlm-server
docker compose logs -f api
curl --fail-with-body http://localhost:8080/health
docker compose exec api curl -fsS http://paddleocr-vlm-server:8118/health
```

Inspect the container health check directly:

```bash
docker inspect --format '{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{end}}' \
  "$(docker compose ps -q paddleocr-vlm-server)"
docker inspect --format '{{range .State.Health.Log}}exit={{.ExitCode}} {{.Output}}{{println}}{{end}}' \
  "$(docker compose ps -q paddleocr-vlm-server)"
```

Remove stale containers from older Compose runs:

```bash
docker compose down --remove-orphans
docker ps -a | grep paddleocr
docker rm -f <container_name_or_id>
```

## Connect

Set the connection details in the client shell. Replace the host with the
server DNS name or IP when connecting remotely:

```bash
export OCR_API_URL=http://localhost:8080
export OCR_API_KEY='the-value-from-PUBLIC_API_KEY'
```

Only `/health` is public. Parsing endpoints require this header:

```text
Authorization: Bearer <PUBLIC_API_KEY>
```

For remote access, allow `APP_PORT` through the host firewall or place the API
behind an HTTPS reverse proxy. Do not expose an unencrypted public HTTP endpoint
because the bearer token and uploaded documents would travel in plaintext.

## Operate

Useful lifecycle commands:

```bash
docker compose restart
docker compose logs -f api
docker compose logs -f paddleocr-vlm-server
docker compose down
```

`docker compose down` keeps the named model and application volumes. To remove
those volumes as well, use `docker compose down --volumes`; subsequent startup
will download models again.

## Local Development

Install the locked Python environment:

```bash
uv sync
```

The local API expects the same internal Compose defaults as production. If you
want host-based development, change `paddlocr_vl/core/config.py` first so the
API points at a reachable vLLM server.

Run tests without model initialization:

```bash
uv run pytest -q
```

The production API uses one worker because `PaddleOCRVLService` holds a
GPU-resident pipeline and serializes inference calls. Do not increase Uvicorn
workers without accounting for duplicated GPU model memory.

## Troubleshooting

**Container cannot access the GPU**

Run the CUDA container check from `Verify The Host`. Confirm Docker is
configured with NVIDIA Container Toolkit and restart Docker after changing its
runtime configuration.

**vLLM remains unhealthy during first startup**

The offline vLLM image still needs time to initialize the model on GPU. Check
`docker compose logs -f paddleocr-vlm-server`. The health check allows a
10-minute startup period. If the API reports a missing layout model directory,
run `docker compose logs -f model-setup` and confirm the model download
completed successfully before starting it.

**CUDA out of memory**

Stop other GPU processes, verify the selected `GPU_DEVICE_ID`, and lower
`gpu-memory-utilization` or `max-num-seqs` in `deploy/vllm_config.yaml`.

**HTTP 401**

The bearer value does not match `PUBLIC_API_KEY`. After changing `.env`, recreate
the API container with `docker compose up -d --force-recreate api`.

**HTTP 413**

The upload exceeds `MAX_FILE_SIZE_MB`. Increase the setting deliberately and
recreate the API container with `docker compose up -d --force-recreate api`.

**HTTP 415**

The file extension or content type is unsupported, or the file was sent to the
wrong image/PDF endpoint.
