from __future__ import annotations

import shutil
from collections import Counter
from pathlib import Path
from typing import Optional

import typer

from . import config
from .providers import PROVIDERS, TranscribeOptions
from .tasks import TASKS, compatible

app = typer.Typer(no_args_is_help=True, add_completion=False, help="Résumé de parties de JDR enregistrées.")


@app.callback()
def main() -> None:
    app.cfg = config.load()  # type: ignore[attr-defined]


@app.command()
def doctor() -> None:
    """Vérifie les binaires, les clés et les serveurs."""
    for tool in ("ffmpeg", "ffprobe", "deno"):
        typer.echo(f"{'ok ' if shutil.which(tool) else 'KO '} {tool}")
    for name, cls in PROVIDERS.items():
        ok, why = cls().available()
        typer.echo(f"{'ok ' if ok else 'KO '} {name}{'' if ok else ' — ' + why}")


@app.command()
def models(task: Optional[str] = typer.Option(None, help=f"Filtre par tâche : {', '.join(TASKS)}")) -> None:
    """Liste les modèles disponibles, avec leurs capacités."""
    if task and task not in TASKS:
        raise SystemExit(f"Tâche inconnue : {task}. Choix : {', '.join(TASKS)}.")
    for name, cls in PROVIDERS.items():
        provider = cls()
        ok, why = provider.available()
        if not ok:
            typer.echo(f"# {name} : indisponible — {why}")
            continue
        found = provider.list_models()
        found = compatible(task, found) if task else found
        typer.echo(f"# {name} : {len(found)} modèle(s)")
        for model in found:
            typer.echo(f"  {model.id:42} {', '.join(sorted(model.caps))}")


@app.command()
def ingest(source: str, run_id: Optional[str] = typer.Option(None, "--id"), force: bool = False) -> None:
    """Télécharge et normalise l'audio d'une URL YouTube/Twitch ou d'un fichier local."""
    from .ingest import ingest as do_ingest
    run = do_ingest(source, run_id, force)
    typer.echo(f"Run prêt : {run.name} ({run / 'audio.opus'})")


@app.command()
def transcribe(
    run_id: str,
    provider: Optional[str] = typer.Option(None), model: Optional[str] = typer.Option(None),
    language: Optional[str] = typer.Option(None), speakers: Optional[int] = typer.Option(None, help="Nombre de locuteurs, si connu"),
    vocab: Optional[Path] = typer.Option(None, help="Fichier de noms propres, un par ligne"),
    start: float = typer.Option(0.0, help="Début de l'extrait, en secondes"),
    end: Optional[float] = typer.Option(None, help="Fin de l'extrait, en secondes"),
    force: bool = False,
) -> None:
    """Transcrit un run avec séparation des locuteurs."""
    from .transcribe import load, transcribe as do_transcribe
    cfg = app.cfg  # type: ignore[attr-defined]
    chosen_provider, chosen_model = config.task_choice(cfg, "transcribe", provider, model)
    settings = cfg.get("transcribe", {})
    opts = TranscribeOptions(
        language=language or settings.get("language", "fr"), num_speakers=speakers,
        vocabulary=[line.strip() for line in vocab.read_text().splitlines() if line.strip()] if vocab else [],
        chunk_seconds=float(settings.get("mistral_chunk_seconds", 1500)),
        progress=lambda message: typer.echo(message, err=True),
    )
    out = do_transcribe(config.run_dir(run_id), chosen_provider, chosen_model, opts, start, end, force)
    result = load(out / "transcript.json")
    talk: Counter[str] = Counter()
    for seg in result.segments:
        talk[seg.speaker] += seg.end - seg.start
    typer.echo(f"{out / 'transcript.md'}")
    typer.echo(f"{len(result.segments)} segments, {len(talk)} locuteurs : "
               + ", ".join(f"{name} {int(seconds // 60)} min" for name, seconds in talk.most_common()))


@app.command()
def identify(
    run_id: str,
    provider: Optional[str] = typer.Option(None), model: Optional[str] = typer.Option(None),
    cast_only: bool = typer.Option(False, help="S'arrête après la distribution, pour la relire"),
    redo_cast: bool = typer.Option(False, help="Recalcule cast.json même s'il existe"),
) -> None:
    """Propose la distribution (cast.json), puis annote chaque réplique : mode et personnage."""
    import json
    from . import identify as idf
    from .transcribe import load, log_step
    cfg = app.cfg  # type: ignore[attr-defined]
    chosen_provider, chosen_model = config.task_choice(cfg, "identify", provider, model)
    run = config.run_dir(run_id)
    transcript = load(run / "transcript.json")
    cast_path = run / "cast.json"
    if redo_cast or not cast_path.exists():
        cast = idf.propose_cast(run, transcript, chosen_provider, chosen_model)
        cast_path.write_text(json.dumps(cast, ensure_ascii=False, indent=2))
    cast = json.loads(cast_path.read_text())
    for entry in cast["speakers"]:
        played = f" joue {', '.join(entry['characters'])}" if entry["characters"] else ""
        typer.echo(f"{entry['speaker']:11} {entry['role']:7} {entry['player']}{played}  ({entry['confidence']:.2f}) {entry['evidence']}")
    if cast_only:
        typer.echo(f"Distribution à relire : {cast_path}. Relance sans --cast-only pour annoter.")
        return
    idf.apply_cast(transcript, cast)
    done = idf.annotate_lines(transcript, cast, chosen_provider, chosen_model,
                              progress=lambda message: typer.echo(message, err=True))
    (run / "transcript.json").write_text(transcript.model_dump_json(indent=1, exclude_none=True))
    title = json.loads((run / "source.json").read_text()).get("title", run_id)
    (run / "transcript.md").write_text(idf.to_script(transcript, title))
    log_step(run, {"step": "identify", "provider": chosen_provider, "model": chosen_model,
                   "annotated": done, "segments": len(transcript.segments)})
    typer.echo(f"{done} répliques annotées sur {len(transcript.segments)} : {run / 'transcript.md'}")


