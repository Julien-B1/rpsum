"""Outils communs aux étapes qui passent le transcript à un LLM par fenêtres."""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor

from .schema import Segment, Transcript, timestamp


def line(seg: Segment, offset: float = 0.0) -> str:
    who = seg.player or seg.speaker
    if seg.character and seg.character != who:
        who += f" / {seg.character}"
    mode = f" ({seg.mode})" if seg.mode else ""
    return f"{seg.id} [{timestamp(seg.start + offset)}] {who}{mode}: {seg.text}"


def windows(t: Transcript, size: int, overlap: int = 0) -> list[list[Segment]]:
    step = size - overlap
    return [t.segments[i:i + size] for i in range(0, max(1, len(t.segments) - overlap), step)]


def chat_json(provider, model: str, system: str, user: str, schema: dict, temperature: float = 0.2) -> dict:
    """Appel avec sortie JSON contrainte. Un second essai si la réponse n'est pas du JSON valide."""
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    for attempt in (1, 2):
        answer = provider.chat(model, messages, json_schema=schema, temperature=temperature)
        try:
            return json.loads(answer)
        except json.JSONDecodeError:
            if attempt == 2:
                raise RuntimeError(f"Réponse JSON invalide de {model} : {answer[:200]}")
    raise AssertionError("inatteignable")


def parallel(work, items: list, workers: int = 4, progress=lambda message: None, label: str = "") -> list:
    results = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for index, result in enumerate(pool.map(work, items)):
            results.append(result)
            progress(f"{label} : fenêtre {index + 1} sur {len(items)}")
    return results
