from pathlib import Path

from PIL import Image, ImageOps


def open_normalized_image(path: Path) -> Image.Image:
    """Open an image with EXIF orientation applied."""
    with Image.open(path) as img:
        return ImageOps.exif_transpose(img)
