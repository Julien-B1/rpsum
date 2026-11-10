"""Étape `identify` : qui parle (distribution), puis pour chaque réplique, en jeu ou hors jeu et sous quel personnage."""
from __future__ import annotations

import json
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .schema import Segment, Transcript, timestamp
from .tasks import resolve

MODES = ["en-jeu", "narration", "hors-jeu", "regles"]
ROLES = ["mj", "joueur", "autre"]

CAST_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["speakers"],
    "properties": {"speakers": {"type": "array", "items": {
        "type": "object", "additionalProperties": False,
        "required": ["speaker", "player", "role", "characters", "evidence", "confidence"],
        "properties": {
            "speaker": {"type": "string"},
            "player": {"type": "string"},
            "role": {"type": "string", "enum": ROLES},
            "characters": {"type": "array", "items": {"type": "string"}},
            "evidence": {"type": "string"},
            "confidence": {"type": "number"},
        }}}},
}

LINES_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["lines"],
    "properties": {"lines": {"type": "array", "items": {
        "type": "object", "additionalProperties": False, "required": ["id", "mode", "character"],
        "properties": {
            "id": {"type": "integer"},
            "mode": {"type": "string", "enum": MODES},
            "character": {"type": ["string", "null"]},
        }}}},
}

CAST_PROMPT = """Tu analyses le transcript d'une partie de jeu de rôle sur table, enregistrée en vidéo.
La séparation automatique des voix a produit des identifiants de locuteurs (speaker_N). Elle fait des erreurs :
une même personne peut avoir plusieurs identifiants, et un identifiant très peu bavard peut être du bruit.

Pour chaque identifiant, détermine :
- player : le prénom ou pseudo de la personne réelle s'il est prononcé. Sinon « MJ » pour le maître du jeu,
  ou « Joueur de <personnage> » pour un joueur. Deux identifiants de la même personne reçoivent exactement le même `player`.
- role : « mj », « joueur », ou « autre » (voix extérieure, bruit, identifiant inclassable).
- characters : le personnage joueur incarné. Pour le MJ, liste vide (ses PNJ sont traités ailleurs).
- evidence : une phrase qui cite l'indice du transcript qui justifie ton choix.
- confidence : entre 0 et 1.

Indices utiles : le MJ décrit les lieux, fait parler les PNJ, demande des jets de dés et parle le plus.
Un joueur dit « je » pour son personnage, et les autres l'interpellent par le nom de son personnage.
Attention : quand quelqu'un appelle un nom, c'est le nom de la personne à qui il parle, pas le sien.
{hints}
Réponds en JSON, avec une entrée par identifiant listé ci-dessous, sans en oublier."""

LINES_PROMPT = """Tu annotes le transcript d'une partie de jeu de rôle sur table. Distribution :
{cast}

Pour chaque réplique numérotée, donne :
- mode :
  « en-jeu » : la personne parle ou agit en tant que personnage (dialogue, « je fais telle action »).
  « narration » : le MJ décrit une scène, un lieu, le résultat d'une action.
  « regles » : jets de dés, points de vie, règles, fiches de personnage.
  « hors-jeu » : blagues, discussion entre joueurs, technique, pause, adresse au public.
- character : le personnage qui s'exprime, seulement en mode « en-jeu ». Pour un joueur, son personnage.
  Pour le MJ, le nom du PNJ qu'il fait parler (ou une courte description, par exemple « le vieux pêcheur »). Sinon null.

Les répliques marquées [contexte] servent à comprendre la scène : ne les annote pas.
Réponds en JSON avec une entrée par réplique à annoter, en reprenant son numéro."""


def _line(seg: Segment, offset: float, who: str | None = None) -> str:
    return f"{seg.id} [{timestamp(seg.start + offset)}] {who or seg.speaker}: {seg.text}"


