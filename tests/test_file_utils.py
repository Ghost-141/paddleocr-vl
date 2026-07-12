from pathlib import Path

from paddlocr_vl.utils.file_utils import json_compatible, strip_markdown_images


def test_strip_markdown_images() -> None:
    result = strip_markdown_images(
        'Before\n\n<div style="text-align:center"><img src="imgs/chart.png" /></div>'
        '\n\n![figure](imgs/figure.jpg)\n\nAfter'
    )

    assert result == "Before\n\nAfter"


def test_strip_raw_image_data_uri() -> None:
    result = strip_markdown_images(
        "Before\n\ndata:image/jpeg;base64,aW1hZ2UtYnl0ZXM=\n\nAfter"
    )

    assert result == "Before\n\nAfter"


def test_strip_html_data_uri_image_tag() -> None:
    result = strip_markdown_images(
        'Before\n\n<div style="text-align: center;"><img '
        'src="data:image/jpeg;base64,/9j/4AAQSkZJRgABAQAAAQABAAD/" /></div>\n\nAfter'
    )

    assert result == "Before\n\nAfter"


def test_json_compatible_converts_nested_non_json_values() -> None:
    class ArrayLike:
        def tolist(self) -> list[int]:
            return [1, 2]

    result = json_compatible(
        {"path": Path("output.json"), "items": (ArrayLike(), Path("page.png"))}
    )

    assert result == {
        "path": "output.json",
        "items": [[1, 2], "page.png"],
    }
