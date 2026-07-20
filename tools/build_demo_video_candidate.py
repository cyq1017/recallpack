from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import textwrap
from typing import Any


SCRIPT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = Path("docs/submission/media/video-candidate")
DEFAULT_VIDEO_NAME = "recallpack-demo-candidate.mp4"
TARGET_DURATION_SECONDS = 156


def build_video_plan(root: Path = SCRIPT_ROOT) -> dict[str, Any]:
    media_root = root / "docs" / "submission" / "media" / "m71-replay"
    scenes = [
        {
            "id": "problem",
            "duration_seconds": 18,
            "image": media_root / "01-one-click-stale-memory-replay.png",
            "title": "MemoryAgent, not generic RAG",
            "caption": "RecallPack stores supersession before handoff selection loses the reversing decision.",
            "voiceover": (
                "When a fresh coding agent takes over, something has already "
                "decided what it gets to see. If selection keeps a decision the "
                "project later reversed, the agent may confidently write last "
                "week's code. RecallPack moves the decision earlier: judge "
                "supersession at write time, when old and reversing decisions "
                "are visible together before handoff budget selection."
            ),
        },
        {
            "id": "live_boundary",
            "duration_seconds": 12,
            "image": media_root / "03-qwen-provider-evidence.png",
            "title": "Live evidence boundary",
            "caption": "Stored live runs support lifecycle filtering, not a measured live baseline failure rate.",
            "voiceover": (
                "The stored live Qwen evidence supports the lifecycle boundary. "
                "RecallPack excluded stale retry memory in stored live runs, but "
                "the stored raw-history embedding and rerank baseline selected the "
                "active retry decision on this small fixture. So the local replay "
                "is an authored failure-class illustration, not live frequency evidence."
            ),
        },
        {
            "id": "baseline_failure",
            "duration_seconds": 20,
            "image": media_root / "01-one-click-stale-memory-replay.png",
            "title": "Local replay stale context fails",
            "caption": "Authored deterministic raw-history replay selects stale retry memory and fixture tests pass only 1/3.",
            "voiceover": (
                "In this deterministic local replay, the baseline raw-history "
                "path pulls the semantically similar old retry decision. That "
                "stale instruction produces the wrong retry patch, and the fixture "
                "tests show the consequence: one out of three passes."
            ),
        },
        {
            "id": "lifecycle",
            "duration_seconds": 22,
            "image": media_root / "02-recallpack-active-memory-pack.png",
            "title": "Remember, supersede, recall",
            "caption": "RecallPack keeps active memory separate from superseded history.",
            "voiceover": (
                "RecallPack observes session events as memory lifecycle operations. "
                "It remembers decisions and preferences, supersedes the old retry "
                "policy, and keeps the active retry decision plus the no-new-"
                "dependencies preference."
            ),
        },
        {
            "id": "recallpack_success",
            "duration_seconds": 22,
            "image": media_root / "02-recallpack-active-memory-pack.png",
            "title": "Active memory passes",
            "caption": "RecallPack active memory pack gives the local replay the correct patch: 3/3.",
            "voiceover": (
                "With the active memory pack, the local replay applies the current "
                "retry policy. The same fixture tests now pass three out of three. "
                "The lifecycle state changes what memory reaches the fresh agent "
                "before it reasons."
            ),
        },
        {
            "id": "qwen_boundary",
            "duration_seconds": 33,
            "image": media_root / "03-qwen-provider-evidence.png",
            "title": "Qwen Cloud is load-bearing",
            "caption": "Qwen text model, text-embedding-v4, and qwen3-rerank are separated from deterministic runtime work.",
            "voiceover": (
                "The intended Qwen Cloud path has three model roles. The Qwen text "
                "model handles memory decisions and supersession judgment in the "
                "provider path. "
                "text embedding v four retrieves active memory candidates, and "
                "qwen three rerank improves precision before deterministic code "
                "assembles the budgeted pack. The public demo remains credential-free "
                "and displays sanitized live trace evidence, including one stored "
                "provider-path trace that completed successfully once and a fresh "
                "M98 failed trace where lifecycle filtering still held."
            ),
        },
        {
            "id": "judge_path",
            "duration_seconds": 29,
            "image": media_root / "03-qwen-provider-evidence.png",
            "title": "Judge-run proof",
            "caption": "Public repo, fresh-clone smoke, Docker/ECS proof, and bounded local tests are ready.",
            "voiceover": (
                "The public repository is built from the sanitized bundle. Judges "
                "can run the fresh-clone smoke without credentials, and the Alibaba "
                "Cloud ECS endpoint runs the same credential-free demo surface. "
                "RecallPack prevents coding agents from acting on superseded "
                "project memory."
            ),
        },
    ]
    return {
        "title": "RecallPack Demo Video Candidate",
        "target_duration_seconds": TARGET_DURATION_SECONDS,
        "scenes": [
            {**scene, "image": scene["image"].relative_to(root).as_posix()}
            for scene in scenes
        ],
        "voiceover_text": "\n\n".join(scene["voiceover"] for scene in scenes),
        "truthfulness_boundary": [
            "Local demo is credential-free and uses deterministic fake providers.",
            "Stored live Qwen E2E trace is sanitized evidence; public demo does not call live Qwen.",
            "Fresh M98 live rerun is stored as live_e2e_failed and must not be claimed as passed.",
            "Stored live raw-history baseline traces selected active retry memory; the local stale failure is authored replay evidence.",
            "This file is a local video candidate, not a Devpost video URL or upload proof.",
        ],
    }


