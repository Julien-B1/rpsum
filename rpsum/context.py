"""Contexte de campagne : un fichier Markdown libre (notes, noms, extraits, liens) est transformé en fiche
structurée (`context.json`) qui sert au lexique de transcription, à l'identification et aux prompts."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import httpx

from . import llm
from .tasks import resolve

MAX_SOURCE_CHARS = 200_000   # par source
CHUNK_CHARS = 120_000        # taille d'un passage envoyé au modèle
ENTITY_LISTS = {"characters": "Personnages joueurs", "npcs": "PNJ", "places": "Lieux", "factions": "Factions",
                "items": "Objets", "terms": "Termes de l'univers"}

ENTITY = {"type": "object", "additionalProperties": False, "required": ["name", "aliases", "description"],
          "properties": {"name": {"type": "string"}, "aliases": {"type": "array", "items": {"type": "string"}},
                         "description": {"type": "string"}}}
SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["title", "system", "setting", "background", "people", *ENTITY_LISTS],
    "properties": {
        "title": {"type": ["string", "null"]}, "system": {"type": ["string", "null"]},
        "setting": {"type": "string"}, "background": {"type": "string"},
        "people": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["name", "aliases", "role", "character"],
            "properties": {"name": {"type": "string"}, "aliases": {"type": "array", "items": {"type": "string"}},
                           "role": {"type": "string", "enum": ["mj", "joueur"]},
                           "character": {"type": ["string", "null"]}}}},
        **{key: {"type": "array", "items": ENTITY} for key in ENTITY_LISTS},
    },
}

PROMPT = """Tu prépares la fiche de contexte d'une partie de jeu de rôle sur table qui va être transcrite
automatiquement puis résumée. On te donne des documents bruts : notes du MJ, listes de noms, extraits, description
de la vidéo, textes relevés à l'écran. Extrais-en tout ce qui aidera à bien écrire les noms et à comprendre la partie.

- title : nom de la campagne ou du scénario. system : jeu ou système de règles. null si inconnu.
- setting : l'univers en quelques phrases. background : ce qui s'est passé avant cette session, si c'est dit.
- people : les personnes réelles qui jouent à la table, et elles seules (pas les spectateurs, abonnés ou
  donateurs). `name` est le pseudo ou prénom, `role` vaut « mj » ou « joueur », `character` est le personnage
  joué (null pour le MJ). Si le fichier de contexte et le relevé de l'écran se contredisent, le fichier a raison.
- characters : les personnages joueurs. npcs : les personnages non joueurs. places, factions, items : lieux,
  groupes, objets. terms : tout autre nom propre ou mot inventé de l'univers (sorts, monnaies, peuples, dieux).
- Pour chaque entrée : `name` est l'orthographe exacte et officielle, `aliases` les surnoms, titres et autres
  façons de le dire ou de l'écrire, `description` une phrase utile (rôle, lien avec les autres). Chaîne vide si rien.

