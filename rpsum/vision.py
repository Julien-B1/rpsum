"""Lecture d'images par un modèle de vision : incrustations de la vidéo, images jointes au contexte."""
from __future__ import annotations

import base64
import json
import re
import subprocess
from pathlib import Path

from .tasks import resolve

OVERLAY_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["title", "order_evidence", "people", "other_text"],
    "properties": {
        "title": {"type": ["string", "null"]},
        "order_evidence": {"type": "string"},
        "people": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["name", "role", "character"],
            "properties": {
                "name": {"type": "string"},
                "role": {"type": "string", "enum": ["mj", "joueur", "inconnu"]},
                "character": {"type": ["string", "null"]},
            }}},
        "other_text": {"type": "array", "items": {"type": "string"}},
    },
}

OVERLAY_PROMPT = """Ces images viennent de l'enregistrement vidéo d'une partie de jeu de rôle sur table.
L'habillage affiche souvent, près de chaque webcam, le pseudo du participant et le nom de son personnage.
Relève ce qui est écrit à l'écran :
- title : le titre de la partie ou du jeu s'il est affiché, sinon null.
- people : une entrée par participant. `name` est le pseudo de la personne réelle, `role` vaut « mj » pour le
  maître du jeu (souvent marqué MJ, GM, Maître du jeu) et « joueur » sinon, `character` est le nom du personnage
  joué (null pour le MJ ou si rien n'est affiché).
- other_text : les autres textes lisibles et utiles (nom du jeu, de la chaîne, du scénario).
- order_evidence : une phrase qui dit comment tu as distingué pseudo et personnage.

Une étiquette du type « A - B » ne dit pas d'elle-même lequel est le pseudo. Détermine l'ordre avec ces indices,
puis applique le même ordre à toutes les étiquettes :
- L'étiquette du MJ donne le modèle : « Maître du Jeu - Karu » signifie « rôle - pseudo », donc les étiquettes
  des joueurs sont « personnage - pseudo ». À l'inverse « Karu - Maître du Jeu » signifie « pseudo - personnage ».
- Un historique de jets de dés ou une fiche affichent des noms de personnages.
- Une liste de salon vocal (Discord) affiche des pseudos de personnes réelles.
Les noms d'abonnés, de donateurs ou de spectateurs affichés dans un bandeau ne sont pas des participants :
mets-les dans other_text en précisant « spectateur ».
Recopie les noms exactement comme ils sont écrits. N'invente rien : si un nom est illisible, ne le donne pas.
Si plusieurs images montrent la même chose, ne répète pas les participants."""


def url_start(url: str) -> float:
    """Position de départ portée par l'URL (`t=229s`, `t=1h2m3s`), en secondes."""
    match = re.search(r"[?&#]t=(?:(\d+)h)?(?:(\d+)m)?(\d+)?s?", url)
    if not match or not any(match.groups()):
        return 0.0
    hours, minutes, seconds = (int(g or 0) for g in match.groups())
    return float(hours * 3600 + minutes * 60 + seconds)


def capture_frames(source: str, times: list[float], out: Path, height: int = 720) -> list[Path]:
    """Capture une image de la vidéo à chaque instant demandé. `source` est une URL ou un fichier local."""
    out.mkdir(parents=True, exist_ok=True)
    frames: list[Path] = []
    stream = source
    if not Path(source).is_file():
        from yt_dlp import YoutubeDL
        opts = {"quiet": True, "no_warnings": True, "format": f"bv*[height<={height}]/b[height<={height}]/b"}
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(source, download=False)
        stream = info.get("url") or info["requested_formats"][0]["url"]
    for moment in times:
        frame = out / f"frame_{int(moment):06d}.jpg"
        proc = subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-ss", f"{moment:.1f}", "-i", stream, "-frames:v", "1", "-q:v", "3", str(frame)],
            capture_output=True, text=True, timeout=180)
        if proc.returncode == 0 and frame.exists() and frame.stat().st_size > 0:
            frames.append(frame)
    return frames


def image_part(path: Path) -> dict:
    kind = {"jpg": "jpeg", "jpeg": "jpeg", "png": "png", "webp": "webp"}.get(path.suffix.lower().lstrip("."), "jpeg")
    data = base64.b64encode(path.read_bytes()).decode()
    return {"type": "image_url", "image_url": {"url": f"data:image/{kind};base64,{data}"}}


def read_overlay(images: list[Path], provider_name: str, model: str) -> dict:
    """Relève les participants et personnages affichés à l'écran."""
    provider = resolve("vision", provider_name, model)
    content = [{"type": "text", "text": OVERLAY_PROMPT}, *[image_part(p) for p in images]]
    answer = provider.chat(model, [{"role": "user", "content": content}], json_schema=OVERLAY_SCHEMA, temperature=0.0)
    return json.loads(answer)
