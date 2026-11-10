"""Étape `summarize` : fiches de scène factuelles (map), puis rédaction selon le ton, la longueur et le format (reduce)."""
from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

from . import llm
from .config import ROOT
from .schema import Transcript, timestamp
from .tasks import resolve

STR_LIST = {"type": "array", "items": {"type": "string"}}
SCENES_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["scenes"],
    "properties": {"scenes": {"type": "array", "items": {
        "type": "object", "additionalProperties": False,
        "required": ["title", "start_id", "end_id", "summary", "characters", "npcs", "places", "items",
                     "decisions", "rolls", "off_game"],
        "properties": {
            "title": {"type": "string"}, "start_id": {"type": "integer"}, "end_id": {"type": "integer"},
            "summary": {"type": "string"},
            "characters": STR_LIST, "npcs": STR_LIST, "places": STR_LIST, "items": STR_LIST,
            "decisions": STR_LIST, "rolls": STR_LIST, "off_game": STR_LIST,
        }}}},
}

MAP_PROMPT = """Tu lis un passage du transcript d'une partie de jeu de rôle sur table. Distribution :
{cast}

Découpe ce passage en scènes (changement de lieu, d'objectif ou de situation) et rédige une fiche par scène :
- title : titre court.
- start_id, end_id : numéros de la première et de la dernière réplique de la scène.
- summary : ce qui se passe dans la fiction, en 3 à 8 phrases factuelles, au présent. Nomme qui fait quoi.
- characters : personnages joueurs actifs. npcs : PNJ présents ou évoqués, avec leur rôle en quelques mots.
- places, items : lieux et objets importants.
- decisions : choix faits par les personnages, et pistes ouvertes.
- rolls : jets de dés marquants et leur résultat (réussite, échec, critique).
- off_game : moments hors jeu notables (fou rire, blague récurrente, incident technique). Liste vide sinon.

Règles : n'écris que ce qui figure dans le transcript. Les répliques « hors-jeu » ne font pas partie de la fiction.
Dans summary, characters, npcs et decisions, n'emploie que des noms de personnages : jamais le pseudo d'un joueur
ni celui du MJ. Une réplique « Joueur / Personnage » se rapporte au personnage.
Le transcript est automatique : un nom mal orthographié se corrige d'après la distribution.
Les scènes doivent couvrir tout le passage, dans l'ordre."""

REDUCE_PROMPT = """Tu rédiges le résumé d'une partie de jeu de rôle sur table à partir de fiches de scène.
Titre de la session : {title}
Distribution :
{cast}

Consignes de rédaction :
- Ton : {tone}
- Longueur : {words} mots au maximum. C'est une limite stricte : choisis les faits qui comptent le plus.
- Format : {format}
- Point de vue : {pov}
- Périmètre : {scope}
- Langue : français.
{instructions}
Les pseudos des joueurs et du MJ désignent des personnes réelles : ils n'apparaissent dans le résumé que si le
périmètre inclut l'ambiance de la table.
Règle absolue : chaque fait du résumé doit venir des fiches. N'invente ni événement, ni nom, ni dialogue.
N'écris aucune réplique entre guillemets : les fiches ne contiennent pas les paroles exactes. Rapporte les paroles au style indirect.
Le ton change la manière de raconter, jamais les faits. Rends directement le résumé, sans préambule."""

LENGTHS = {"court": 150, "moyen": 400, "long": 900}
FORMATS = {
    "recit": "récit continu en paragraphes.",
    "puces": "liste à puces chronologique, une puce par événement important.",
    "fiche": "fiche de campagne en Markdown avec les sections : Résumé, Personnages joueurs, PNJ rencontrés, "
             "Lieux, Objets, Décisions prises, Pistes ouvertes.",
    "article": "article de gazette avec un titre accrocheur, un chapeau et des intertitres.",
    "discord": "message Discord de moins de 1800 caractères, avec un titre en gras et quelques émojis.",
}
SCOPES = {
    "en-jeu": "la fiction seulement. Ignore les moments hors jeu.",
    "tout": "la fiction, plus une courte section finale sur l'ambiance à la table (moments hors jeu notables).",
}
DEFAULTS = {"tone": "neutre et clair", "length": "moyen", "format": "recit", "pov": "narrateur extérieur",
            "scope": "en-jeu", "instructions": ""}


