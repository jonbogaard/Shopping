"""
Beer Money PWA Builder
Reads price_history.json + config.json → injects data into pwa/index.html template.
Run by GitHub Actions daily after scraping, or locally for testing.

Usage:
    python build_pwa.py              # Build from repo root
    python build_pwa.py --out docs   # Build to /docs (for GitHub Pages)
"""
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).parent
HISTORY_PATH = BASE_DIR / "price_history.json"
CONFIG_PATH = BASE_DIR / "config.json"
TEMPLATE_DIR = BASE_DIR / "pwa"
TEMPLATE_PATH = TEMPLATE_DIR / "index.html"

# Default output to /docs (GitHub Pages serves from /docs on main branch)
OUT_DIR = BASE_DIR / "docs"
if "--out" in sys.argv:
    idx = sys.argv.index("--out")
    if idx + 1 < len(sys.argv):
        OUT_DIR = BASE_DIR / sys.argv[idx + 1]


def build():
    print("🍺 Beer Money PWA Builder")

    # Load data
    with open(HISTORY_PATH) as f:
        price_data = json.load(f)
    with open(CONFIG_PATH) as f:
        config = json.load(f)

    build_time = datetime.now(timezone.utc).strftime("%b %d, %Y %I:%M %p UTC")
    print(f"   Build time: {build_time}")
    print(f"   Products: {len(price_data)} tracked")

    # Read template
    template = TEMPLATE_PATH.read_text(encoding="utf-8")

    # Inject data — replace placeholder objects
    price_json = json.dumps(price_data, separators=(",", ":"))
    config_json = json.dumps(config, separators=(",", ":"))

    html = template.replace(
        "/*PRICE_DATA_PLACEHOLDER*/ {}", price_json
    ).replace(
        "/*CONFIG_PLACEHOLDER*/ {}", config_json
    ).replace(
        "/*BUILD_TIME_PLACEHOLDER*/", build_time
    )

    # Update service worker cache version with build timestamp
    sw_cache_version = f"beer-money-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M')}"

    sw_content = (TEMPLATE_DIR / "sw.js").read_text(encoding="utf-8")
    sw_content = sw_content.replace("beer-money-v1", sw_cache_version)

    # Write output
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    (OUT_DIR / "index.html").write_text(html, encoding="utf-8")
    (OUT_DIR / "sw.js").write_text(sw_content, encoding="utf-8")

    # Copy manifest
    shutil.copy(TEMPLATE_DIR / "manifest.json", OUT_DIR / "manifest.json")

    # Copy icons if they exist
    for icon in ["icon-192.png", "icon-512.png"]:
        icon_path = TEMPLATE_DIR / icon
        if icon_path.exists():
            shutil.copy(icon_path, OUT_DIR / icon)

    out_size = (OUT_DIR / "index.html").stat().st_size
    print(f"   Output: {OUT_DIR / 'index.html'} ({out_size:,} bytes)")
    print(f"   Cache version: {sw_cache_version}")
    print("   ✅ Build complete!")


if __name__ == "__main__":
    build()