def sample_for_cast(t: Transcript, names: list[str], per_speaker: int = 30, opening: int = 120,
                    mentions: int = 80) -> str:
    """Échantillon compact : début de session, répliques réparties de chaque locuteur, et passages où un nom
    connu est prononcé. Reste petit pour tenir dans le contexte d'un modèle local."""
    picked: dict[int, Segment] = {s.id: s for s in t.segments[:opening]}
    by_speaker: dict[str, list[Segment]] = defaultdict(list)
    for seg in t.segments:
        by_speaker[seg.speaker].append(seg)
    for segs in by_speaker.values():
        long_ones = [s for s in segs if len(s.text.split()) >= 8] or segs
        step = max(1, len(long_ones) // per_speaker)
        for seg in long_ones[::step][:per_speaker]:
            picked[seg.id] = seg
    lowered = [n.lower() for n in names]
    hits = [s for s in t.segments if any(n in s.text.lower() for n in lowered)]
    for seg in hits[:: max(1, len(hits) // mentions)][:mentions] if hits else []:
        picked[seg.id] = seg
        if seg.id + 1 < len(t.segments):  # la réponse qui suit dit souvent qui a été interpellé
            picked[seg.id + 1] = t.segments[seg.id + 1]
    stats = [f"- {name} : {int(sum(s.end - s.start for s in segs) // 60)} min de parole, {len(segs)} répliques"
             for name, segs in sorted(by_speaker.items(), key=lambda kv: -sum(s.end - s.start for s in kv[1]))]
    lines = [_line(picked[i], t.offset) for i in sorted(picked)]
    return "Identifiants :\n" + "\n".join(stats) + "\n\nExtraits (numéro, horodatage, locuteur) :\n" + "\n".join(lines)


def propose_cast(run: Path, t: Transcript, provider_name: str, model: str) -> dict:
    provider = resolve("identify", provider_name, model)
    hints_path = run / "hints.json"
    hints = json.loads(hints_path.read_text()) if hints_path.exists() else {}
    hint_text = ""
    if hints:
        hint_text = "\nInformations fournies par l'utilisateur (fiables) :\n"
        if hints.get("gm"):
            hint_text += f"- Le maître du jeu s'appelle {hints['gm']}.\n"
        if hints.get("characters"):
            hint_text += f"- Personnages joueurs : {', '.join(hints['characters'])}. Un joueur par personnage.\n"
        if hints.get("people"):
            hint_text += f"- Il y a {hints['people']} personnes à table.\n"
    names = [n for n in [hints.get("gm"), *hints.get("characters", [])] if n]
    answer = provider.chat(model, [
        {"role": "system", "content": CAST_PROMPT.format(hints=hint_text)},
        {"role": "user", "content": sample_for_cast(t, names)},
    ], json_schema=CAST_SCHEMA, temperature=0.0)
    cast = json.loads(answer)
    known = {s.speaker for s in t.segments}
    cast["speakers"] = [entry for entry in cast["speakers"] if entry["speaker"] in known]
    for missing in sorted(known - {entry["speaker"] for entry in cast["speakers"]}):
        cast["speakers"].append({"speaker": missing, "player": "Inconnu", "role": "autre", "characters": [],
                                 "evidence": "Non classé par le modèle.", "confidence": 0.0})
    cast["model"] = f"{provider_name}/{model}"
    return cast


def apply_cast(t: Transcript, cast: dict) -> None:
    by_id = {entry["speaker"]: entry for entry in cast["speakers"]}
    for seg in t.segments:
        entry = by_id.get(seg.speaker)
        if entry:
            seg.player, seg.role = entry["player"], entry["role"]


def annotate_lines(t: Transcript, cast: dict, provider_name: str, model: str, window: int = 120,
                   context: int = 12, workers: int = 4, progress=lambda message: None) -> int:
    """Remplit `mode` et `character` par fenêtres de `window` répliques. Renvoie le nombre de répliques annotées."""
    provider = resolve("identify", provider_name, model)
    people: dict[str, dict] = {}
    for entry in cast["speakers"]:
        people.setdefault(entry["player"], {"role": entry["role"], "characters": []})["characters"] += entry["characters"]
    cast_text = "\n".join(
        f"- {player} : {info['role']}" + (f", joue {', '.join(dict.fromkeys(info['characters']))}" if info["characters"] else "")
        for player, info in people.items())
    own = {entry["player"]: entry["characters"][0] for entry in cast["speakers"]
           if entry["role"] == "joueur" and entry["characters"]}
    starts = list(range(0, len(t.segments), window))

    def work(start: int) -> list[dict]:
        before = t.segments[max(0, start - context):start]
        body = t.segments[start:start + window]
        text = "\n".join(["[contexte] " + _line(s, t.offset, s.player) for s in before]
                         + [_line(s, t.offset, s.player) for s in body])
        answer = provider.chat(model, [
            {"role": "system", "content": LINES_PROMPT.format(cast=cast_text)},
            {"role": "user", "content": text},
        ], json_schema=LINES_SCHEMA, temperature=0.0)
        return json.loads(answer)["lines"]

    done = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for index, (start, lines) in enumerate(zip(starts, pool.map(work, starts))):
            valid = range(start, min(start + window, len(t.segments)))
            for line in lines:
                if line["id"] not in valid:
                    continue  # le modèle a annoté une réplique de contexte ou inventé un numéro
                seg = t.segments[line["id"]]
                seg.mode = line["mode"]
                seg.character = line["character"] if line["mode"] == "en-jeu" else None
                # Un joueur en jeu parle pour son propre personnage, quoi qu'en dise le modèle.
                if seg.mode == "en-jeu" and seg.role == "joueur" and seg.player in own:
                    seg.character = own[seg.player]
                # Le MJ ne joue pas les personnages joueurs : soit le modèle a noté l'interlocuteur,
                # soit la voix d'un joueur a été attribuée au MJ. On retire le nom et on signale le doute.
                if seg.role == "mj" and seg.character in own.values():
                    seg.character, seg.confidence = None, 0.3
                done += 1
            progress(f"identify : fenêtre {index + 1} sur {len(starts)}")
    return done


def to_script(t: Transcript, title: str) -> str:
    """Transcript façon script : « [hh:mm:ss] Joueur / Personnage (mode) — texte »."""
    lines = [f"# {title}", ""]
    for seg in t.segments:
        who = seg.player or seg.speaker
        if seg.character and seg.character != who:
            who += f" / {seg.character}"
        mode = f" ({seg.mode})" if seg.mode else ""
        lines.append(f"[{timestamp(seg.start + t.offset)}] {who}{mode} — {seg.text}")
    return "\n".join(lines) + "\n"
