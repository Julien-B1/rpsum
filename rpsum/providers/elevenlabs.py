from __future__ import annotations

import os
from pathlib import Path

import httpx

from .. import audio as au, usage
from ..schema import Segment, Transcript
from .base import Cap, ModelInfo, Provider, TranscribeOptions, form

API = "https://api.elevenlabs.io"
TURN_GAP = 2.0  # silence, en secondes, qui ouvre un nouveau segment pour un même locuteur


def normalize(raw: dict, model: str) -> Transcript:
    """Regroupe les mots en segments par locuteur. Les sons restent dans le texte, entre crochets,
    et sont aussi listés dans `events`."""
    segments: list[Segment] = []
    for word in raw.get("words", []):
        speaker = word.get("speaker_id") or "speaker_?"
        start, end = word.get("start"), word.get("end")
        last = segments[-1] if segments else None
        if word["type"] == "spacing":
            if last:
                last.text += word["text"]
            continue
        if last is None or last.speaker != speaker or (start is not None and start - last.end > TURN_GAP):
            last = Segment(start=start or 0.0, end=end or start or 0.0, speaker=speaker, text="")
            segments.append(last)
        last.text += word["text"]
        if end is not None:
            last.end = end
        if word["type"] == "audio_event":
            last.events.append(word["text"].strip("[]() "))
    for seg in segments:
        seg.text = seg.text.strip()
    return Transcript(
        provider="elevenlabs", model=model, language=raw.get("language_code"),
        duration=raw.get("audio_duration_secs") or (segments[-1].end if segments else 0.0),
        segments=[s for s in segments if s.text],
    )


class ElevenLabs(Provider):
    name = "elevenlabs"
    stt_price_per_min = {"scribe_v2": 0.22 / 60}

    def available(self) -> tuple[bool, str]:
        return (True, "") if os.environ.get("ELEVENLABS_API_KEY") else (False, "ELEVENLABS_API_KEY absente")

    def list_models(self) -> list[ModelInfo]:
        # Pas d'API de liste pour la transcription : liste statique.
        caps = {Cap.STT, Cap.DIARIZATION, Cap.AUDIO_EVENTS, Cap.WORD_TIMESTAMPS}
        return [ModelInfo(self.name, "scribe_v2", caps)]

    def transcribe(self, audio: Path, model: str, opts: TranscribeOptions) -> tuple[Transcript, list[dict]]:
        data: list[tuple[str, str]] = [
            ("model_id", model), ("diarize", "true"), ("tag_audio_events", "true"),
            ("timestamps_granularity", "word"),
        ]
        if opts.language:
            data.append(("language_code", opts.language))
        if opts.num_speakers:
            data.append(("num_speakers", str(opts.num_speakers)))
        data += [("keyterms", term) for term in opts.vocabulary]
        opts.progress("ElevenLabs : envoi en une requête, sans suivi possible")
        with audio.open("rb") as fh:
            resp = httpx.post(
                f"{API}/v1/speech-to-text", headers={"xi-api-key": os.environ["ELEVENLABS_API_KEY"]},
                data=form(data), files={"file": (audio.name, fh)}, timeout=3600.0)
        if resp.status_code >= 400:
            raise RuntimeError(f"ElevenLabs : HTTP {resp.status_code} {resp.text[:500]}")
        raw = resp.json()
        seconds = au.duration(audio)
        usage.record("elevenlabs", model, "transcription", audio_seconds=seconds, cost_usd=self.stt_cost(model, seconds))
        return normalize(raw, model), [raw]
