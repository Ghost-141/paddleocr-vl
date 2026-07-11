# PaddleOCR-VL API Reference

This guide describes how to query the running PaddleOCR-VL API. The API accepts
one image or one PDF per request and always returns JSON. PDF requests can
include structured PaddleOCR results, assembled Markdown, or both.

## Base URL

For a local deployment using the default `APP_PORT=8080`:

```bash
export OCR_API_URL="http://localhost:8080"
export OCR_API_KEY="value-of-PUBLIC_API_KEY"
```

For a public deployment, use its HTTPS origin instead:

```bash
export OCR_API_URL="https://ocr.example.com"
export OCR_API_KEY="value-of-PUBLIC_API_KEY"
```

Do not add a trailing slash to `OCR_API_URL` in these examples.

## Authentication

The image and PDF endpoints require the public API key as a bearer token:

```text
Authorization: Bearer <PUBLIC_API_KEY>
```

The `/health` endpoint does not require authentication. Keep the API key out of
source control, URLs, query strings, and application logs.

## Request Limits

| Setting | Default | Behavior |
| --- | ---: | --- |
| `MAX_FILE_SIZE_MB` | `100` | Rejects a larger upload with HTTP 413 |
| `MAX_PAGES` | `100` | Limits the PDF page results returned and assembled |

`MAX_FILE_SIZE_MB` is measured in MiB (`1 MiB = 1,048,576 bytes`). The current
pipeline applies `MAX_PAGES` after PaddleOCR prediction, so it limits the
response but does not stop initial PDF inference early. Long or visually
complex documents can take several minutes; configure client and reverse-proxy
timeouts accordingly.

## Health Check

### `GET /health`

Checks whether the API process and PaddleOCR pipeline are ready. Authentication
is not required.

```bash
curl --fail-with-body "$OCR_API_URL/health"
```

Example response:

```json
{
  "status": "healthy",
  "pipeline_loaded": true,
  "vllm_server_url": "http://paddleocr-vlm-server:8118/v1",
  "vllm_model": "PaddleOCR-VL-1.6-0.9B",
  "layout_model": "PP-DocLayoutV2"
}
```

`status` is `healthy` when the pipeline is loaded and `starting` otherwise.

## Parse an Image

### `POST /parse/image`

Processes exactly one image and returns structured page JSON plus clean
Markdown. This endpoint has no query parameters.

| Parameter | Location | Type | Required | Description |
| --- | --- | --- | --- | --- |
| `file` | Multipart form | File | Yes | PNG, JPEG, WebP, or TIFF image |

Supported extensions are `.png`, `.jpg`, `.jpeg`, `.webp`, `.tif`, and
`.tiff`. Accepted MIME types are `image/png`, `image/jpeg`, `image/jpg`,
`image/webp`, `image/tiff`, and `application/octet-stream`.

```bash
curl --fail-with-body \
  --request POST \
  "$OCR_API_URL/parse/image" \
  --header "Authorization: Bearer $OCR_API_KEY" \
  --form "file=@page.png" \
  --output image-response.json
```

Example response shape:

```json
{
  "request_id": "dd5427dfcb314211952ad143974e7aec",
  "filename": "page.png",
  "content_type": "image/png",
  "file_size_bytes": 84231,
  "processed_pages": 1,
  "pages": [
    {
      "page": 1,
      "json": {
        "parsing_res_list": []
      },
      "markdown": "# Document title\n\nDocument text."
    }
  ],
  "combined_markdown": "# Document title\n\nDocument text."
}
```

Extract the assembled Markdown with `jq`:

```bash
jq --raw-output '.combined_markdown' image-response.json > image-output.md
```

Multiple images must be sent as separate requests.

## Parse a PDF

### `POST /parse/pdf`

Processes one single-page or multi-page PDF.

| Parameter | Location | Type | Required | Default | Description |
| --- | --- | --- | --- | --- | --- |
| `file` | Multipart form | File | Yes | None | PDF document |
| `output_format` | Query string | Enum | No | `both` | `json`, `markdown`, or `both` |

The filename must end in `.pdf`. Accepted MIME types are `application/pdf` and
`application/octet-stream`.

### JSON and Markdown

Omitting `output_format` is equivalent to `output_format=both`:

