# PaddleOCR-VL API Reference

Production contract for API version `2.0.0`.

## Conventions

| Item | Value |
|---|---|
| Default base URL | `http://localhost:8080` |
| Request encoding | JSON unless an endpoint specifies `multipart/form-data` |
| Response encoding | JSON unless a result endpoint specifies otherwise |
| Authentication | `Authorization: Bearer <PUBLIC_API_KEY>` |
| Job identifier | 32-character lowercase UUID hex string |
| Timestamp format | Unix time in seconds, represented as a JSON number |

`status_url` and `result_urls` are relative paths. Resolve them against the same
base URL used to submit the job.

The API does not implement an idempotency key. Every successful PDF submission
creates a new job, even when the file and request parameters are identical.

FastAPI also exposes generated API discovery documents:

- Swagger UI: `/docs`
- ReDoc: `/redoc`
- OpenAPI schema: `/openapi.json`

## Authentication and ownership

Every endpoint except `GET /health` requires a bearer token:

```http
Authorization: Bearer your-api-key
```

Jobs are scoped to a SHA-256 identity derived from the bearer token. A request
using a different token receives `404 Job not found`, even when the job ID
exists. The default deployment has one `PUBLIC_API_KEY`, so it is a shared
on-premises credential rather than per-employee identity.

Missing or invalid credentials return `401`:

```json
{
  "detail": "Invalid public API key"
}
```

An invalid-token response includes:

```http
WWW-Authenticate: Bearer
```

## Endpoint summary

| Method | Path | Authentication | Success | Purpose |
|---|---|---|---:|---|
| `GET` | `/health` | No | `200` | Gateway liveness |
| `POST` | `/parse/image` | Bearer | `200` | Parse one image synchronously |
| `POST` | `/parse/pdf` | Bearer | `202` | Validate and queue a PDF |
| `GET` | `/jobs/{job_id}` | Bearer | `200` | Read job status and progress |
| `GET` | `/jobs/{job_id}/result/{artifact}` | Bearer | `200` | Download a completed artifact |
| `DELETE` | `/jobs/{job_id}` | Bearer | `202` | Request cancellation |

---

## `GET /health`

Reports that the FastAPI gateway started successfully and shows its configured
internal vLLM URL.

This endpoint does **not** probe vLLM. Use it as gateway liveness, not
end-to-end backend readiness.

### Request

No parameters or authentication.

```bash
curl --fail-with-body http://localhost:8080/health
```

### `200 OK`

```json
{
  "status": "healthy",
  "vllm_url": "http://paddleocr-vlm-server:8118/v1"
}
```

| Field | Type | Description |
|---|---|---|
| `status` | string | Gateway state; currently `healthy` after successful startup |
| `vllm_url` | string | Internal vLLM base URL configured for the gateway |

---

## `POST /parse/image`

Parses one image synchronously. The HTTP request remains open until vLLM
returns the page result or the backend request fails.

The server-side vLLM request timeout is 600 seconds. Clients and upstream
proxies must allow enough time for synchronous image processing or use the
asynchronous PDF workflow for multi-page documents.

### Request

Content type: `multipart/form-data`

| Field | Location | Type | Required | Description |
|---|---|---|---|---|
| `file` | form body | binary | Yes | One PNG, JPEG, WebP, or TIFF image |

Accepted filename extensions:

```text
.png .jpg .jpeg .webp .tif .tiff
```

Accepted media types are `image/png`, `image/jpeg`, `image/jpg`, `image/webp`,
`image/tiff`, and `application/octet-stream`. The filename must have a supported
extension. Maximum upload size is controlled by `MAX_FILE_SIZE_MB`.

```bash
curl --fail-with-body -X POST http://localhost:8080/parse/image \
  -H "Authorization: Bearer $OCR_API_KEY" \
  -F file=@page.png
```

### `200 OK`

Content type: `application/json`

```json
{
  "request_id": "2a60ce2be68a48f29545725fd5ef22db",
  "filename": "page.png",
  "content_type": "image/png",
  "file_size_bytes": 184233,
  "processed_pages": 1,
  "pages": [
    {
      "page": 1,
      "json": {
        "parsing_res_list": [
          {
            "block_label": "text",
            "block_content": "Parsed document text"
          }
        ]
      },
      "markdown": "Parsed document text"
    }
  ],
  "combined_markdown": "Parsed document text"
}
```

| Field | Type | Nullable | Description |
|---|---|---:|---|
| `request_id` | string | No | Unique 32-character request identifier |
| `filename` | string | Yes | Multipart filename supplied by the client |
| `content_type` | string | Yes | Multipart media type supplied by the client |
| `file_size_bytes` | integer | No | Number of uploaded bytes |
| `processed_pages` | integer | No | Always `1` for this endpoint |
| `pages` | array | No | One page result |
| `pages[].page` | integer | No | One-based page number; always `1` |
| `pages[].json` | object | No | Compact PaddleOCR-VL structured page result |
| `pages[].markdown` | string | No | Markdown assembled from the structured blocks |
| `combined_markdown` | string | No | Same value as page-one Markdown |