Règles : ne retiens que ce qui figure dans les documents. N'invente aucun nom. Garde l'orthographe des documents.
Un même nom ne figure que dans une seule liste. Sois exhaustif sur les noms propres : chacun compte."""

GOOGLE = re.compile(r"https://docs\.google\.com/(document|spreadsheets|presentation)/d/([\w-]+)")
MD_LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
# Chemin écrit tel quel dans le texte, sans espace (un chemin avec espaces passe par un lien Markdown).
BARE_PATH = re.compile(r"(?<![\w(:/])((?:~|\.{1,2})?/[\w./-]+\.(?:md|txt|json|csv|pdf|png|jpe?g|webp))")
IMAGES = {".png", ".jpg", ".jpeg", ".webp"}


def _google(kind: str, doc_id: str) -> str:
    export = {"document": "export?format=txt", "spreadsheets": "export?format=csv", "presentation": "export/txt"}[kind]
    resp = httpx.get(f"https://docs.google.com/{kind}/d/{doc_id}/{export}", follow_redirects=True, timeout=60)
    if resp.status_code != 200 or "text/html" in resp.headers.get("content-type", ""):
        raise RuntimeError("document non partagé par lien (accès « toute personne disposant du lien » requis)")
    return resp.text


def _local(path: Path) -> str:
    if path.suffix.lower() == ".pdf":
        from pypdf import PdfReader
        return "\n".join(page.extract_text() or "" for page in PdfReader(str(path)).pages)
    return path.read_text(errors="replace")


def gather(raw: str, base: Path) -> tuple[list[dict], list[Path]]:
    """Suit les liens du fichier de contexte. Renvoie les sources lues (avec leur statut) et les images trouvées."""
    sources = [{"ref": "fichier de contexte", "status": "lu", "text": raw}]
    images: list[Path] = []
    seen: set[str] = set()
    for kind, doc_id in GOOGLE.findall(raw):
        ref = f"https://docs.google.com/{kind}/d/{doc_id}"
        if ref in seen:
            continue
        seen.add(ref)
        try:
            sources.append({"ref": ref, "status": "lu", "text": _google(kind, doc_id)[:MAX_SOURCE_CHARS]})
        except Exception as exc:  # une source illisible ne doit pas arrêter les autres
            sources.append({"ref": ref, "status": f"échec : {exc}", "text": ""})
    candidates = [m for m in MD_LINK.findall(raw) if not m.startswith(("http://", "https://", "#", "mailto:"))]
    candidates += BARE_PATH.findall(raw)
    for ref in candidates:
        path = Path(ref).expanduser()
        path = path if path.is_absolute() else (base / path)
        key = str(path.resolve())
        if key in seen:
            continue
        seen.add(key)
        if not path.is_file():
            sources.append({"ref": ref, "status": "échec : fichier introuvable", "text": ""})
        elif path.suffix.lower() in IMAGES:
            images.append(path)
            sources.append({"ref": ref, "status": "image, lue par le modèle de vision", "text": ""})
        else:
            try:
                sources.append({"ref": ref, "status": "lu", "text": _local(path)[:MAX_SOURCE_CHARS]})
            except Exception as exc:
                sources.append({"ref": ref, "status": f"échec : {exc}", "text": ""})
    for ref in re.findall(r"https?://[^\s)>\]]+", raw):
        if "docs.google.com" not in ref and ref not in seen:
            seen.add(ref)
            sources.append({"ref": ref, "status": "non suivi (seuls Google Docs et fichiers locaux le sont)", "text": ""})
    return sources, images


def merge(parts: list[dict]) -> dict:
    """Fusionne les fiches extraites de plusieurs passages. Un nom déjà vu garde sa première fiche, enrichie."""
    out = {"title": None, "system": None, "setting": "", "background": "", "people": [],
           **{key: [] for key in ENTITY_LISTS}}
    for part in parts:
        for key in ("title", "system"):
            out[key] = out[key] or part.get(key)
        for key in ("setting", "background"):
            if part.get(key) and part[key] not in out[key]:
                out[key] = (out[key] + " " + part[key]).strip()
        for key in ("people", *ENTITY_LISTS):
            known = {entry["name"].lower(): entry for entry in out[key]}
            for entry in part.get(key, []):
                if not entry.get("name"):
                    continue
                first = known.get(entry["name"].lower())
                if first is None:
                    out[key].append(entry)
                    known[entry["name"].lower()] = entry
                    continue
                first["aliases"] = list(dict.fromkeys([*first["aliases"], *entry.get("aliases", [])]))
                for field in ("description", "character"):
                    if field in entry and not first.get(field):
                        first[field] = entry[field]
    return out


def build(raw: str, base: Path, extra: dict[str, str], provider_name: str, model: str,
          read_images=None, progress=lambda message: None) -> dict:
    """Construit la fiche de contexte. `extra` : autres textes à joindre (description de la vidéo, incrustations).
    `read_images` : fonction qui reçoit des images et renvoie le texte relevé (modèle de vision)."""
    provider = resolve("context", provider_name, model)
    sources, images = gather(raw, base) if raw else ([], [])
    if images and read_images:
        extra = {**extra, "Images jointes au contexte (relevé du modèle de vision)": read_images(images)}
    blocks = [f"### {s['ref']}\n{s['text']}" for s in sources if s["text"].strip()]
    blocks += [f"### {name}\n{text}" for name, text in extra.items() if text and text.strip()]
    if not blocks:
        raise SystemExit("Aucun contenu de contexte à analyser.")
    chunks, current = [], ""
    for block in blocks:  # passages de taille bornée, sans couper une source si elle tient
        while len(block) > CHUNK_CHARS:
            chunks.append(block[:CHUNK_CHARS])
            block = block[CHUNK_CHARS:]
        if len(current) + len(block) > CHUNK_CHARS:
            chunks.append(current)
            current = ""
        current += block + "\n\n"
    chunks.append(current)
    parts = llm.parallel(lambda chunk: llm.chat_json(provider, model, PROMPT, chunk, SCHEMA, temperature=0.0),
                         chunks, workers=2, progress=progress, label="context")
    context = merge(parts)
    context["sources"] = [{"ref": s["ref"], "status": s["status"]} for s in sources] + [
        {"ref": name, "status": "lu"} for name, text in extra.items() if text and text.strip()]
    context["model"] = f"{provider_name}/{model}"
    return context


def fingerprint(raw: str, extra: dict[str, str]) -> str:
    return hashlib.sha256(json.dumps([raw, extra], sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


def load(run: Path) -> dict | None:
    path = run / "context.json"
    return json.loads(path.read_text()) if path.exists() else None


def vocabulary(context: dict, limit: int = 100) -> list[str]:
    """Noms à fournir au modèle de transcription, les plus importants d'abord."""
    names: list[str] = []
    for person in context.get("people", []):
        names += [person["name"], person.get("character") or ""]
    for key in ENTITY_LISTS:
        names += [entry["name"] for entry in context.get(key, [])]
    cleaned = [n.strip() for n in names if n and 1 < len(n.strip()) <= 50]
    return list(dict.fromkeys(cleaned))[:limit]


