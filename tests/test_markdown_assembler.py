from paddlocr_vl.utils.markdown_assembler import (
    assemble_document_markdown,
    assemble_page_markdown,
)


def test_assemble_page_markdown_filters_noise_and_preserves_structure() -> None:
    page = {
        "model_settings": {
            "markdown_ignore_labels": [
                "number",
                "footnote",
                "header",
                "header_image",
                "footer",
                "footer_image",
                "aside_text",
            ]
        },
        "parsing_res_list": [
            {"block_label": "header_image", "block_content": "<img src='data:image/jpeg;base64,AAA' />", "block_bbox": [0, 0, 10, 10], "block_order": None, "global_block_id": 1},
            {"block_label": "paragraph_title", "block_content": "### Linear Regression", "block_bbox": [10, 10, 20, 20], "block_order": 1, "global_block_id": 2},
            {"block_label": "text", "block_content": "Linear models are simple.", "block_bbox": [10, 30, 20, 40], "block_order": 2, "global_block_id": 3},
            {"block_label": "chart", "block_content": '<div style="text-align: center;"><img src="imgs/chart.png" /></div>', "block_bbox": [10, 50, 20, 60], "block_order": 3, "global_block_id": 4},
            {"block_label": "display_formula", "block_content": " $$ x = y + 1 $$ ", "block_bbox": [10, 70, 20, 80], "block_order": 4, "global_block_id": 5},
            {"block_label": "text", "block_content": "from scipy.optimize import minimize\ndef loss(v):\n    return v[0]", "block_bbox": [10, 90, 20, 100], "block_order": 5, "global_block_id": 6},
            {"block_label": "number", "block_content": "[73]", "block_bbox": [10, 110, 20, 120], "block_order": None, "global_block_id": 7},
        ],
    }

    markdown = assemble_page_markdown(page)

    assert "### Linear Regression" in markdown
    assert "Linear models are simple." in markdown
    assert "$$\n$$" not in markdown
    assert "$$" in markdown
    assert "```text" in markdown
    assert "from scipy.optimize import minimize" in markdown
    assert "chart.png" not in markdown
    assert "[73]" not in markdown


def test_assemble_document_markdown_joins_pages_without_page_noise() -> None:
    document = assemble_document_markdown(
        [
            {
                "parsing_res_list": [
                    {"block_label": "paragraph_title", "block_content": "## Page 1", "block_bbox": [0, 0, 10, 10], "block_order": 1, "global_block_id": 1},
                    {"block_label": "text", "block_content": "First page text.", "block_bbox": [0, 10, 10, 20], "block_order": 2, "global_block_id": 2},
                ]
            },
            {
                "parsing_res_list": [
                    {"block_label": "paragraph_title", "block_content": "## Page 2", "block_bbox": [0, 0, 10, 10], "block_order": 1, "global_block_id": 3},
                    {"block_label": "text", "block_content": "Second page text.", "block_bbox": [0, 10, 10, 20], "block_order": 2, "global_block_id": 4},
                ]
            },
        ]
    )

    assert document == "## Page 1\n\nFirst page text.\n\n## Page 2\n\nSecond page text."
