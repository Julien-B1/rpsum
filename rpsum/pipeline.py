"""Étapes du pipeline, partagées par les commandes unitaires et par `rpsum run`.

Règle de reprise : une étape dont le résultat existe n'est pas refaite, sauf si on la force. Refaire une étape
efface les résultats des étapes qui en dépendent."""
from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from pathlib import Path

from . import config
from . import context as ctx
from .providers import TranscribeOptions
from .schema import Transcript
from .transcribe import load, log_step

STEPS = ["context", "transcribe", "identify", "summarize", "extract"]
# Fichiers à effacer quand une étape est refaite : tout ce que les étapes suivantes en ont tiré.
DOWNSTREAM = {
    "transcribe": ["cast.json", "scenes.json", "highlights.json", "highlights.md"],
    "identify": ["scenes.json", "highlights.json", "highlights.md"],
}
Say = Callable[[str], None]


def _source(run: Path) -> dict:
    path = run / "source.json"
    return json.loads(path.read_text()) if path.exists() else {"title": run.name}


def _cast(run: Path) -> dict:
    path = run / "cast.json"
    return json.loads(path.read_text()) if path.exists() else {"speakers": []}


def _invalidate(run: Path, step: str) -> None:
    for name in DOWNSTREAM.get(step, []):
        (run / name).unlink(missing_ok=True)


def is_annotated(t: Transcript) -> bool:
    return any(seg.mode for seg in t.segments)


def step_context(run: Path, cfg: dict, context_file: Path | None, force: bool, say: Say,
                 provider: str | None = None, model: str | None = None) -> dict | None:
    """Construit runs/<id>/context.json à partir du fichier de contexte, de la description de la vidéo et des
    incrustations lues à l'écran. Refait seulement si ces entrées ont changé."""
    from . import vision
    if context_file:
        if not context_file.is_file():
            raise SystemExit(f"Fichier de contexte introuvable : {context_file}")
        shutil.copy(context_file, run / "context.input.md")
        (run / "context.base").write_text(str(context_file.resolve().parent))
    raw_path = run / "context.input.md"
    raw = raw_path.read_text() if raw_path.exists() else ""
    base = Path((run / "context.base").read_text()) if (run / "context.base").exists() else run
    source = _source(run)

    extra: dict[str, str] = {}
    if source.get("title") or source.get("description"):
        extra["Titre et description de la vidéo"] = f"{source.get('title', '')}\n{source.get('description', '')}".strip()

    vision_provider, vision_model = config.task_choice(cfg, "vision", None, None)
    overlay_path = run / "overlay.json"
    if (force or not overlay_path.exists()) and source.get("source"):
        start = float(source.get("start") or 0)
        try:  # la lecture de l'écran est un plus : son échec ne doit pas arrêter le run
            frames = vision.capture_frames(source["source"], [start + 5, start + 25, start + 50], run / "frames")
            if frames:
                overlay = vision.read_overlay(frames, vision_provider, vision_model)
                overlay_path.write_text(json.dumps(overlay, ensure_ascii=False, indent=2))
                say(f"Écran lu sur {len(frames)} image(s) : {len(overlay['people'])} participant(s) relevé(s)")
        except Exception as exc:
            say(f"Lecture de l'écran impossible ({type(exc).__name__} : {str(exc)[:120]}). On continue sans.")
    if overlay_path.exists():
        overlay = json.loads(overlay_path.read_text())
        lines = [f"Titre affiché : {overlay['title']}"] if overlay.get("title") else []
        lines += [f"- {p['name']} : {p['role']}" + (f", joue {p['character']}" if p.get("character") else "")
                  for p in overlay.get("people", [])]
        lines += [f"Autre texte : {text}" for text in overlay.get("other_text", [])]
        extra["Texte relevé à l'écran en début de vidéo (pseudos et personnages affichés près des webcams)"] = "\n".join(lines)

    if not raw and not extra:
        say("Contexte : rien à analyser.")
        return ctx.load(run)
    mark = ctx.fingerprint(raw, extra)
    current = ctx.load(run)
    if current and current.get("fingerprint") == mark and not force:
        say("Contexte : déjà à jour.")
        return current

    chosen_provider, chosen_model = config.task_choice(cfg, "context", provider, model)

    def read_images(images: list[Path]) -> str:
        return json.dumps(vision.read_overlay(images, vision_provider, vision_model), ensure_ascii=False)

    built = ctx.build(raw, base, extra, chosen_provider, chosen_model, read_images=read_images, progress=say)
    built["fingerprint"] = mark
    (run / "context.json").write_text(json.dumps(built, ensure_ascii=False, indent=2))
    (run / "context.md").write_text(ctx.to_markdown(built))
    log_step(run, {"step": "context", "provider": chosen_provider, "model": chosen_model,
                   "names": len(ctx.vocabulary(built, 10_000)), "people": len(built["people"]),
                   "sources": built["sources"]})
    failed = [s for s in built["sources"] if s["status"].startswith("échec")]
    say(f"Contexte : {len(built['people'])} participant(s), {len(ctx.vocabulary(built, 10_000))} noms"
        + (f", {len(failed)} source(s) en échec : " + " ; ".join(f"{s['ref']} ({s['status']})" for s in failed) if failed else ""))
    return built


