from __future__ import annotations

from collections.abc import Mapping, Sequence
import re
from typing import Any

from .file_utils import strip_markdown_images

DEFAULT_IGNORE_LABELS = {
    "header",
    "footer",
    "number",
    "footnote",
    "aside_text",
    "header_image",
    "footer_image",
    "chart",
    "image",
    "figure",
}
HEADING_RE = re.compile(r"^\s*(#{1,6})\s*(.+?)\s*$")
INLINE_SPACE_RE = re.compile(r"[ \t]+")
DOCUMENT_TITLE_LABELS = {"doc_title", "document_title", "title"}
SECTION_TITLE_LABELS = {"paragraph_title", "section_title"}
SUBSECTION_TITLE_LABELS = {"subsection_title", "sub_title"}


def assemble_document_markdown(pages: Sequence[Mapping[str, Any]]) -> str:
    page_markdowns = [
        assemble_page_markdown(page)
        for page in pages
        if page and isinstance(page, Mapping)
    ]
    page_markdowns = [markdown for markdown in page_markdowns if markdown.strip()]
    return "\n\n".join(page_markdowns).strip()


def assemble_page_markdown(page: Mapping[str, Any]) -> str:
    result = page.get("res")
    if isinstance(result, Mapping):
        page = result

    ignore_labels = set(DEFAULT_IGNORE_LABELS)
    model_settings = page.get("model_settings")
    if isinstance(model_settings, Mapping):
        ignore_labels.update(str(label) for label in model_settings.get("markdown_ignore_labels", []))

    blocks = page.get("parsing_res_list") or []
    # Paddle documents parsing_res_list as already being in reading order.
    ordered_blocks = [block for block in blocks if isinstance(block, Mapping)]

    rendered_blocks = [
        rendered
        for block in ordered_blocks
        if (rendered := render_block(block, ignore_labels)) is not None
    ]
    return "\n\n".join(rendered_blocks).strip()


def render_block(block: Mapping[str, Any], ignore_labels: set[str]) -> str | None:
    label = str(block.get("block_label") or "").strip()
    content = str(block.get("block_content") or "").strip()
    if not content or label in ignore_labels:
        return None

    if label in DOCUMENT_TITLE_LABELS:
        return normalize_heading(content, default_level=1)
    if label in SECTION_TITLE_LABELS:
        return normalize_heading(content, default_level=2)
    if label in SUBSECTION_TITLE_LABELS:
        return normalize_heading(content, default_level=3)
    if label == "display_formula":
        return normalize_display_formula(content)
    if label == "inline_formula":
        return normalize_inline_text(content)
    if label == "table":
        return normalize_table(content)

    cleaned = normalize_inline_text(content)
    if _looks_like_code_block(cleaned):
        return normalize_code_block(cleaned)
    return cleaned


def normalize_heading(text: str, default_level: int = 2) -> str:
    text = strip_markdown_images(text).strip()
    match = HEADING_RE.match(text)
    if match:
        level = len(match.group(1))
        title = match.group(2).strip()
    else:
        level = default_level
        title = text
    level = max(1, min(level, 6))
    return f'{"#" * level} {normalize_inline_text(title)}'


def normalize_display_formula(text: str) -> str:
    cleaned = strip_markdown_images(text).strip()
    if cleaned.startswith("$$") and cleaned.endswith("$$"):
        return cleaned
    return f"$$\n{cleaned}\n$$"


def normalize_table(text: str) -> str:
    cleaned = strip_markdown_images(text).strip()
    return cleaned


def normalize_inline_text(text: str) -> str:
    cleaned = strip_markdown_images(text).replace("\r\n", "\n").replace("\r", "\n")
    lines = [INLINE_SPACE_RE.sub(" ", line).strip() for line in cleaned.split("\n")]
    non_empty = [line for line in lines if line]
    if not non_empty:
        return ""
    if _looks_like_code_block(non_empty):
        return normalize_code_block("\n".join(non_empty))
    if _looks_like_list(non_empty):
        return "\n".join(non_empty)
    return " ".join(non_empty)


def normalize_code_block(text: str) -> str:
    lines = [line.rstrip() for line in text.splitlines()]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return "```text\n" + "\n".join(lines) + "\n```"


def _looks_like_list(lines: Sequence[str]) -> bool:
    return any(line.startswith(("- ", "* ", "+ ")) or re.match(r"^\d+\.\s+", line) for line in lines)


def _looks_like_code_block(lines: Sequence[str]) -> bool:
    if len(lines) < 2:
        return False

    code_hints = 0
    for line in lines:
        stripped = line.lstrip()
        if line.startswith(("    ", "\t")):
            code_hints += 1
            continue
        if stripped.startswith((">>>", "...", "from ", "import ", "def ", "class ", "return ", "for ", "while ", "if ")):
            code_hints += 1
            continue
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*\s*=\s*.+$", stripped):
            code_hints += 1
            continue
    return code_hints >= max(2, len(lines) // 2)