The contents of `pages[].json` are model-defined and may gain fields when the
pinned PaddleOCR-VL SDK is upgraded. The API removes embedded images and Base64
image data before returning it.

### Errors

| Status | Condition |
|---:|---|
| `401` | Bearer token is missing or invalid |
| `413` | File exceeds `MAX_FILE_SIZE_MB` |
| `415` | Filename extension or media type is unsupported, or a PDF was submitted |
| `422` | Multipart field `file` is missing |
| `502` | vLLM inference failed or returned an invalid response |

Example backend failure:

```json
{
  "detail": "Document parsing failed: vLLM request failed: ..."
}
```

---

## `POST /parse/pdf`

Streams a PDF to durable storage, validates it, creates one page task per page,
and returns immediately with `202 Accepted`. Processing continues in background
workers.

### Request

Content type: `multipart/form-data`

| Parameter | Location | Type | Required | Default | Description |
|---|---|---|---|---|---|
| `file` | form body | binary | Yes | — | PDF upload |
| `output_format` | query | enum | No | `both` | Artifact selection: `json`, `markdown`, or `both` |

The filename must end in `.pdf`. Accepted media types are `application/pdf` and
`application/octet-stream`. Before queueing, the API rejects files that are:

- larger than `MAX_FILE_SIZE_MB`;
- encrypted or password protected;
- corrupt or not readable as PDF;
- empty;
- over the configured `MAX_PAGES` limit.

Example:

```bash
curl --fail-with-body -X POST \
  'http://localhost:8080/parse/pdf?output_format=both' \
  -H "Authorization: Bearer $OCR_API_KEY" \
  -F file=@document.pdf
```

### `202 Accepted`

```json
{
  "job_id": "16f86c44f021443f95df0c7af81c7f23",
  "status": "queued",
  "status_url": "/jobs/16f86c44f021443f95df0c7af81c7f23",
  "result_urls": {
    "json": "/jobs/16f86c44f021443f95df0c7af81c7f23/result/json",
    "markdown": "/jobs/16f86c44f021443f95df0c7af81c7f23/result/markdown"
  }
}
```

| Field | Type | Description |
|---|---|---|
| `job_id` | string | Durable job identifier |
| `status` | string | Initial state, normally `queued` |
| `status_url` | string | Relative URL for progress checks |
| `result_urls` | object | Relative URLs for requested artifacts only |

`output_format=json` exposes only `result_urls.json`; `markdown` exposes only
`result_urls.markdown`; `both` exposes both. A URL indicates the requested
artifact, not that it is ready.

### Errors

| Status | Condition |
|---:|---|
| `400` | PDF is corrupt, encrypted, empty, or exceeds `MAX_PAGES` |
| `401` | Bearer token is missing or invalid |
| `413` | Upload exceeds `MAX_FILE_SIZE_MB` |
| `415` | Filename extension or media type is unsupported, or the file is not submitted as PDF |
| `422` | `file` is missing or `output_format` is not `json`, `markdown`, or `both` |
| `429` | `MAX_JOBS` queued/running jobs already exist |

A queue-full response includes:

```http
Retry-After: 60
```

```json
{
  "detail": "PDF job queue is full"
}
```

---

## `GET /jobs/{job_id}`

Returns the current state and page-level progress counters for an owned job.

### Request

| Parameter | Location | Type | Required | Description |
|---|---|---|---|---|
| `job_id` | path | string | Yes | ID returned by `POST /parse/pdf` |

```bash
curl --fail-with-body \
  -H "Authorization: Bearer $OCR_API_KEY" \
  http://localhost:8080/jobs/16f86c44f021443f95df0c7af81c7f23
```

### `200 OK`

```json
{
  "job_id": "16f86c44f021443f95df0c7af81c7f23",
  "status": "running",
  "status_url": "/jobs/16f86c44f021443f95df0c7af81c7f23",
  "result_urls": {
    "json": "/jobs/16f86c44f021443f95df0c7af81c7f23/result/json",
    "markdown": "/jobs/16f86c44f021443f95df0c7af81c7f23/result/markdown"
  },
  "filename": "document.pdf",
  "created_at": 1784017200.125,
  "updated_at": 1784017218.702,
  "completed_at": null,
  "total_pages": 10,
  "pending_pages": 6,
  "running_pages": 2,
  "completed_pages": 2,
  "failed_pages": 0,
  "cancellation_requested": false,
  "retry_count": 1,
  "error": null
}
```