def step_transcribe(run: Path, cfg: dict, force: bool, say: Say, provider: str | None = None,
                    model: str | None = None, speakers: int | None = None, vocab: list[str] | None = None,
                    language: str | None = None, start: float = 0.0, end: float | None = None) -> Path | None:
    """Transcrit, sauf si runs/<id>/transcript.json existe déjà. Renvoie le dossier de sortie, ou None si rien n'a été fait."""
    from .transcribe import transcribe
    partial = start > 0 or end is not None
    if (run / "transcript.json").exists() and not force and not partial and not (provider or model):
        say("Transcription : déjà présente, non refaite (--force pour la refaire).")
        return None
    chosen_provider, chosen_model = config.task_choice(cfg, "transcribe", provider, model)
    settings = cfg.get("transcribe", {})
    context = ctx.load(run)
    if vocab is None and context:
        vocab = ctx.vocabulary(context)
    if speakers is None and context and context.get("people"):
        speakers = len(context["people"])
    opts = TranscribeOptions(
        language=language or settings.get("language", "fr"), num_speakers=speakers, vocabulary=vocab or [],
        chunk_seconds=float(settings.get("mistral_chunk_seconds", 1500)), progress=say)
    out = transcribe(run, chosen_provider, chosen_model, opts, start, end, force)
    if not partial:
        # Une transcription demandée explicitement devient le transcript courant et périme la suite.
        for name in ("transcript.json", "transcript.md"):
            shutil.copy(out / name, run / name)
        _invalidate(run, "transcribe")
    return out


def step_identify(run: Path, cfg: dict, force: bool, say: Say, provider: str | None = None,
                  model: str | None = None, cast_only: bool = False, redo_cast: bool = False,
                  reannotate: bool = False) -> dict:
    """`force` ou `redo_cast` recalculent la distribution. `reannotate` garde cast.json (corrigé à la main ou
    non) et refait l'annotation des répliques. Sans rien de tout cela, une identification déjà faite est gardée."""
    from . import identify as idf
    transcript = load(run / "transcript.json")
    cast_path = run / "cast.json"
    if is_annotated(transcript) and cast_path.exists() and not (force or redo_cast or cast_only or reannotate):
        say("Identification : déjà faite, non refaite.")
        return json.loads(cast_path.read_text())
    chosen_provider, chosen_model = config.task_choice(cfg, "identify", provider, model)
    context = ctx.load(run)
    if context:  # orthographe officielle des noms connus, avant toute analyse
        names, fixed = ctx.vocabulary(context, 10_000), 0
        for seg in transcript.segments:
            seg.text, n = ctx.fix_names(seg.text, names)
            fixed += n
        if fixed:
            say(f"Identification : {fixed} nom(s) ramené(s) à l'orthographe de la fiche de contexte")
    if force or redo_cast or not cast_path.exists():
        cast = idf.propose_cast(run, transcript, chosen_provider, chosen_model)
        cast_path.write_text(json.dumps(cast, ensure_ascii=False, indent=2))
    cast = json.loads(cast_path.read_text())
    if cast_only:
        return cast
    idf.apply_cast(transcript, cast)
    done = idf.annotate_lines(transcript, cast, chosen_provider, chosen_model, progress=say,
                              campaign=ctx.prompt_block(ctx.load(run)))
    (run / "transcript.json").write_text(transcript.model_dump_json(indent=1, exclude_none=True))
    (run / "transcript.md").write_text(idf.to_script(transcript, _source(run).get("title", run.name)))
    _invalidate(run, "identify")
    log_step(run, {"step": "identify", "provider": chosen_provider, "model": chosen_model,
                   "annotated": done, "segments": len(transcript.segments)})
    say(f"Identification : {done} répliques annotées sur {len(transcript.segments)}")
    return cast