```bash
curl --fail-with-body \
  --request POST \
  "$OCR_API_URL/parse/pdf?output_format=both" \
  --header "Authorization: Bearer $OCR_API_KEY" \
  --form "file=@document.pdf" \
  --output document-response.json
```

The response contains request metadata, `pages`, and `combined_markdown`. Each
page contains `page`, `json`, and `markdown`.

### Structured JSON Only

```bash
curl --fail-with-body \
  --request POST \
  "$OCR_API_URL/parse/pdf?output_format=json" \
  --header "Authorization: Bearer $OCR_API_KEY" \
  --form "file=@document.pdf" \
  --output document-structure.json
```

The response contains `pages`, but each page contains only `page` and `json`.
It does not contain `combined_markdown` or page-level `markdown` fields.

### Markdown Only

```bash
curl --fail-with-body \
  --request POST \
  "$OCR_API_URL/parse/pdf?output_format=markdown" \
  --header "Authorization: Bearer $OCR_API_KEY" \
  --form "file=@document.pdf" \
  --output document-markdown-response.json
```

This still returns an `application/json` response. Extract the Markdown string
into a file:

```bash
jq --raw-output '.combined_markdown' \
  document-markdown-response.json > document.md
```

The Markdown-only response has this shape:

```json
{
  "request_id": "f85b73e19d9a471394637fc03a612fb1",
  "filename": "document.pdf",
  "content_type": "application/pdf",
  "file_size_bytes": 524288,
  "processed_pages": 4,
  "combined_markdown": "# Document title\n\nDocument text."
}
```

## Python Example

This example processes a PDF and saves its assembled Markdown:

```python
import os
from pathlib import Path

import httpx

base_url = os.environ["OCR_API_URL"]
api_key = os.environ["OCR_API_KEY"]
pdf_path = Path("document.pdf")

with pdf_path.open("rb") as pdf_file:
    response = httpx.post(
        f"{base_url}/parse/pdf",
        params={"output_format": "markdown"},
        headers={"Authorization": f"Bearer {api_key}"},
        files={"file": (pdf_path.name, pdf_file, "application/pdf")},
        timeout=600,
    )

response.raise_for_status()
Path("document.md").write_text(
    response.json()["combined_markdown"],
    encoding="utf-8",
)
```

For an image, change the URL to `/parse/image`, remove `params`, and supply the
appropriate image MIME type. The image endpoint always returns both formats.

## Response Fields

| Field | Type | Present when | Description |
| --- | --- | --- | --- |
| `request_id` | String | Always | Unique request identifier |
| `filename` | String or null | Always | Original multipart filename |
| `content_type` | String or null | Always | MIME type supplied by the client |
| `file_size_bytes` | Integer | Always | Number of uploaded bytes |
| `processed_pages` | Integer | Always | Number of page results returned |
| `pages` | Array | Image, PDF `json`, or PDF `both` | Ordered page results |
| `combined_markdown` | String | Image, PDF `markdown`, or PDF `both` | Assembled Markdown |

Each item in `pages` can contain:

| Field | Type | Description |
| --- | --- | --- |
| `page` | Integer | One-based page number |
| `json` | Object | Raw structured PaddleOCR page result |
| `markdown` | String | Page Markdown; included for images and PDF `both` |

## Error Responses

Errors use FastAPI's standard JSON shape:

```json
{
  "detail": "Error description"
}
```

| Status | Meaning | Typical cause |
| ---: | --- | --- |
| `401` | Unauthorized | Missing or invalid bearer token |
| `413` | Content too large | Upload exceeds `MAX_FILE_SIZE_MB` |
| `415` | Unsupported media type | Unsupported file or wrong endpoint |
| `422` | Invalid request | Missing `file` or invalid `output_format` |
| `502` | OCR backend failure | PaddleOCR or vLLM inference failed |

Use `curl --fail-with-body` to preserve the JSON error body while returning a
nonzero shell exit status.

## Interactive Specification

FastAPI exposes Swagger documentation and its OpenAPI schema at:

```text
GET /docs
GET /openapi.json
```

For example, with the default `APP_PORT=8080`, open
`http://localhost:8080/docs`. Replace `8080` with the configured production
port when necessary.