| Field | Type | Nullable | Description |
|---|---|---:|---|
| `job_id` | string | No | Durable job identifier |
| `status` | string | No | Current lifecycle state |
| `status_url` | string | No | Relative status URL |
| `result_urls` | object | No | Requested artifact URLs |
| `filename` | string | No | Original client filename |
| `created_at` | number | No | Creation time as Unix seconds |
| `updated_at` | number | No | Last state-change time as Unix seconds |
| `completed_at` | number | Yes | Terminal completion time; otherwise `null` |
| `total_pages` | integer | No | Validated PDF page count |
| `pending_pages` | integer | No | Pages waiting to be claimed or retried |
| `running_pages` | integer | No | Pages with active worker leases |
| `completed_pages` | integer | No | Successfully parsed pages |
| `failed_pages` | integer | No | Permanently failed pages |
| `cancellation_requested` | boolean | No | Whether cancellation has been requested |
| `retry_count` | integer | No | Number of transient backend retries scheduled |
| `error` | string | Yes | Most recent job/page/assembly error summary |

Cancelled page tasks are not exposed as a separate counter. Consequently, page
counters do not necessarily add up to `total_pages` after cancellation.

### Job states

| Status | Terminal | Meaning |
|---|---:|---|
| `queued` | No | Pages are waiting for workers |
| `running` | No | At least one page is running or has completed while more remain |
| `assembling` | No | Page JSON is complete and requested artifacts are being assembled |
| `completed` | Yes | Requested artifacts are ready |
| `failed` | Yes | A page or artifact assembly failed permanently |
| `cancelled` | Yes | Cancellation completed between page tasks |

Typical lifecycle:

```text
queued → running → assembling → completed
                 ↘ failed
queued/running → cancelled
```

Clients should stop polling at `completed`, `failed`, or `cancelled`. Polling
every one or two seconds is sufficient for the current deployment.

### Errors

| Status | Condition |
|---:|---|
| `401` | Bearer token is missing or invalid |
| `404` | Job is unknown, expired, or owned by another token |

```json
{
  "detail": "Job not found"
}
```

---

## `GET /jobs/{job_id}/result/{artifact}`

Downloads one completed artifact. This is a raw file response, not a JSON
wrapper.

### Request

| Parameter | Location | Type | Required | Values |
|---|---|---|---|---|
| `job_id` | path | string | Yes | ID returned at submission |
| `artifact` | path | enum | Yes | `json` or `markdown` |

### JSON result

```bash
curl --fail-with-body \
  -H "Authorization: Bearer $OCR_API_KEY" \
  -o result.json \
  http://localhost:8080/jobs/16f86c44f021443f95df0c7af81c7f23/result/json
```

Response headers include:

```http
Content-Type: application/json
Content-Disposition: attachment; filename="16f86c44f021443f95df0c7af81c7f23.json"
```

Artifact structure:

```json
{
  "job_id": "16f86c44f021443f95df0c7af81c7f23",
  "filename": "document.pdf",
  "pages": [
    {
      "page": 1,
      "json": {
        "parsing_res_list": [
          {
            "block_label": "paragraph_title",
            "block_content": "Introduction"
          },
          {
            "block_label": "text",
            "block_content": "First page text."
          }
        ]
      }
    }
  ]
}
```

| Field | Type | Description |
|---|---|---|
| `job_id` | string | Source job identifier |
| `filename` | string | Original client filename |
| `pages` | array | Compact page results in ascending page order |
| `pages[].page` | integer | One-based page number |
| `pages[].json` | object | Compact PaddleOCR-VL structured page result |

Embedded and Base64 images are removed. Cross-page title levels and repeated
table headers may be normalized during artifact assembly.

### Markdown result

```bash
curl --fail-with-body \
  -H "Authorization: Bearer $OCR_API_KEY" \
  -o result.md \
  http://localhost:8080/jobs/16f86c44f021443f95df0c7af81c7f23/result/markdown
```

Response headers include:

```http
Content-Type: text/markdown; charset=utf-8
Content-Disposition: attachment; filename="16f86c44f021443f95df0c7af81c7f23.md"
```

Example artifact:

```markdown
## Page 1

# Document title

First page text.

---

## Page 2

Second page text.

---
```

The assembler preserves reading order from structured page blocks and handles
headings, paragraphs, lists, tables, display formulas, and code-like blocks.
Generated image markup is removed.

### Errors

| Status | Condition |
|---:|---|
| `401` | Bearer token is missing or invalid |
| `404` | Job is unknown/expired, artifact is unknown, artifact was not requested, or job belongs to another token |
| `409` | Job is not `completed`, or the artifact file is not ready |

If an artifact returns `409` immediately after a just-observed `completed`
status, repeat the status request and retry the artifact: the worker may be in
the short transition that finalizes artifact assembly.

