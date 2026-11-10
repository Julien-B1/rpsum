from __future__ import annotations

from .providers import PROVIDERS, Cap, ModelInfo

# Capacités qu'un modèle doit avoir pour être proposé sur une tâche.
TASKS: dict[str, set[Cap]] = {
    "transcribe": {Cap.STT, Cap.DIARIZATION},
    "context": {Cap.CHAT, Cap.JSON_SCHEMA},
    "vision": {Cap.CHAT, Cap.JSON_SCHEMA, Cap.VISION},
    "identify": {Cap.CHAT, Cap.JSON_SCHEMA},
    "summarize": {Cap.CHAT},
    "extract": {Cap.CHAT, Cap.JSON_SCHEMA},
}


def compatible(task: str, models: list[ModelInfo]) -> list[ModelInfo]:
    return [m for m in models if TASKS[task] <= m.caps]


def resolve(task: str, provider_name: str, model: str):
    """Renvoie le fournisseur après avoir vérifié que le modèle convient à la tâche."""
    if provider_name not in PROVIDERS:
        raise SystemExit(f"Fournisseur inconnu : {provider_name}. Choix : {', '.join(PROVIDERS)}.")
    provider = PROVIDERS[provider_name]()
    ok, why = provider.available()
    if not ok:
        raise SystemExit(f"Fournisseur {provider_name} indisponible : {why}")
    models = provider.list_models()
    info = next((m for m in models if m.id == model), None)
    if info is None:
        raise SystemExit(f"Modèle {model} inconnu chez {provider_name}.")
    missing = TASKS[task] - info.caps
    if missing:
        names = ", ".join(m.id for m in compatible(task, models)) or "aucun"
        raise SystemExit(
            f"Modèle {model} incompatible avec « {task} » "
            f"(capacités manquantes : {', '.join(sorted(missing))}). Compatibles : {names}."
        )
    return provider
