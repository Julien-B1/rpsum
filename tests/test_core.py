from rpsum.audio import plan_chunks
from rpsum.providers import Cap, ModelInfo
from rpsum.providers import elevenlabs, mistral
from rpsum.tasks import compatible


def test_plan_chunks_cuts_on_nearby_silence():
    chunks = plan_chunks(4000, [(990, 1010), (1500, 1504), (2900, 2910)], target=1000, window=120)
    assert chunks[0] == (0.0, 1000.0)          # milieu du silence 990-1010
    assert chunks[1] == (1000.0, 2000.0)       # pas de silence proche : coupe à la cible
    assert chunks[-1][1] == 4000 and all(a < b for a, b in chunks)
    assert [b for _, b in chunks[:-1]] == [a for a, _ in chunks[1:]]  # morceaux contigus


def test_plan_chunks_short_audio_is_one_chunk():
    assert plan_chunks(1100, [], target=1000) == [(0.0, 1100)]


def test_compatible_filters_by_capabilities():
    stt = ModelInfo("x", "stt", {Cap.STT, Cap.DIARIZATION})
    chat = ModelInfo("x", "chat", {Cap.CHAT, Cap.JSON_SCHEMA})
    assert compatible("transcribe", [stt, chat]) == [stt]
    assert compatible("summarize", [stt, chat]) == [chat]


def test_elevenlabs_groups_words_and_keeps_events():
    w = lambda text, start, end, spk, kind="word": {"text": text, "start": start, "end": end, "speaker_id": spk, "type": kind}
    raw = {"language_code": "fra", "words": [
        w("Bonjour", 0, 0.5, "speaker_0"), w(" ", 0.5, 0.6, "speaker_0", "spacing"), w("tous.", 0.6, 1, "speaker_0"),
        w("[rire]", 1.2, 1.8, "speaker_1", "audio_event"),
        w("Encore", 9, 9.5, "speaker_1"),
    ]}
    segs = elevenlabs.normalize(raw, "scribe_v2").segments
    assert [(s.speaker, s.text) for s in segs] == [("speaker_0", "Bonjour tous."), ("speaker_1", "[rire]"), ("speaker_1", "Encore")]
    assert segs[1].events == ["rire"]


def test_mistral_merges_shifts_and_renames():
    raw = {"segments": [
        {"text": "Un.", "start": 0, "end": 1, "speaker_id": "speaker_1"},
        {"text": "Deux.", "start": 1.5, "end": 2, "speaker_id": "speaker_1"},
        {"text": "Trois.", "start": 3, "end": 9, "speaker_id": "speaker_2"},
    ]}
    segs = mistral.normalize(raw, "m", shift=100, rename={"speaker_2": "c1_speaker_2"})
    assert [(s.speaker, s.text, s.start) for s in segs] == [("speaker_1", "Un. Deux.", 100), ("c1_speaker_2", "Trois.", 103)]
    assert mistral.pick_references(raw) == {"speaker_2": (3, 6)}


def test_quote_must_come_from_transcript():
    from rpsum.extract import find_quote, quote_found
    from rpsum.schema import Segment, Transcript
    assert quote_found("j'ai encore deux ouïes, les gamins", "Eh, je suis peut-être vieux, mais j'ai encore deux ouïes, les gamins. [rires]")
    assert quote_found("C'est le grand Schtroumpf !", "C'est le Grand Schtroumpf.")
    assert not quote_found("Je lance une boule de feu sur le dragon", "C'est le Grand Schtroumpf.")
    assert not quote_found("oui", "oui oui")  # trop court pour prouver quoi que ce soit
    t = Transcript(provider="x", model="y", segments=[
        Segment(id=i, start=i, end=i + 1, speaker="s", text=text)
        for i, text in enumerate(["Bonjour à tous.", "On aurait dû prendre l'autre couloir.", "Sans doute."])])
    assert find_quote(t, {"start_id": 0, "end_id": 0, "quote": "on aurait du prendre l'autre couloir"}) == 1
    assert find_quote(t, {"start_id": 0, "end_id": 2, "quote": "Une phrase jamais prononcée ici"}) is None


def test_links_carry_timestamp():
    from rpsum.extract import link
    assert link("https://www.youtube.com/watch?v=abc", 125.7) == "https://www.youtube.com/watch?v=abc&t=125s"
    assert link("https://www.twitch.tv/videos/1", 3725) == "https://www.twitch.tv/videos/1?t=1h2m5s"
    assert link(None, 5) is None


def test_preset_overrides_and_validation():
    import pytest
    from rpsum.summarize import load_preset
    settings = load_preset(None, {"length": "250", "format": "puces", "tone": None})
    assert settings["words"] == 250 and settings["format"] == "puces" and settings["tone"] == "neutre et clair"
    with pytest.raises(SystemExit):
        load_preset(None, {"format": "opera"})


def test_summary_quotes_are_checked_against_transcript():
    from rpsum.schema import Segment, Transcript
    from rpsum.summarize import unverified_quotes
    t = Transcript(provider="x", model="y", segments=[
        Segment(id=0, start=0, end=1, speaker="s", text="Paraît que c'est une sirène, tout ce que je sais moi.")])
    text = ("Le vieux dit : « Paraît que c'est une sirène ». Tessa répond : \"On dirait des livreurs de sushis.\" "
            "Il murmure : « Un accident. » Il cite « Élysia ».")
    assert unverified_quotes(text, t) == ["On dirait des livreurs de sushis.", "Un accident."]