def _context(run_id: str):
    """Charge ce dont les étapes texte ont besoin : dossier, transcript, distribution, métadonnées."""
    import json
    from .transcribe import load
    run = config.run_dir(run_id)
    cast_path, source_path = run / "cast.json", run / "source.json"
    cast = json.loads(cast_path.read_text()) if cast_path.exists() else {"speakers": []}
    source = json.loads(source_path.read_text()) if source_path.exists() else {"title": run_id}
    return run, load(run / "transcript.json"), cast, source


def _progress(message: str) -> None:
    typer.echo(message, err=True)


@app.command()
def summarize(
    run_id: str,
    preset: Optional[str] = typer.Option(None, help="Préréglage de presets/*.toml"),
    tone: Optional[str] = typer.Option(None, help="Ton, en texte libre"),
    length: Optional[str] = typer.Option(None, help="court, moyen, long, ou un nombre de mots"),
    format: Optional[str] = typer.Option(None, help="recit, puces, fiche, article, discord"),
    pov: Optional[str] = typer.Option(None, help="Point de vue, en texte libre (par exemple : Hécate, à la première personne)"),
    scope: Optional[str] = typer.Option(None, help="en-jeu ou tout"),
    instructions: Optional[str] = typer.Option(None, help="Consigne supplémentaire"),
    name: Optional[str] = typer.Option(None, help="Nom du fichier de sortie : summary.<nom>.md"),
    provider: Optional[str] = typer.Option(None), model: Optional[str] = typer.Option(None),
    redo_scenes: bool = typer.Option(False, help="Recalcule les fiches de scène"),
) -> None:
    """Résume la session selon un ton, une longueur et un format."""
    from . import summarize as sm
    from .transcribe import log_step
    chosen_provider, chosen_model = config.task_choice(app.cfg, "summarize", provider, model)  # type: ignore[attr-defined]
    settings = sm.load_preset(preset, {"tone": tone, "length": length, "format": format, "pov": pov,
                                       "scope": scope, "instructions": instructions})
    run, transcript, cast, source = _context(run_id)
    scenes = sm.load_or_build_scenes(run, transcript, cast, chosen_provider, chosen_model, redo_scenes, _progress)
    text = sm.write_summary(scenes, cast, source["title"], settings, chosen_provider, chosen_model, transcript)
    left = sm.unverified_quotes(text, transcript)
    if left:
        typer.echo(f"Attention : {len(left)} réplique(s) entre guillemets introuvable(s) dans le transcript : "
                   + " | ".join(left), err=True)
    out = run / f"summary.{name or preset or 'defaut'}.md"
    out.write_text(text + "\n")
    log_step(run, {"step": "summarize", "provider": chosen_provider, "model": chosen_model, "output": out.name,
                   "scenes": len(scenes), "words": len(text.split()),
                   "unverified_quotes": len(left),
                   "settings": {k: settings[k] for k in ("tone", "words", "format", "pov", "scope")}})
    typer.echo(f"{out} ({len(text.split())} mots, {len(scenes)} scènes)")


@app.command()
def extract(
    run_id: str,
    provider: Optional[str] = typer.Option(None), model: Optional[str] = typer.Option(None),
    clips: bool = typer.Option(False, help="Découpe l'audio des passages notés 8 et plus"),
    force: bool = False,
) -> None:
    """Extrait moments forts, bêtisier et mèmes, avec citations vérifiées."""
    import json
    from collections import Counter
    from . import extract as ex
    from .transcribe import log_step
    chosen_provider, chosen_model = config.task_choice(app.cfg, "extract", provider, model)  # type: ignore[attr-defined]
    run, transcript, cast, source = _context(run_id)
    path = run / "highlights.json"
    if force or not path.exists():
        items, rejected = ex.extract(transcript, cast, chosen_provider, chosen_model, source.get("url"),
                                     progress=_progress)
        log_step(run, {"step": "extract", "provider": chosen_provider, "model": chosen_model,
                       "kept": len(items), "rejected": rejected})
        typer.echo(f"{len(items)} passages retenus, {rejected} rejetés (citation introuvable ou bornes fausses)")
    else:
        items = json.loads(path.read_text())["items"]
    if clips:
        typer.echo(f"{ex.cut_clips(run, items, transcript.offset)} extraits audio dans {run / 'clips'}")
    path.write_text(json.dumps({"items": items}, ensure_ascii=False, indent=1))
    (run / "highlights.md").write_text(ex.to_markdown(items, source["title"]))
    counts = Counter(item["category"] for item in items)
    typer.echo(f"{run / 'highlights.md'} — " + ", ".join(f"{ex.CATEGORIES[c]} : {n}" for c, n in counts.items()))


if __name__ == "__main__":
    app()