def step_summarize(run: Path, cfg: dict, settings: dict, name: str, say: Say, provider: str | None = None,
                   model: str | None = None, redo_scenes: bool = False) -> Path:
    from . import summarize as sm
    chosen_provider, chosen_model = config.task_choice(cfg, "summarize", provider, model)
    transcript, cast, campaign = load(run / "transcript.json"), _cast(run), ctx.prompt_block(ctx.load(run))
    scenes = sm.load_or_build_scenes(run, transcript, cast, chosen_provider, chosen_model, redo_scenes, say, campaign)
    text = sm.write_summary(scenes, cast, _source(run).get("title", run.name), settings, chosen_provider,
                            chosen_model, transcript, campaign)
    left = sm.unverified_quotes(text, transcript)
    if left:
        say(f"Attention : {len(left)} réplique(s) entre guillemets introuvable(s) dans le transcript : " + " | ".join(left))
    out = run / f"summary.{name}.md"
    out.write_text(text + "\n")
    log_step(run, {"step": "summarize", "provider": chosen_provider, "model": chosen_model, "output": out.name,
                   "scenes": len(scenes), "words": len(text.split()), "unverified_quotes": len(left),
                   "settings": {k: settings[k] for k in ("tone", "words", "format", "pov", "scope")}})
    say(f"Résumé : {out} ({len(text.split())} mots, {len(scenes)} scènes)")
    return out


def step_extract(run: Path, cfg: dict, force: bool, clips: bool, say: Say, provider: str | None = None,
                 model: str | None = None) -> list[dict]:
    from . import extract as ex
    transcript, source = load(run / "transcript.json"), _source(run)
    path = run / "highlights.json"
    if force or not path.exists():
        chosen_provider, chosen_model = config.task_choice(cfg, "extract", provider, model)
        items, rejected = ex.extract(transcript, _cast(run), chosen_provider, chosen_model, source.get("url"),
                                     progress=say, campaign=ctx.prompt_block(ctx.load(run)))
        log_step(run, {"step": "extract", "provider": chosen_provider, "model": chosen_model,
                       "kept": len(items), "rejected": rejected})
        say(f"Extraction : {len(items)} passages retenus, {rejected} rejetés (citation introuvable ou bornes fausses)")
    else:
        items = json.loads(path.read_text())["items"]
    if clips:
        shutil.rmtree(run / "clips", ignore_errors=True)
        say(f"Extraction : {ex.cut_clips(run, items, transcript.offset)} extraits audio dans {run / 'clips'}")
    path.write_text(json.dumps({"items": items}, ensure_ascii=False, indent=1))
    (run / "highlights.md").write_text(ex.to_markdown(items, source.get("title", run.name)))
    return items


def run_all(source: str, cfg: dict, say: Say, run_id: str | None = None, context_file: Path | None = None,
            presets: list[str] | None = None, speakers: int | None = None, force: bool = False,
            redo_from: str | None = None) -> Path:
    """Pipeline complet. Reprise : l'audio, le contexte, la transcription et l'identification déjà présents sont
    gardés ; les résumés et l'extraction sont refaits à chaque lancement. `force` refait tout depuis la
    transcription. `redo_from` refait à partir d'une étape donnée."""
    from . import summarize as sm
    from .ingest import ingest
    if redo_from and redo_from not in STEPS:
        raise SystemExit(f"Étape inconnue : {redo_from}. Choix : {', '.join(STEPS)}.")
    first = STEPS.index(redo_from) if redo_from else (STEPS.index("transcribe") if force else len(STEPS))
    redo = {step: STEPS.index(step) >= first for step in STEPS}

    existing = config.RUNS / source
    if existing.is_dir() and (existing / "audio.opus").exists():
        run = existing
        say(f"Run existant : {run.name}")
    else:
        run = ingest(source, run_id)
        say(f"Audio prêt : {run / 'audio.opus'}")
    step_context(run, cfg, context_file, redo["context"], say)
    step_transcribe(run, cfg, redo["transcribe"], say, speakers=speakers)
    step_identify(run, cfg, redo["identify"] or redo["transcribe"], say)
    settings_run = cfg.get("run", {})
    for index, preset in enumerate(presets or settings_run.get("presets", ["fiche"])):
        step_summarize(run, cfg, sm.load_preset(preset, {}), preset, say,
                       redo_scenes=index == 0 and (redo["summarize"] or not (run / "scenes.json").exists()))
    step_extract(run, cfg, True, bool(settings_run.get("clips", True)), say)
    return run