def build_demo_video_candidate(
    root: Path = SCRIPT_ROOT,
    output_dir: Path | None = None,
    *,
    dry_run: bool = False,
    voice: str = "Samantha",
) -> dict[str, Any]:
    root = root.resolve()
    output_dir = (root / (output_dir or DEFAULT_OUTPUT_DIR)).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    plan = build_video_plan(root)
    manifest_path = output_dir / "manifest.json"
    video_path = output_dir / DEFAULT_VIDEO_NAME
    voiceover_path = output_dir / "voiceover.txt"
    voiceover_path.write_text(plan["voiceover_text"] + "\n", encoding="utf-8")

    if dry_run:
        payload = {
            **plan,
            "status": "planned",
            "video_path": _display_path(video_path, root),
            "manifest_path": _display_path(manifest_path, root),
            "upload_performed": False,
        }
        manifest_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        return payload

    _require_command("ffmpeg")
    _require_command("ffprobe")
    _require_command("say")
    _require_pillow()

    with tempfile.TemporaryDirectory(prefix="recallpack-video-") as temp_dir:
        temp = Path(temp_dir)
        frame_paths = _render_scene_frames(root, plan, temp)
        concat_path = temp / "frames.txt"
        _write_concat_file(concat_path, frame_paths, plan)
        audio_path = temp / "voiceover.aiff"
        subprocess.run(
            ["say", "-v", voice, "-r", "185", "-o", str(audio_path), "-f", str(voiceover_path)],
            check=True,
        )
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(concat_path),
                "-i",
                str(audio_path),
                "-t",
                str(TARGET_DURATION_SECONDS),
                "-vf",
                "fps=30,format=yuv420p",
                "-af",
                "apad",
                "-shortest",
                "-c:v",
                "libx264",
                "-preset",
                "medium",
                "-crf",
                "22",
                "-c:a",
                "aac",
                "-b:a",
                "128k",
                "-movflags",
                "+faststart",
                str(video_path),
            ],
            check=True,
        )

    duration = _probe_duration(video_path)
    payload = {
        **plan,
        "status": "built",
        "video_path": _display_path(video_path, root),
        "manifest_path": _display_path(manifest_path, root),
        "duration_seconds": round(duration, 3),
        "upload_performed": False,
        "devpost_video_url": None,
        "voice": voice,
        "toolchain": {
            "ffmpeg": shutil.which("ffmpeg"),
            "ffprobe": shutil.which("ffprobe"),
            "say": shutil.which("say"),
        },
    }
    manifest_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    _write_readme(output_dir, payload)
    return payload


