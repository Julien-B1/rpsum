from __future__ import annotations

import shutil
from collections import Counter
from pathlib import Path
from typing import Optional

import typer

from . import config
from .providers import PROVIDERS
from .tasks import TASKS, compatible

app = typer.Typer(no_args_is_help=True, add_completion=False, help="Résumé de parties de JDR enregistrées.")


@app.callback()
def main() -> None:
    app.cfg = config.load()  # type: ignore[attr-defined]


def _cfg() -> dict:
    return app.cfg  # type: ignore[attr-defined]


def say(message: str) -> None:
    typer.echo(message, err=True)


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
def run(
    source: str = typer.Argument(..., help="URL YouTube ou Twitch, fichier local, ou identifiant d'un run existant"),
    run_id: Optional[str] = typer.Option(None, "--id", help="Identifiant du run à créer"),
    context: Optional[Path] = typer.Option(None, help="Fichier Markdown de contexte de campagne"),
    preset: Optional[list[str]] = typer.Option(None, help="Préréglage de résumé, répétable. Défaut : config.toml"),
    speakers: Optional[int] = typer.Option(None, help="Nombre de personnes à table, si connu"),
    force: bool = typer.Option(False, help="Refait tout depuis la transcription"),
    redo_from: Optional[str] = typer.Option(None, "--from", help="Refait à partir d'une étape : context, transcribe, identify, summarize"),
) -> None:
    """Pipeline complet. Relancé sur un run existant, il garde transcription et identification, et refait résumés et extraction."""
    from . import pipeline
    done = pipeline.run_all(source, _cfg(), say, run_id, context, preset, speakers, force, redo_from)
    typer.echo(f"Terminé : {done}")
    for path in sorted(done.glob("summary.*.md")) + [done / "highlights.md", done / "transcript.md"]:
        typer.echo(f"  {path}")


@app.command()
def ingest(source: str, run_id: Optional[str] = typer.Option(None, "--id"), force: bool = False) -> None:
    """Télécharge et normalise l'audio d'une URL YouTube/Twitch ou d'un fichier local."""
    from .ingest import ingest as do_ingest
    done = do_ingest(source, run_id, force)
    typer.echo(f"Run prêt : {done.name} ({done / 'audio.opus'})")


@app.command()
def context(
    run_id: str,
    file: Optional[Path] = typer.Argument(None, help="Fichier Markdown de contexte. Omis : réutilise le précédent."),
    provider: Optional[str] = typer.Option(None), model: Optional[str] = typer.Option(None),
    force: bool = False,
) -> None:
    """Construit la fiche de contexte : noms, lieux, participants. Lit aussi l'écran de la vidéo."""
    from . import pipeline
    done = config.run_dir(run_id)
    pipeline.step_context(done, _cfg(), file, force, say, provider, model)
    if (done / "context.md").exists():
        typer.echo(f"{done / 'context.md'}")


@app.command()
def transcribe(
    run_id: str,
    provider: Optional[str] = typer.Option(None), model: Optional[str] = typer.Option(None),
    language: Optional[str] = typer.Option(None),
    speakers: Optional[int] = typer.Option(None, help="Nombre de locuteurs, si connu"),
    vocab: Optional[Path] = typer.Option(None, help="Fichier de noms propres, un par ligne. Défaut : la fiche de contexte"),
    start: float = typer.Option(0.0, help="Début de l'extrait, en secondes"),
    end: Optional[float] = typer.Option(None, help="Fin de l'extrait, en secondes"),
    force: bool = False,
) -> None:
    """Transcrit un run avec séparation des locuteurs."""
    from . import pipeline
    from .transcribe import load
    words = [line.strip() for line in vocab.read_text().splitlines() if line.strip()] if vocab else None
    done = config.run_dir(run_id)
    out = pipeline.step_transcribe(done, _cfg(), force, say, provider, model, speakers, words, language, start, end)
    result = load((out or done) / "transcript.json")
    talk: Counter[str] = Counter()
    for seg in result.segments:
        talk[seg.player or seg.speaker] += seg.end - seg.start
    typer.echo(f"{(out or done) / 'transcript.md'}")
    typer.echo(f"{len(result.segments)} segments, {len(talk)} locuteurs : "
               + ", ".join(f"{name} {int(seconds // 60)} min" for name, seconds in talk.most_common()))


@app.command()
def identify(
    run_id: str,
    provider: Optional[str] = typer.Option(None), model: Optional[str] = typer.Option(None),
    cast_only: bool = typer.Option(False, help="S'arrête après la distribution, pour la relire"),
    redo_cast: bool = typer.Option(False, help="Recalcule cast.json même s'il existe"),
    force: bool = typer.Option(False, help="Refait distribution et annotation"),
) -> None:
    """Propose la distribution (cast.json), puis annote chaque réplique : mode et personnage."""
    from . import pipeline
    done = config.run_dir(run_id)
    # Lancée seule, la commande réannote toujours : c'est ce qu'on veut après avoir corrigé cast.json.
    cast = pipeline.step_identify(done, _cfg(), force, say, provider, model, cast_only, redo_cast, reannotate=True)
    for entry in cast["speakers"]:
        played = f" joue {', '.join(entry['characters'])}" if entry["characters"] else ""
        typer.echo(f"{entry['speaker']:11} {entry['role']:7} {entry['player']}{played}  ({entry['confidence']:.2f}) {entry['evidence']}")
    typer.echo(f"Distribution à relire : {done / 'cast.json'}." if cast_only else f"{done / 'transcript.md'}")


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
    from . import pipeline
    from . import summarize as sm
    settings = sm.load_preset(preset, {"tone": tone, "length": length, "format": format, "pov": pov,
                                       "scope": scope, "instructions": instructions})
    out = pipeline.step_summarize(config.run_dir(run_id), _cfg(), settings, name or preset or "defaut", say,
                                  provider, model, redo_scenes)
    typer.echo(str(out))


@app.command()
def extract(
    run_id: str,
    provider: Optional[str] = typer.Option(None), model: Optional[str] = typer.Option(None),
    clips: bool = typer.Option(False, help="Découpe l'audio des passages notés 8 et plus"),
    force: bool = False,
) -> None:
    """Extrait moments forts, bêtisier et mèmes, avec citations vérifiées."""
    from . import extract as ex
    from . import pipeline
    done = config.run_dir(run_id)
    items = pipeline.step_extract(done, _cfg(), force, clips, say, provider, model)
    counts = Counter(item["category"] for item in items)
    typer.echo(f"{done / 'highlights.md'} — " + ", ".join(f"{ex.CATEGORIES[c]} : {n}" for c, n in counts.items()))


if __name__ == "__main__":
    app()