def cast_text(cast: dict) -> str:
    people: dict[str, dict] = {}
    for entry in cast.get("speakers", []):
        if entry["role"] == "autre":
            continue
        people.setdefault(entry["player"], {"role": entry["role"], "characters": []})["characters"] += entry["characters"]
    lines = []
    for name, info in people.items():
        if info["role"] == "mj":
            # Le pseudo du MJ n'est pas donné : le modèle s'en servirait pour nommer un PNJ sans nom.
            lines.append("- MJ : maître du jeu. Personne réelle, absente de la fiction. Il fait parler les PNJ, "
                         "indiqués après la barre oblique. Un « PNJ non nommé » se désigne par sa fonction.")
        else:
            played = ", ".join(dict.fromkeys(info["characters"])) or "personnage inconnu"
            lines.append(f"- {name} : joueur, personne réelle. Son personnage dans la fiction : {played}.")
    return "\n".join(lines) or "(inconnue)"


def load_preset(name: str | None, overrides: dict) -> dict:
    settings = dict(DEFAULTS)
    if name:
        path = ROOT / "presets" / f"{name}.toml"
        if not path.exists():
            known = ", ".join(sorted(p.stem for p in (ROOT / "presets").glob("*.toml")))
            raise SystemExit(f"Préréglage inconnu : {name}. Disponibles : {known}.")
        settings.update(tomllib.loads(path.read_text()))
    settings.update({key: value for key, value in overrides.items() if value is not None})
    if settings["format"] not in FORMATS:
        raise SystemExit(f"Format inconnu : {settings['format']}. Choix : {', '.join(FORMATS)}.")
    if settings["scope"] not in SCOPES:
        raise SystemExit(f"Périmètre inconnu : {settings['scope']}. Choix : {', '.join(SCOPES)}.")
    length = str(settings["length"])
    if length not in LENGTHS and not length.isdigit():
        raise SystemExit(f"Longueur inconnue : {length}. Choix : {', '.join(LENGTHS)}, ou un nombre de mots.")
    settings["words"] = LENGTHS.get(length) or int(length)
    return settings


def build_scenes(t: Transcript, cast: dict, provider_name: str, model: str, window: int = 220,
                 progress=lambda message: None, campaign: str = "") -> list[dict]:
    provider = resolve("summarize", provider_name, model)
    system = MAP_PROMPT.format(cast=cast_text(cast)) + ("\n\n" + campaign if campaign else "")

    def work(segments) -> list[dict]:
        text = "\n".join(llm.line(s, t.offset) for s in segments)
        scenes = llm.chat_json(provider, model, system, text, SCENES_SCHEMA)["scenes"]
        first, last = segments[0].id, segments[-1].id
        for scene in scenes:  # bornes ramenées dans la fenêtre
            scene["start_id"] = min(max(scene["start_id"], first), last)
            scene["end_id"] = min(max(scene["end_id"], scene["start_id"]), last)
            scene["start"] = t.segments[scene["start_id"]].start + t.offset
            scene["end"] = t.segments[scene["end_id"]].end + t.offset
        return scenes

    batches = llm.parallel(work, llm.windows(t, window), progress=progress, label="summarize (scènes)")
    return [scene for batch in batches for scene in batch]


def scenes_text(scenes: list[dict], scope: str) -> str:
    blocks = []
    for index, scene in enumerate(scenes, 1):
        block = [f"## Scène {index} — {scene['title']} [{timestamp(scene['start'])}–{timestamp(scene['end'])}]",
                 scene["summary"]]
        labels = {"characters": "Personnages", "npcs": "PNJ", "places": "Lieux", "items": "Objets",
                  "decisions": "Décisions et pistes", "rolls": "Jets"}
        if scope == "tout":
            labels["off_game"] = "Hors jeu"
        block += [f"{label} : {' ; '.join(scene[key])}" for key, label in labels.items() if scene.get(key)]
        blocks.append("\n".join(block))
    return "\n\n".join(blocks)