Examples:

```json
{
  "detail": "Job is running"
}
```

```json
{
  "detail": "Artifact was not requested"
}
```

---

## `DELETE /jobs/{job_id}`

Requests cancellation. Pending pages are cancelled immediately. A page that
already holds a worker lease may finish, but no additional page is claimed for
the job.

### Request

```bash
curl --fail-with-body -X DELETE \
  -H "Authorization: Bearer $OCR_API_KEY" \
  http://localhost:8080/jobs/16f86c44f021443f95df0c7af81c7f23
```

### `202 Accepted`

Returns the same full job representation as `GET /jobs/{job_id}`. A queued job
with no running page normally becomes `cancelled` immediately:

```json
{
  "job_id": "16f86c44f021443f95df0c7af81c7f23",
  "status": "cancelled",
  "status_url": "/jobs/16f86c44f021443f95df0c7af81c7f23",
  "result_urls": {
    "markdown": "/jobs/16f86c44f021443f95df0c7af81c7f23/result/markdown"
  },
  "filename": "document.pdf",
  "created_at": 1784017200.125,
  "updated_at": 1784017202.914,
  "completed_at": 1784017202.914,
  "total_pages": 10,
  "pending_pages": 0,
  "running_pages": 0,
  "completed_pages": 0,
  "failed_pages": 0,
  "cancellation_requested": true,
  "retry_count": 0,
  "error": null
}
```

When a page is already running, the response may remain `running` with
`cancellation_requested: true` until that page exits. Repeat status requests
until the job becomes `cancelled`.

Cancellation is idempotent for an existing terminal job: the endpoint returns
its unchanged representation with `202`.

### Errors

| Status | Condition |
|---:|---|
| `401` | Bearer token is missing or invalid |
| `404` | Job is unknown, expired, or owned by another token |

---

## Error format

Application errors use FastAPI's standard `detail` envelope:

```json
{
  "detail": "Human-readable error message"
}
```

Request-validation failures return `422` with a structured list:

```json
{
  "detail": [
    {
      "type": "missing",
      "loc": ["body", "file"],
      "msg": "Field required",
      "input": null
    }
  ]
}
```

Clients should branch on HTTP status and treat `detail` as diagnostic text, not
as a stable machine error code.

| Status | General meaning | Retry guidance |
|---:|---|---|
| `400` | PDF validation failed | Fix or replace the document |
| `401` | Authentication failed | Correct the bearer token |
| `404` | Resource is unavailable to this token | Do not retry indefinitely |
| `409` | Artifact is not ready | Poll job status before retrying |
| `413` | Upload is too large | Reduce file size or change server limit |
| `415` | File extension/media type is unsupported | Correct the upload metadata/file type |
| `422` | Request shape or query value is invalid | Correct the request |
| `429` | PDF queue is full | Retry after the `Retry-After` delay |
| `500` | Unexpected gateway failure | Retry with bounded backoff and investigate logs |
| `502` | Synchronous backend inference failed | Retry with bounded backoff if appropriate |

## End-to-end PDF client flow

```text
POST /parse/pdf
  → save job_id and relative URLs
  → GET status_url every 1-2 seconds
      → queued/running/assembling: continue polling
      → completed: download each result URL
      → failed/cancelled: stop and inspect error/status
```

Minimal shell example:

```bash
BASE_URL=http://localhost:8080

curl --fail-with-body -X POST \
  "$BASE_URL/parse/pdf?output_format=both" \
  -H "Authorization: Bearer $OCR_API_KEY" \
  -F file=@document.pdf

# Read job_id and status_url from the 202 response, then:
curl --fail-with-body \
  -H "Authorization: Bearer $OCR_API_KEY" \
  "$BASE_URL/jobs/<job_id>"

# After status becomes completed:
curl --fail-with-body \
  -H "Authorization: Bearer $OCR_API_KEY" \
  -o result.json \
  "$BASE_URL/jobs/<job_id>/result/json"
```

The API currently uses polling and does not expose webhooks or server-sent
events.

## Limits and retention

| Setting | Default | Effect |
|---|---:|---|
| `MAX_FILE_SIZE_MB` | `100` | Maximum streamed upload size |
| `MAX_PAGES` | `100` | Maximum accepted PDF page count |
| `MAX_JOBS` | `20` | Maximum jobs in `queued` or `running` state |
| `MAX_RETRIES` | `3` | Transient page-inference retries |
| `LEASE_SECONDS` | `900` | Worker page lease duration before crash recovery |
| `RETENTION_HOURS` | `24` | Terminal job and artifact retention |

After retention cleanup, status and result requests return `404`. The SQLite
database and artifacts use local Docker storage and are not shared across
machines.
