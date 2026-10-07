"""Uploaded pictures (R6b): member photos and club pictures.

Every upload is opened with Pillow, checked, turned upright, cropped square,
resized and re-saved as WebP. Re-saving drops everything but the pixels, so
location (GPS) and camera details never reach the server's disk. Files get
random, unguessable names in the instance folder (the NAS data volume) and
are served at /api/media/<name>.
"""

import os
import re
import secrets
from io import BytesIO

MAX_BYTES = 5 * 1024 * 1024
SIZES = {'avatar': 256, 'club': 512}
FORMATS = {'JPEG', 'MPO', 'PNG', 'WEBP', 'GIF'}     # MPO: phone JPEGs with a depth map
MAX_PIXELS = 40_000_000                            # refuse "decompression bombs"
URL_PREFIX = '/api/media/'
NAME_RE = re.compile(r'^[a-f0-9]{32}\.webp$')


class BadImage(Exception):
    """Not a picture we can use (the message is safe to show)."""


def media_dir(instance_path):
    path = os.path.join(instance_path, 'media')
    os.makedirs(path, exist_ok=True)
    return path


def save(instance_path, data, kind):
    """Process an upload and store it; returns its URL. Raises BadImage."""
    from PIL import Image, ImageOps
    if not data:
        raise BadImage('Choose a picture to upload.')
    if len(data) > MAX_BYTES:
        raise BadImage('That picture is over 5 MB. Try a smaller one.')
    Image.MAX_IMAGE_PIXELS = MAX_PIXELS
    try:
        img = Image.open(BytesIO(data))
        if img.format not in FORMATS:
            raise BadImage('Use a JPEG, PNG, WebP or GIF.')
        img.seek(0)                                # GIFs: the first frame
        img.load()
        img = ImageOps.exif_transpose(img)         # phone photos come out upright
        alpha = img.mode in ('RGBA', 'LA') or (img.mode == 'P' and 'transparency' in img.info)
        img = img.convert('RGBA' if alpha else 'RGB')
        size = SIZES[kind]
        img = ImageOps.fit(img, (size, size), Image.LANCZOS)
    except BadImage:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise BadImage('That picture is too large to process.')
    except Exception:
        raise BadImage("That file isn't a picture we can read.")
    name = f'{secrets.token_hex(16)}.webp'
    folder = media_dir(instance_path)
    tmp = os.path.join(folder, f'.{name}.tmp')
    img.save(tmp, 'WEBP', quality=85, method=4)
    os.replace(tmp, os.path.join(folder, name))
    return URL_PREFIX + name


def delete(instance_path, url):
    """Remove a stored picture (no-op for anything else, e.g. Discord pictures)."""
    if not url or not url.startswith(URL_PREFIX):
        return
    name = url[len(URL_PREFIX):]
    if NAME_RE.match(name):
        try:
            os.remove(os.path.join(media_dir(instance_path), name))
        except FileNotFoundError:
            pass


def clean_emoji(value):
    """An emoji (or short emoji sequence) to use as a picture, or None. Letters
    and digits aren't allowed: this is for 🎬, not text."""
    v = (value or '').strip()
    if not v or len(v) > 16 or any(c.isspace() for c in v) or any(c.isascii() and c.isalnum() for c in v):
        return None
    if all(c.isascii() for c in v):
        return None
    return v
