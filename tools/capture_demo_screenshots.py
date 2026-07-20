from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
from typing import Any
from urllib.parse import urlparse
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASE_URL = "http://127.0.0.1:8789"
DEFAULT_OUTPUT_DIR = ROOT / "docs" / "submission" / "media" / "m71-replay"
DEFAULT_VIEWPORT = (1280, 720)
MIN_SCREENSHOT_BYTES = 20_000

SHOT_SPECS = (
    {
        "filename": "01-one-click-stale-memory-replay.png",
        "label": "One-click stale-memory failure replay",
        "path": "/?view=learn",
    },
    {
        "filename": "02-recallpack-active-memory-pack.png",
        "label": "RecallPack active memory pack",
        "path": "/?view=recall",
    },
    {
        "filename": "03-qwen-provider-evidence.png",
        "label": "Qwen provider evidence",
        "path": "/?view=evaluate",
    },
)

CHROME_CANDIDATES = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "google-chrome",
    "chromium",
    "chromium-browser",
    "microsoft-edge",
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Capture local RecallPack Devpost screenshot candidates."
    )
    parser.add_argument("--url", default=DEFAULT_BASE_URL, help="Local demo server base URL.")
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help="Directory for generated screenshot PNG files.",
    )
    parser.add_argument("--chrome", help="Chrome/Chromium executable path.")
    parser.add_argument("--timeout", type=int, default=20, help="Seconds per screenshot.")
    parser.add_argument(
        "--list",
        action="store_true",
        help="Print the screenshot plan as JSON without requiring Chrome or a server.",
    )
    args = parser.parse_args()

    if args.list:
        print(json.dumps(build_plan(args.url), indent=2))
        return 0

    chrome = resolve_chrome(args.chrome)
    if not chrome:
        print("Chrome or Chromium executable not found.", file=sys.stderr)
        return 2

    base_url = normalize_base_url(args.url)
    if not is_local_demo_url(base_url):
        print("Only local demo URLs are supported.", file=sys.stderr)
        return 2
    if not server_is_available(base_url):
        print(f"Demo server is not reachable: {base_url}", file=sys.stderr)
        return 2

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    results = []
    for shot in build_plan(base_url)["shots"]:
        target = output_dir / shot["filename"]
        result = capture_shot(
            chrome=chrome,
            url=shot["url"],
            target=target,
            timeout=args.timeout,
        )
        results.append({**shot, **result})

    print(
        json.dumps(
            {
                "status": "passed",
                "output_dir": str(output_dir),
                "requires_live_qwen": False,
                "uploads_media": False,
                "viewport": viewport_label(),
                "shots": results,
            },
            indent=2,
        )
    )
    return 0


def build_plan(base_url: str) -> dict[str, Any]:
    base = normalize_base_url(base_url)
    return {
        "requires_live_qwen": False,
        "uploads_media": False,
        "viewport": viewport_label(),
        "shots": [
            {
                "filename": shot["filename"],
                "label": shot["label"],
                "url": f"{base}{shot['path']}",
            }
            for shot in SHOT_SPECS
        ],
    }


def normalize_base_url(value: str) -> str:
    return value.rstrip("/")


def is_local_demo_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and parsed.hostname in {
        "127.0.0.1",
        "localhost",
        "::1",
    }


def viewport_label() -> str:
    return f"{DEFAULT_VIEWPORT[0]}x{DEFAULT_VIEWPORT[1]}"


def resolve_chrome(explicit: str | None = None) -> str | None:
    candidates = (explicit,) if explicit else CHROME_CANDIDATES
    for candidate in candidates:
        if not candidate:
            continue
        path = Path(candidate)
        if path.is_file():
            return str(path)
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
    return None


def server_is_available(base_url: str) -> bool:
    try:
        with urlopen(f"{base_url}/api/health", timeout=5) as response:
            return response.status == 200
    except Exception:
        return False


def capture_shot(
    *,
    chrome: str,
    url: str,
    target: Path,
    timeout: int,
) -> dict[str, Any]:
    if target.exists():
        target.unlink()
    profile = Path(tempfile.mkdtemp(prefix="recallpack-chrome-shot-"))
    command = [
        chrome,
        "--headless",
        "--disable-gpu",
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--disable-background-networking",
        "--disable-component-update",
        "--disable-default-apps",
        "--disable-extensions",
        "--disable-sync",
        "--metrics-recording-only",
        "--no-first-run",
        "--no-default-browser-check",
        "--hide-scrollbars",
        f"--user-data-dir={profile}",
        f"--window-size={DEFAULT_VIEWPORT[0]},{DEFAULT_VIEWPORT[1]}",
        "--virtual-time-budget=3000",
        f"--screenshot={target}",
        url,
    ]
    timed_out = False
    try:
        subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
            check=True,
        )
    except subprocess.TimeoutExpired:
        timed_out = True
    finally:
        shutil.rmtree(profile, ignore_errors=True)

    width, height = read_png_size(target)
    size = target.stat().st_size
    if width < DEFAULT_VIEWPORT[0] or height < DEFAULT_VIEWPORT[1]:
        raise ValueError(f"Screenshot is too small: {target} {width}x{height}")
    if size < MIN_SCREENSHOT_BYTES:
        raise ValueError(f"Screenshot may be blank: {target} {size} bytes")
    return {
        "path": str(target),
        "bytes": size,
        "width": width,
        "height": height,
        "chrome_timed_out_after_write": timed_out,
    }


def read_png_size(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError(f"Not a PNG file: {path}")
    return struct.unpack(">II", data[16:24])


if __name__ == "__main__":
    sys.exit(main())
