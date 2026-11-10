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


def test_context_gathers_links_and_reports_failures(tmp_path):
    from rpsum.context import gather
    (tmp_path / "notes.md").write_text("Le PNJ s'appelle Talion.")
    (tmp_path / "plan.png").write_bytes(b"x")
    raw = ("Voir [les notes](notes.md), [la carte](plan.png), [un absent](rien.txt) "
           "et https://exemple.org/page. Ainsi que /chemin/inexistant/fiche.txt et dossier/relatif.md, fin.")
    sources, images = gather(raw, tmp_path)
    status = {s["ref"]: s["status"] for s in sources}
    assert status["notes.md"] == "lu" and "Talion" in sources[1]["text"]
    assert status["rien.txt"].startswith("échec") and status["/chemin/inexistant/fiche.txt"].startswith("échec")
    assert status["https://exemple.org/page"].startswith("non suivi")
    assert status["dossier/relatif.md"].startswith("échec")
    assert len(sources) == 7  # le fichier, notes.md, plan.png, rien.txt, deux chemins nus, un lien web
    assert images == [tmp_path / "plan.png"]


def test_context_merge_vocabulary_and_hints():
    from rpsum.context import hints, merge, prompt_block, vocabulary
    entity = lambda name, aliases=(), description="": {"name": name, "aliases": list(aliases), "description": description}
    blank = {"title": None, "system": None, "setting": "", "background": "", "people": [],
             "characters": [], "npcs": [], "places": [], "factions": [], "items": [], "terms": []}
    one = {**blank, "title": "Void", "people": [{"name": "Karu", "aliases": [], "role": "mj", "character": None},
                                                {"name": "Jonda", "aliases": [], "role": "joueur", "character": "Saigetsu"}],
           "npcs": [entity("Talion", ["le tavernier"])]}
    two = {**blank, "title": "Autre", "npcs": [entity("talion", ["Tal"], "Tavernier endeuillé"), entity("Corven")]}
    merged = merge([one, two])
    assert merged["title"] == "Void" and [n["name"] for n in merged["npcs"]] == ["Talion", "Corven"]
    assert merged["npcs"][0]["aliases"] == ["le tavernier", "Tal"] and merged["npcs"][0]["description"] == "Tavernier endeuillé"
    assert vocabulary(merged) == ["Karu", "Jonda", "Saigetsu", "Talion", "Corven"]
    assert hints(merged) == {"gm": "Karu", "players": [{"name": "Jonda", "character": "Saigetsu"}],
                             "characters": ["Saigetsu"], "people": 2}
    assert "Talion (Tavernier endeuillé) [aussi : le tavernier, Tal]" in prompt_block(merged)
    assert prompt_block(None) == ""


def test_url_start_and_resume_rules():
    from rpsum.pipeline import DOWNSTREAM, is_annotated
    from rpsum.schema import Segment, Transcript
    from rpsum.vision import url_start
    assert url_start("https://www.youtube.com/watch?v=abc&t=229s") == 229
    assert url_start("https://www.twitch.tv/videos/1?t=1h2m5s") == 3725
    assert url_start("https://www.youtube.com/watch?v=abc") == 0
    raw = Transcript(provider="x", model="y", segments=[Segment(start=0, end=1, speaker="s", text="a")])
    assert not is_annotated(raw)
    raw.segments[0].mode = "en-jeu"
    assert is_annotated(raw)
    assert "cast.json" in DOWNSTREAM["transcribe"] and "cast.json" not in DOWNSTREAM["identify"]


def test_fix_names_is_conservative():
    from rpsum.context import fix_names
    names = ["Gontrand", "Grimar", "Jonda", "Karu", "Bronk", "La secte de l'IA"]
    text, count = fix_names("Gontran et Grimgar suivent Jondat. Gontrand grimpe. Karl et Grimer attendent, grimar aussi.", names)
    assert text == "Gontrand et Grimar suivent Jonda. Gontrand grimpe. Karl et Grimer attendent, grimar aussi."
    assert count == 3


def test_summary_fence_is_stripped_and_gm_is_not_a_character():
    from rpsum.llm import line
    from rpsum.schema import Segment
    from rpsum.summarize import cast_text, strip_fence
    assert strip_fence("```markdown\n# Titre\nTexte\n```") == "# Titre\nTexte"
    assert strip_fence("Texte simple") == "Texte simple"
    gm = Segment(id=3, start=0, end=1, speaker="s", text="Vous êtes qui ?", player="Karu", role="mj", character="le vieux", mode="en-jeu")
    assert line(gm) == "3 [00:00:00] MJ / le vieux (en-jeu): Vous êtes qui ?"
    cast = {"speakers": [{"speaker": "s", "player": "Karu", "role": "mj", "characters": []},
                         {"speaker": "t", "player": "Kratos", "role": "joueur", "characters": ["Grimar"]}]}
    assert "absente de la fiction" in cast_text(cast) and "Son personnage dans la fiction : Grimar" in cast_text(cast)
    assert "Karu" not in cast_text(cast)
    gm.character = None
    assert line(gm) == "3 [00:00:00] MJ / PNJ non nommé (en-jeu): Vous êtes qui ?"


def test_npc_name_cleanup_keeps_real_names():
    from rpsum.identify import clean_npc
    assert clean_npc("Karu (PNJ)") == "Karu"
    assert clean_npc("la spécialiste des armes (PNJ)") == "la spécialiste des armes"
    assert clean_npc("Sigmund") == "Sigmund"
    assert clean_npc(None) is None and clean_npc("(PNJ)") is None
