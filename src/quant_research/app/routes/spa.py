"""Read-only serving helpers for the built QDR Vue single-page application."""

from __future__ import annotations

import mimetypes
from pathlib import Path

DIST_DIR = Path(__file__).resolve().parents[2] / "assets" / "dist"


def render_spa_index(console_token: str) -> tuple[bytes, str] | None:
    """Return the built SPA shell with its loopback console token injected."""
    index_file = DIST_DIR / "index.html"
    if not index_file.is_file():
        return None
    html = index_file.read_text(encoding="utf-8").replace("__TOKEN__", console_token)
    return html.encode("utf-8"), "text/html; charset=utf-8"


def read_dist_asset(relative_path: str) -> tuple[bytes, str] | None:
    """Serve a built asset only when its resolved path stays inside dist/."""
    root = DIST_DIR.resolve()
    candidate = (root / relative_path.lstrip("/")).resolve()
    if not candidate.is_relative_to(root) or not candidate.is_file():
        return None
    mime, _ = mimetypes.guess_type(str(candidate))
    return candidate.read_bytes(), mime or "application/octet-stream"