def write_summary(scenes: list[dict], cast: dict, title: str, settings: dict, provider_name: str, model: str,
                  transcript: Transcript | None = None, campaign: str = "") -> str:
    provider = resolve("summarize", provider_name, model)
    instructions = f"- Consigne supplémentaire : {settings['instructions']}\n" if settings["instructions"] else ""
    system = REDUCE_PROMPT.format(
        title=title, cast=cast_text(cast), tone=settings["tone"], words=settings["words"],
        format=FORMATS[settings["format"]], pov=settings["pov"], scope=SCOPES[settings["scope"]],
        instructions=instructions) + ("\n\n" + campaign if campaign else "")
    messages = [{"role": "system", "content": system},
                {"role": "user", "content": scenes_text(scenes, settings["scope"])}]
    text = provider.chat(model, messages, temperature=0.6).strip()
    # Les modèles dépassent souvent la longueur demandée : une passe de coupe si l'écart est net.
    limit = int(settings["words"] * 1.2)
    too_long = len(text.split()) > limit or (settings["format"] == "discord" and len(text) > 1800)
    if too_long:
        order = (f"Ce texte fait {len(text.split())} mots et {len(text)} caractères. Réécris-le en {settings['words']} mots "
                 f"au maximum" + (", et moins de 1800 caractères" if settings["format"] == "discord" else "")
                 + ". Garde le ton, le format et les faits essentiels. N'ajoute aucun fait. Rends seulement le texte.")
        text = provider.chat(model, [*messages, {"role": "assistant", "content": text},
                                     {"role": "user", "content": order}], temperature=0.3).strip()
    text = strip_fence(text)
    # Garde-fou : une réplique entre guillemets doit exister dans le transcript.
    invented = unverified_quotes(text, transcript) if transcript else []
    if invented:
        listing = "\n".join(f"- {quote}" for quote in invented)
        order = ("Ces répliques entre guillemets ne figurent pas dans l'enregistrement :\n" + listing
                 + "\nRéécris le texte sans elles : passe au style indirect ou supprime-les. "
                   "Ne change rien d'autre, n'ajoute aucun fait. Rends seulement le texte.")
        text = provider.chat(model, [*messages, {"role": "assistant", "content": text},
                                     {"role": "user", "content": order}], temperature=0.2).strip()
    return strip_fence(text)


def strip_fence(text: str) -> str:
    """Retire les balises de bloc de code dont certains modèles entourent leur réponse."""
    match = re.fullmatch(r"\s*```[\w-]*\n(.*?)\n?```\s*", text, re.DOTALL)
    return match.group(1).strip() if match else text.strip()


QUOTE = re.compile(r'«\s*([^»]{6,}?)\s*»|“([^”]{6,}?)”|"([^"]{6,}?)"')


def unverified_quotes(text: str, t: Transcript) -> list[str]:
    """Répliques entre guillemets (deux mots ou plus) introuvables dans le transcript."""
    from .extract import norm, quote_found
    whole = norm(" ".join(seg.text for seg in t.segments))
    missing = []
    for match in QUOTE.finditer(text):
        quote = next(group for group in match.groups() if group)
        if len(quote.split()) < 2 or norm(quote) in whole:
            continue
        keys = [word for word in norm(quote).split() if len(word) > 4]
        near = [seg for seg in t.segments if sum(word in norm(seg.text) for word in keys) >= max(2, len(keys) // 2)]
        if not any(quote_found(quote, seg.text) for seg in near):
            missing.append(quote)
    return missing


def load_or_build_scenes(run: Path, t: Transcript, cast: dict, provider_name: str, model: str, force: bool,
                         progress=lambda message: None, campaign: str = "") -> list[dict]:
    path = run / "scenes.json"
    if path.exists() and not force:
        return json.loads(path.read_text())["scenes"]
    scenes = build_scenes(t, cast, provider_name, model, progress=progress, campaign=campaign)
    path.write_text(json.dumps({"model": f"{provider_name}/{model}", "scenes": scenes}, ensure_ascii=False, indent=1))
    return scenes
