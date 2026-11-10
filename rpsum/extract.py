"""Étape `extract` : moments forts, bêtisier et mèmes, avec citations vérifiées contre le transcript."""
from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path

from . import audio as au
from . import llm
from .schema import Transcript, timestamp
from .summarize import cast_text
from .tasks import resolve

CATEGORIES = {"moment-fort": "Moments forts", "betisier": "Bêtisier", "meme": "Mèmes"}
SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["items"],
    "properties": {"items": {"type": "array", "items": {
        "type": "object", "additionalProperties": False,
        "required": ["category", "title", "start_id", "end_id", "quote", "why", "caption", "score"],
        "properties": {
            "category": {"type": "string", "enum": list(CATEGORIES)},
            "title": {"type": "string"},
            "start_id": {"type": "integer"}, "end_id": {"type": "integer"},
            "quote": {"type": "string"},
            "why": {"type": "string"},
            "caption": {"type": ["string", "null"]},
            "score": {"type": "integer"},
        }}}},
}

PROMPT = """Tu repères les meilleurs passages d'une partie de jeu de rôle sur table, pour un montage vidéo. Distribution :
{cast}

Trois catégories :
- « moment-fort » : retournement, réussite ou échec critique, combat décisif, scène d'émotion, révélation, belle scène de jeu.
- « betisier » : fou rire, lapsus, erreur de règles, plan absurde, incident technique, dérapage hors jeu.
- « meme » : réplique courte et citable hors contexte, blague récurrente, surnom. Donne dans `caption` une légende de mème.

Pour chaque passage :
- start_id, end_id : numéros de la première et de la dernière réplique. Un passage dure de quelques répliques à une trentaine.
- quote : la réplique la plus marquante, copiée mot pour mot depuis une seule réplique du passage, sans rien corriger.
- title : titre court. why : une phrase qui explique l'intérêt.
- caption : légende, seulement pour « meme ». Sinon null.
- score : de 1 à 10. Réserve 8 et plus aux passages qui méritent vraiment un extrait.

Les mentions [rire] signalent des rires captés par le micro : bon indice pour le bêtisier.
Sois sélectif : de 0 à 6 passages pour ce bloc. Un bloc sans intérêt donne une liste vide."""


def norm(text: str) -> str:
    text = unicodedata.normalize("NFD", text.lower())
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def quote_found(quote: str, haystack: str, tolerance: float = 0.85) -> bool:
    """Vrai si la citation figure dans le texte, à la ponctuation, la casse et quelques mots près."""
    q, h = norm(quote), norm(haystack)
    if len(q) < 8:
        return False
    if q in h:
        return True
    matched = sum(block.size for block in SequenceMatcher(None, q, h, autojunk=False).get_matching_blocks())
    return matched / len(q) >= tolerance and len(q) <= len(h)


def find_quote(t: Transcript, item: dict, margin: int = 3) -> int | None:
    """Renvoie le numéro de la réplique qui contient la citation, cherchée dans le passage élargi de `margin`."""
    low = max(0, item["start_id"] - margin)
    high = min(len(t.segments) - 1, item["end_id"] + margin)
    for seg in t.segments[low:high + 1]:
        if quote_found(item["quote"], seg.text):
            return seg.id
    return None


def link(url: str | None, seconds: float) -> str | None:
    if not url:
        return None
    s = int(seconds)
    if "twitch.tv" in url:
        return f"{url}?t={s // 3600}h{s % 3600 // 60}m{s % 60}s"
    return f"{url}{'&' if '?' in url else '?'}t={s}s"


def extract(t: Transcript, cast: dict, provider_name: str, model: str, url: str | None = None,
            window: int = 220, overlap: int = 20, max_span: float = 300.0,
            progress=lambda message: None, campaign: str = "") -> tuple[list[dict], int]:
    """Renvoie les passages retenus et le nombre de passages rejetés (citation introuvable ou bornes fausses)."""
    provider = resolve("extract", provider_name, model)
    system = PROMPT.format(cast=cast_text(cast)) + ("\n\n" + campaign if campaign else "")

    def work(segments) -> list[dict]:
        text = "\n".join(llm.line(s, t.offset) for s in segments)
        return llm.chat_json(provider, model, system, text, SCHEMA, temperature=0.3)["items"]

    batches = llm.parallel(work, llm.windows(t, window, overlap), progress=progress, label="extract")
    kept: list[dict] = []
    rejected = 0
    last = len(t.segments) - 1
    for item in (i for batch in batches for i in batch):
        if not (0 <= item["start_id"] <= item["end_id"] <= last):
            rejected += 1
            continue
        quote_id = find_quote(t, item)
        if quote_id is None:
            rejected += 1
            continue
        start = t.segments[item["start_id"]].start + t.offset
        end = min(t.segments[item["end_id"]].end + t.offset, start + max_span)
        quoted = t.segments[quote_id]
        item.update(start=round(start, 1), end=round(end, 1), quote_id=quote_id,
                    quote_by=(quoted.player or quoted.speaker) + (f" / {quoted.character}" if quoted.character else ""),
                    quote=quoted.text if len(quoted.text) <= 240 else item["quote"],
                    score=min(max(item["score"], 1), 10), url=link(url, start))
        # Les fenêtres se recouvrent : un même passage peut sortir deux fois. On garde le mieux noté.
        twin = next((k for k in kept if k["category"] == item["category"]
                     and k["start"] < item["end"] and item["start"] < k["end"]), None)
        if twin is None:
            kept.append(item)
        elif item["score"] > twin["score"]:
            kept[kept.index(twin)] = item
    kept.sort(key=lambda i: (-i["score"], i["start"]))
    return kept, rejected


def to_markdown(items: list[dict], title: str, top: int = 15) -> str:
    lines = [f"# {title} — moments forts, bêtisier, mèmes", ""]
    for category, label in CATEGORIES.items():
        chosen = [i for i in items if i["category"] == category][:top]
        lines += [f"## {label} ({len(chosen)})", ""]
        for item in sorted(chosen, key=lambda i: i["start"]):
            stamp = f"{timestamp(item['start'])}–{timestamp(item['end'])}"
            stamp = f"[{stamp}]({item['url']})" if item.get("url") else stamp
            lines += [f"### {item['title']} · {item['score']}/10", f"{stamp}", "",
                      f"> {item['quote']}", f"> — {item['quote_by']}", "", item["why"]]
            if item.get("caption"):
                lines.append(f"\nLégende : *{item['caption']}*")
            lines.append("")
    return "\n".join(lines)


def cut_clips(run: Path, items: list[dict], offset: float, min_score: int = 8, pad: float = 2.0) -> int:
    """Découpe l'audio des passages les mieux notés dans runs/<id>/clips/."""
    clips = run / "clips"
    clips.mkdir(exist_ok=True)
    count = 0
    for item in items:
        if item["score"] < min_score:
            continue
        slug = re.sub(r"[^a-z0-9]+", "-", norm(item["title"]))[:40].strip("-")
        name = f"{item['category']}_{timestamp(item['start']).replace(':', '')}_{slug}.opus"
        start = max(0.0, item["start"] - offset - pad)
        au.cut(run / "audio.opus", start, item["end"] - item["start"] + 2 * pad, clips / name)
        item["clip"] = f"clips/{name}"
        count += 1
    return count