def _render_scene_frames(root: Path, plan: dict[str, Any], temp: Path) -> list[Path]:
    from PIL import Image, ImageDraw

    font_title = _font(46, bold=True)
    font_caption = _font(30, bold=False)
    font_meta = _font(22, bold=False)
    frame_paths: list[Path] = []
    for index, scene in enumerate(plan["scenes"], start=1):
        image_path = root / scene["image"]
        if not image_path.is_file():
            raise FileNotFoundError(f"missing scene screenshot: {scene['image']}")
        image = Image.open(image_path).convert("RGB").resize((1280, 720))
        overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        draw.rectangle((0, 0, 1280, 116), fill=(13, 18, 28, 224))
        draw.rectangle((0, 570, 1280, 720), fill=(13, 18, 28, 232))
        draw.text((42, 27), str(scene["title"]), font=font_title, fill=(248, 250, 252, 255))
        caption = _wrap(str(scene["caption"]), width=74)
        draw.multiline_text(
            (42, 596),
            caption,
            font=font_caption,
            fill=(226, 232, 240, 255),
            spacing=8,
        )
        meta = f"RecallPack demo candidate | scene {index}/{len(plan['scenes'])}"
        draw.text((960, 42), meta, font=font_meta, fill=(148, 163, 184, 255))
        composed = Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB")
        frame_path = temp / f"scene-{index:02d}.png"
        composed.save(frame_path)
        frame_paths.append(frame_path)
    return frame_paths


def _font(size: int, *, bold: bool) -> Any:
    from PIL import ImageFont

    candidates = [
        "/System/Library/Fonts/HelveticaNeue.ttc",
        "/System/Library/Fonts/SFNS.ttf",
        "/System/Library/Fonts/SFNSMono.ttf",
    ]
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size=size, index=1 if bold else 0)
        except Exception:
            continue
    return ImageFont.load_default()


def _write_concat_file(path: Path, frame_paths: list[Path], plan: dict[str, Any]) -> None:
    lines: list[str] = []
    for frame_path, scene in zip(frame_paths, plan["scenes"], strict=True):
        lines.append(f"file '{frame_path.as_posix()}'")
        lines.append(f"duration {scene['duration_seconds']}")
    lines.append(f"file '{frame_paths[-1].as_posix()}'")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _probe_duration(video_path: Path) -> float:
    completed = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(video_path),
        ],
        check=True,
        text=True,
        capture_output=True,
    )
    return float(completed.stdout.strip())


def _display_path(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _write_readme(output_dir: Path, payload: dict[str, Any]) -> None:
    lines = [
        "# RecallPack Demo Video Candidate",
        "",
        "This directory contains a locally generated MP4 candidate for manual",
        "review/upload. It is not proof of Devpost upload and is not a Devpost",
        "video URL.",
        "",
        f"- video: `{Path(payload['video_path']).name}`",
        f"- duration: {payload['duration_seconds']} seconds",
        "- upload_performed: false",
        "- public demo remains credential-free; it does not call live Qwen.",
        "- fresh M98 live rerun remains `live_e2e_failed` and is not claimed as passed.",
        "",
        "Regenerate from the repository root:",
        "",
        "```bash",
        "python3 tools/build_demo_video_candidate.py",
        "```",
        "",
    ]
    (output_dir / "README.md").write_text("\n".join(lines), encoding="utf-8")


def _wrap(text: str, width: int) -> str:
    return "\n".join(textwrap.wrap(text, width=width))


def _require_command(name: str) -> None:
    if shutil.which(name) is None:
        raise RuntimeError(f"required command not found: {name}")


def _require_pillow() -> None:
    try:
        import PIL  # noqa: F401
    except Exception as exc:
        raise RuntimeError("Pillow is required to render the video candidate frames") from exc


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build a local RecallPack demo video candidate without uploading it."
    )
    parser.add_argument("--root", default=str(SCRIPT_ROOT))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--voice", default="Samantha")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    payload = build_demo_video_candidate(
        Path(args.root),
        Path(args.output_dir),
        dry_run=args.dry_run,
        voice=args.voice,
    )
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
