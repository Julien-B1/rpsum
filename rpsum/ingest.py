from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from . import audio as au
from .config import RUNS
from .vision import url_start


def ingest(source: str, run_id: str | None = None, force: bool = False) -> Path:
    """Télécharge l'audio d'une URL (ou copie un fichier local) et le normalise dans runs/<id>/audio.opus."""
    local = Path(source)
    if local.is_file():
        info = {"id": local.stem, "title": local.stem, "extractor": "fichier", "webpage_url": str(local.resolve())}
    else:
        from yt_dlp import YoutubeDL
        with YoutubeDL({"quiet": True, "no_warnings": True}) as ydl:
            info = ydl.extract_info(source, download=False)
    run_id = run_id or re.sub(r"[^\w-]+", "-", f"{info.get('extractor', 'src')}-{info['id']}").lower()
    run = RUNS / run_id
    run.mkdir(parents=True, exist_ok=True)
    target = run / "audio.opus"

    if force or not target.exists():
        if local.is_file():
            raw = run / f"source{local.suffix}"
            shutil.copy(local, raw)
        else:
            existing = [p for p in run.glob("source.*") if p.suffix != ".json"]
            if existing and not force:
                raw = existing[0]
            else:
                # Audio seul. « Audio_Only » est le nom du format audio chez Twitch.
                opts = {"quiet": True, "no_warnings": True, "noprogress": True, "format": "bestaudio/Audio_Only/worst",
                        "outtmpl": str(run / "source.%(ext)s"), "concurrent_fragment_downloads": 8}
                with YoutubeDL(opts) as ydl:
                    done = ydl.extract_info(source, download=True)
                    raw = Path(ydl.prepare_filename(done))
        au.normalize(raw, target)

    meta = {
        "run_id": run_id, "url": info.get("webpage_url", source), "title": info.get("title"),
        "channel": info.get("channel") or info.get("uploader"), "extractor": info.get("extractor"),
        "upload_date": info.get("upload_date"), "language": info.get("language"),
        "duration": au.duration(target),
        "description": info.get("description") or "",
        "source": source if not local.is_file() else str(local.resolve()),
        "start": url_start(source),  # position de départ portée par l'URL (t=…)
        "chapters": [{"start": c["start_time"], "end": c["end_time"], "title": c["title"]}
                     for c in info.get("chapters") or []],
    }
    (run / "source.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2))
    return run
