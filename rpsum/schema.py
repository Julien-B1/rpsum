from __future__ import annotations

from pydantic import BaseModel, Field


class Segment(BaseModel):
    id: int = 0
    start: float
    end: float
    speaker: str
    text: str
    events: list[str] = Field(default_factory=list)
    # Remplis par l'étape `identify`.
    player: str | None = None
    role: str | None = None
    character: str | None = None
    mode: str | None = None
    tone: str | None = None
    confidence: float | None = None


class Transcript(BaseModel):
    provider: str
    model: str
    language: str | None = None
    duration: float = 0.0
    offset: float = 0.0  # position de l'extrait dans la source, en secondes
    segments: list[Segment] = Field(default_factory=list)

    def renumber(self) -> "Transcript":
        """Trie les segments, les numérote, et renomme les locuteurs par ordre d'apparition."""
        self.segments.sort(key=lambda s: (s.start, s.end))
        names: dict[str, str] = {}
        for i, seg in enumerate(self.segments):
            seg.id = i
            seg.speaker = names.setdefault(seg.speaker, f"speaker_{len(names)}")
        return self


def timestamp(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"


def to_markdown(t: Transcript, title: str = "Transcript") -> str:
    lines = [f"# {title}", "", f"Fournisseur : {t.provider} · modèle : {t.model}", ""]
    for seg in t.segments:
        lines.append(f"[{timestamp(seg.start + t.offset)}] {seg.speaker} — {seg.text}")
    return "\n".join(lines) + "\n"
