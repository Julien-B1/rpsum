from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

from . import audio as au
from .providers import TranscribeOptions
from .schema import Transcript, to_markdown
from .tasks import resolve


def log_step(run: Path, record: dict) -> None:
    path = run / "run.json"
    log = json.loads(path.read_text()) if path.exists() else {"steps": []}
    log["steps"].append({"at": time.strftime("%Y-%m-%dT%H:%M:%S"), **record})
    path.write_text(json.dumps(log, ensure_ascii=False, indent=2))


def transcribe(run: Path, provider_name: str, model: str, opts: TranscribeOptions,
               start: float = 0.0, end: float | None = None, force: bool = False) -> Path:
    """Transcrit runs/<id>/audio.opus. Chaque couple fournisseur/modèle garde ses fichiers dans
    transcripts/<nom>/ ; le dernier lancé devient transcript.json à la racine du run."""
    provider = resolve("transcribe", provider_name, model)
    source = run / "audio.opus"
    partial = start > 0 or end is not None
    label = f"{provider_name}__{model}" + (f"__{int(start)}-{int(end or 0)}" if partial else "")
    label += (f"__spk{opts.num_speakers}" if opts.num_speakers else "") + ("__vocab" if opts.vocabulary else "")
    out = run / "transcripts" / label
    out.mkdir(parents=True, exist_ok=True)

    fresh = force or not (out / "transcript.json").exists()
    if fresh:
        audio = source
        if partial:
            audio = out / "extract.opus"
            au.cut(source, start, (end or au.duration(source)) - start, audio)
        opts.workdir = out / "work"
        if force:  # refaire pour de bon : on oublie les morceaux gardés
            shutil.rmtree(opts.workdir, ignore_errors=True)
        began = time.time()
        transcript, raws = provider.transcribe(audio, model, opts)
        elapsed = round(time.time() - began, 1)
        transcript.offset = start
        transcript.renumber()
        (out / "raw.json").write_text(json.dumps(raws, ensure_ascii=False))
        (out / "transcript.json").write_text(transcript.model_dump_json(indent=1, exclude_none=True))
        title = json.loads((run / "source.json").read_text()).get("title", run.name) if (run / "source.json").exists() else run.name
        (out / "transcript.md").write_text(to_markdown(transcript, title))
        log_step(run, {
            "step": "transcribe", "provider": provider_name, "model": model, "output": str(out.relative_to(run)),
            "audio_seconds": round(transcript.duration, 1), "elapsed_seconds": elapsed,
            "segments": len(transcript.segments), "speakers": len({s.speaker for s in transcript.segments}),
            "estimated_cost_usd": provider.stt_cost(model, transcript.duration),
        })

    # Le transcript courant du run n'est remplacé que par une transcription neuve, ou s'il manque :
    # relancer une transcription déjà faite ne doit pas effacer les annotations de `identify`.
    if not partial and (fresh or not (run / "transcript.json").exists()):
        for name in ("transcript.json", "transcript.md"):
            shutil.copy(out / name, run / name)
    return out


def load(path: Path) -> Transcript:
    return Transcript.model_validate_json(path.read_text())