def hints(context: dict) -> dict:
    """Ce que l'étape `identify` peut tenir pour sûr."""
    people = context.get("people", [])
    gm = next((p["name"] for p in people if p["role"] == "mj"), None)
    players = [{"name": p["name"], "character": p.get("character")} for p in people if p["role"] == "joueur"]
    characters = [p["character"] for p in players if p["character"]] or [c["name"] for c in context.get("characters", [])]
    return {"gm": gm, "players": players, "characters": characters, "people": len(people) or None}


def prompt_block(context: dict | None, limit: int = 6000) -> str:
    """Résumé du contexte à glisser dans les prompts : univers, puis noms officiels à respecter."""
    if not context:
        return ""
    lines = ["Contexte de campagne (fourni par l'utilisateur, fiable ; écris les noms exactement ainsi) :"]
    for label, key in (("Campagne", "title"), ("Jeu", "system"), ("Univers", "setting"), ("Avant cette session", "background")):
        if context.get(key):
            lines.append(f"- {label} : {context[key]}")
    for key, label in ENTITY_LISTS.items():
        entries = context.get(key, [])
        if entries:
            lines.append(f"- {label} : " + " ; ".join(
                entry["name"] + (f" ({entry['description']})" if entry.get("description") else "")
                + (f" [aussi : {', '.join(entry['aliases'])}]" if entry.get("aliases") else "") for entry in entries))
    text = "\n".join(lines)
    return (text[:limit] + "…") if len(text) > limit else text


def to_markdown(context: dict) -> str:
    lines = [f"# Contexte — {context.get('title') or 'campagne'}", ""]
    for label, key in (("Jeu", "system"), ("Univers", "setting"), ("Avant cette session", "background")):
        if context.get(key):
            lines += [f"**{label}.** {context[key]}", ""]
    if context.get("people"):
        lines += ["## Participants", ""]
        lines += [f"- {p['name']} — {p['role']}" + (f", joue {p['character']}" if p.get("character") else "")
                  for p in context["people"]] + [""]
    for key, label in ENTITY_LISTS.items():
        if context.get(key):
            lines += [f"## {label}", ""]
            lines += [f"- **{e['name']}**" + (f" (aussi : {', '.join(e['aliases'])})" if e.get("aliases") else "")
                      + (f" — {e['description']}" if e.get("description") else "") for e in context[key]] + [""]
    lines += ["## Sources", ""] + [f"- {s['ref']} : {s['status']}" for s in context.get("sources", [])]
    return "\n".join(lines) + "\n"
