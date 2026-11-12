"""Optional installed-font metrics for layout; no fonts are bundled or copied."""
from functools import lru_cache
import os
from pathlib import Path
import unicodedata


@lru_cache(maxsize=2)
def font_path(bold=False):
    filename = "malgunbd.ttf" if bold else "malgun.ttf"
    candidates = [os.environ.get("KOICA_FONT_BOLD" if bold else "KOICA_FONT", ""),
                  f"/Applications/Microsoft PowerPoint.app/Contents/Resources/DFonts/{filename}",
                  str(Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / filename)]
    return next((Path(p) for p in candidates if p and Path(p).is_file()), None)


@lru_cache(maxsize=2)
def _font(bold=False):
    path = font_path(bold)
    if path:
        try:
            from PIL import ImageFont
            return ImageFont.truetype(str(path), 1024)
        except (ImportError, OSError):
            pass
    return None


@lru_cache(maxsize=16384)
def measure(text, size_pt, bold=False, tracking_pt=-0.64):
    font = _font(bold)
    em = (font.getlength(text) / 1024 if font else
          sum(1.0 if unicodedata.east_asian_width(c) in "WF" else 0.5 for c in text))
    return max(0, (em * size_pt + max(0, len(text) - 1) * tracking_pt) / 72)


def mode():
    return "installed-font" if _font() else "estimated"
