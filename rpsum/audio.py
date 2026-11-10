from __future__ import annotations

import re
import subprocess
from pathlib import Path


def _run(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True, check=True)


def duration(path: Path) -> float:
    out = _run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)])
    return float(out.stdout.strip())


def normalize(src: Path, dst: Path) -> None:
    """Opus mono 16 kHz : environ 11 Mo par heure."""
    _run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-vn", "-ac", "1", "-ar", "16000",
          "-c:a", "libopus", "-b:a", "24k", str(dst)])


def cut(src: Path, start: float, length: float, dst: Path) -> None:
    """Découpe en réencodant (coupe exacte). Le codec suit l'extension de `dst`."""
    codec = {".opus": ["-c:a", "libopus", "-b:a", "24k"], ".flac": ["-c:a", "flac"]}.get(dst.suffix, [])
    _run(["ffmpeg", "-v", "error", "-y", "-ss", f"{start:.3f}", "-t", f"{length:.3f}", "-i", str(src),
          "-ac", "1", "-ar", "16000", *codec, str(dst)])


def silences(path: Path, noise_db: int = -35, min_len: float = 0.6) -> list[tuple[float, float]]:
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-i", str(path), "-af", f"silencedetect=noise={noise_db}dB:d={min_len}",
         "-f", "null", "-"], capture_output=True, text=True)
    starts = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", proc.stderr)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", proc.stderr)]
    return list(zip(starts, ends))


def plan_chunks(total: float, quiet: list[tuple[float, float]], target: float, window: float = 120.0
                ) -> list[tuple[float, float]]:
    """Découpe [0, total] en morceaux d'environ `target` secondes, coupés au milieu d'un silence
    situé à moins de `window` secondes de la cible. Sans silence proche, coupe à la cible."""
    chunks, start = [], 0.0
    mids = [(a + b) / 2 for a, b in quiet]
    while total - start > target * 1.2:
        goal = start + target
        near = [m for m in mids if abs(m - goal) <= window]
        end = min(near, key=lambda m: abs(m - goal)) if near else goal
        chunks.append((start, end))
        start = end
    chunks.append((start, total))
    return chunks
