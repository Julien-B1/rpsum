"""Interface locale de rpsum. Lancement : uv run streamlit run app.py

L'interface ne fait aucun calcul elle-même : elle lance les commandes `rpsum` en tâche de fond, suit leur
journal, et affiche les fichiers produits dans runs/<id>/."""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pandas as pd
import streamlit as st

from rpsum import config, usage
from rpsum.extract import CATEGORIES
from rpsum.schema import timestamp
from rpsum.summarize import FORMATS, LENGTHS, SCOPES
from rpsum.tasks import TASKS

ROOT = Path(__file__).parent
RUNS = ROOT / "runs"
MODES = {"en-jeu": "En jeu", "narration": "Narration", "regles": "Règles", "hors-jeu": "Hors jeu"}

st.set_page_config(page_title="rpsum", page_icon="🎲", layout="wide")
CFG = config.load()


# ---------------------------------------------------------------- outils

def read_json(path: Path, default=None):
    return json.loads(path.read_text()) if path.exists() else default


def list_runs() -> list[str]:
    if not RUNS.is_dir():
        return []
    found = [p for p in RUNS.iterdir() if (p / "audio.opus").exists()]
    return [p.name for p in sorted(found, key=lambda p: p.stat().st_mtime, reverse=True)]


def job_paths(run_id: str) -> tuple[Path, Path]:
    return RUNS / run_id / "ui.log", RUNS / run_id / "ui.pid"


def job_running(run_id: str) -> bool:
    _, pid_file = job_paths(run_id)
    if not pid_file.exists():
        return False
    try:
        pid = int(pid_file.read_text())
        # Un processus terminé mais pas encore récolté reste visible : son état « Z » le trahit.
        state = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
        return state != "Z"
    except (OSError, ValueError, IndexError):
        return False


def launch(run_id: str, args: list[str]) -> None:
    """Lance `rpsum <args>` détaché de l'interface, journal dans runs/<id>/ui.log."""
    (RUNS / run_id).mkdir(parents=True, exist_ok=True)
    log, pid_file = job_paths(run_id)
    with log.open("w") as out:
        out.write(f"$ rpsum {' '.join(args)}\n")
        out.flush()
        proc = subprocess.Popen([sys.executable, "-m", "rpsum.cli", *args], cwd=ROOT, stdout=out,
                                stderr=subprocess.STDOUT, start_new_session=True)
    pid_file.write_text(str(proc.pid))


@st.cache_data(ttl=300, show_spinner="Lecture des modèles disponibles…")
def models_for(task: str) -> dict[str, list[str]]:
    """Modèles compatibles avec une tâche, par fournisseur disponible."""
    from rpsum.providers import PROVIDERS
    from rpsum.tasks import compatible
    out: dict[str, list[str]] = {}
    for name, cls in PROVIDERS.items():
        provider = cls()
        if provider.available()[0]:
            found = [m.id for m in compatible(task, provider.list_models())]
            if found:
                out[name] = found
    return out


def model_picker(task: str, key: str) -> list[str]:
    """Choix du fournisseur et du modèle d'une tâche. Renvoie les options de ligne de commande."""
    default = CFG.get("tasks", {}).get(task, {})
    available = models_for(task)
    if not available:
        st.warning(f"Aucun modèle disponible pour « {task} ».")
        return []
    providers = list(available)
    left, right = st.columns(2)
    provider = left.selectbox("Fournisseur", providers, key=f"{key}-provider",
                              index=providers.index(default["provider"]) if default.get("provider") in providers else 0)
    ids = available[provider]
    model = right.selectbox("Modèle", ids, key=f"{key}-model",
                            index=ids.index(default["model"]) if default.get("model") in ids else 0)
    return ["--provider", provider, "--model", model]


@st.cache_data(ttl=300, show_spinner="Lecture ElevenLabs…")
def elevenlabs_cached() -> dict:
    try:
        return usage.elevenlabs_status()
    except httpx.HTTPError as exc:
        return {"error": str(exc)}


def usage_panel() -> None:
    """Consommation : journal local des appels (Mistral n'a pas d'API de quota) et état ElevenLabs."""
    rows = usage.read_ledger()
    month = time.strftime("%Y-%m")
    by_provider = usage.totals(rows, since=month)
    st.markdown(f"**Ce mois-ci ({month}), d'après le journal local**")
    if not by_provider:
        st.caption("Aucun appel noté. Le journal (runs/usage.jsonl) commence au 2026-11-10.")
    for name, t in sorted(by_provider.items()):
        parts = [f"{t['calls']} appel{'s' if t['calls'] > 1 else ''}"]
        if t["prompt_tokens"] or t["completion_tokens"]:
            parts.append(f"{t['prompt_tokens']:,} jetons envoyés, {t['completion_tokens']:,} reçus".replace(",", " "))
        if t["audio_seconds"]:
            parts.append(f"{t['audio_seconds'] / 3600:.1f} h d'audio")
        cost = f" ≈ {t['cost_usd']:.3f} $" if t["cost_usd"] else ""
        st.markdown(f"- {name} : {', '.join(parts)}{cost}")

    st.markdown("**Mistral**")
    last = next((r.get("limits") for r in reversed(rows) if r.get("provider") == "mistral" and r.get("limits")), None)
    if st.button("Lire les limites de débit", key="mistral-limits", help="Appel de 1 jeton, coût négligeable."):
        last = usage.mistral_limits()
    if last:
        labels = {"limit-tokens-minute": "jetons / min", "remaining-tokens-minute": "jetons restants / min",
                  "limit-req-minute": "requêtes / min", "remaining-req-minute": "requêtes restantes / min",
                  "limit-tokens-month": "jetons / mois", "remaining-tokens-month": "jetons restants / mois"}
        st.caption(" · ".join(f"{labels.get(k, k)} : {v}" for k, v in last.items() if k in labels) or str(last))
    st.caption(f"Pas d'API de quota ni de solde chez Mistral. Montants réels : [console]({usage.MISTRAL_CONSOLE}).")

    st.markdown("**ElevenLabs (30 derniers jours)**")
    if st.button("Actualiser", key="el-refresh"):
        elevenlabs_cached.clear()
    status = elevenlabs_cached()
    if status.get("error"):
        st.warning(status["error"])
        return
    sub = status.get("subscription")
    if sub and sub.get("limit"):
        reset = time.strftime("%Y-%m-%d", time.localtime(sub["reset"])) if sub.get("reset") else "?"
        st.progress(min(sub["used"] / sub["limit"], 1.0),
                    text=f"{sub['used']:,} / {sub['limit']:,} crédits ({sub.get('tier')}), remise à zéro le {reset}")
    elif status.get("subscription_error"):
        st.caption("Limite de l'abonnement illisible : la clé n'a pas la permission `user_read`. "
                   f"Ajoute-la sur [ElevenLabs]({usage.ELEVENLABS_CONSOLE}) pour voir le solde ici.")
    products = status.get("by_product", {})
    if products:
        st.markdown("\n".join(f"- {name} : {sum(values):,.0f} crédits" for name, values in products.items()))
    elif "stats_error" in status:
        st.caption(status["stats_error"])
    else:
        st.caption("Aucune consommation.")


# ---------------------------------------------------------------- barre latérale

with st.sidebar:
    st.title("🎲 rpsum")
    runs = list_runs()
    chosen = st.selectbox("Session", runs, format_func=lambda r: (read_json(RUNS / r / "source.json", {}) or {}).get("title") or r) if runs else None

    with st.expander("Nouvelle session", expanded=not runs):
        with st.form("new-run"):
            url = st.text_input("URL YouTube ou Twitch, ou chemin d'un fichier")
            new_id = st.text_input("Identifiant", help="Lettres, chiffres, tirets. Vide : construit depuis l'URL.")
            context_text = st.text_area("Contexte de campagne (Markdown libre, liens acceptés)", height=140,
                                        help="Noms, lieux, participants, liens Google Docs ou fichiers locaux.")
            presets = sorted(p.stem for p in (ROOT / "presets").glob("*.toml"))
            wanted = st.multiselect("Résumés à produire", presets, default=CFG.get("run", {}).get("presets", ["fiche"]))
            if st.form_submit_button("Lancer", type="primary") and url:
                run_id = new_id.strip() or f"session-{time.strftime('%Y%m%d-%H%M%S')}"
                args = ["run", url.strip(), "--id", run_id]
                if context_text.strip():
                    (RUNS / run_id).mkdir(parents=True, exist_ok=True)
                    (RUNS / run_id / "context.ui.md").write_text(context_text)
                    args += ["--context", str(RUNS / run_id / "context.ui.md")]
                for preset in wanted:
                    args += ["--preset", preset]
                launch(run_id, args)
                st.session_state["watch"] = run_id
                st.rerun()

    with st.expander("Consommation API"):
        usage_panel()

if not chosen and not st.session_state.get("watch"):
    st.info("Aucune session. Lance-en une depuis la barre latérale.")
    st.stop()

run_id = chosen or st.session_state["watch"]
RUN = RUNS / run_id
source = read_json(RUN / "source.json", {}) or {}


# ---------------------------------------------------------------- en-tête et suivi

st.header(source.get("title") or run_id)
facts = [source.get("channel"), timestamp(source["duration"]) if source.get("duration") else None, source.get("url")]
st.caption(" · ".join(str(f) for f in facts if f))


# Rafraîchissement automatique seulement pendant un traitement : sinon l'indicateur d'activité de Streamlit
# (icône animée et bouton Stop, en haut à droite) tournerait en permanence.
@st.fragment(run_every=3 if job_running(run_id) else None)
def job_status() -> None:
    log, _ = job_paths(run_id)
    if not log.exists():
        return
    running = job_running(run_id)
    lines = log.read_text(errors="replace").splitlines()
    if running:
        st.info(f"Traitement en cours : {lines[-1] if lines else '…'}")
    elif st.session_state.get("was-running") == run_id:
        st.session_state.pop("was-running")
        st.rerun()  # le traitement vient de finir : on recharge les résultats
    if running:
        st.session_state["was-running"] = run_id
    with st.expander("Journal du dernier traitement", expanded=running):
        st.code("\n".join(lines[-25:]) or "(vide)", language=None)


job_status()
busy = job_running(run_id)

tab_summary, tab_highlights, tab_transcript, tab_cast, tab_context, tab_run = st.tabs(
    ["Résumés", "Passages", "Transcript", "Distribution", "Contexte", "Pipeline"])


# ---------------------------------------------------------------- résumés

with tab_summary:
    summaries = sorted(RUN.glob("summary.*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
    left, right = st.columns([2, 1])
    with left:
        if summaries:
            pick = st.radio("Résumé", summaries, horizontal=True, format_func=lambda p: p.name[8:-3])
            text = pick.read_text()
            st.caption(f"{len(text.split())} mots")
            st.markdown(text)
            st.download_button("Télécharger", text, file_name=pick.name)
        else:
            st.info("Aucun résumé pour l'instant.")
    with right:
        st.subheader("Nouveau résumé")
        presets = sorted(p.stem for p in (ROOT / "presets").glob("*.toml"))
        preset = st.selectbox("Préréglage", ["(aucun)", *presets])
        tone = st.text_input("Ton", placeholder="pince-sans-rire, épique, rapport de police…")
        length = st.selectbox("Longueur", ["(préréglage)", *LENGTHS, "nombre de mots"])
        words = st.number_input("Mots", 50, 3000, 300, 50) if length == "nombre de mots" else None
        fmt = st.selectbox("Format", ["(préréglage)", *FORMATS])
        pov = st.text_input("Point de vue", placeholder="Saigetsu, à la première personne")
        scope = st.selectbox("Périmètre", ["(préréglage)", *SCOPES])
        extra = st.text_area("Consigne supplémentaire", height=70)
        name = st.text_input("Nom du résumé", placeholder="vide : nom du préréglage")
        with st.expander("Modèle"):
            model_args = model_picker("summarize", "summary")
        if st.button("Générer", type="primary", disabled=busy or not (RUN / "transcript.json").exists()):
            args = ["summarize", run_id, *model_args]
            pairs = {"--preset": None if preset == "(aucun)" else preset, "--tone": tone or None,
                     "--length": str(words) if words else (None if length == "(préréglage)" else length),
                     "--format": None if fmt == "(préréglage)" else fmt, "--pov": pov or None,
                     "--scope": None if scope == "(préréglage)" else scope, "--instructions": extra or None,
                     "--name": name or None}
            for flag, value in pairs.items():
                if value:
                    args += [flag, value]
            launch(run_id, args)
            st.rerun()


# ---------------------------------------------------------------- passages

with tab_highlights:
    items = (read_json(RUN / "highlights.json", {}) or {}).get("items", [])
    if not items:
        st.info("Aucun passage extrait pour l'instant.")
    else:
        top, minimum = st.columns([3, 1])
        wanted_categories = top.multiselect("Catégories", list(CATEGORIES), default=list(CATEGORIES),
                                            format_func=CATEGORIES.get)
        floor = minimum.slider("Note minimale", 1, 10, 7)
        shown = [i for i in items if i["category"] in wanted_categories and i["score"] >= floor]
        st.caption(f"{len(shown)} passage(s) sur {len(items)}")
        for item in sorted(shown, key=lambda i: i["start"]):
            with st.container(border=True):
                head, note = st.columns([5, 1])
                head.markdown(f"**{item['title']}** · {CATEGORIES[item['category']]}")
                note.markdown(f"**{item['score']}/10**")
                stamp = f"{timestamp(item['start'])} – {timestamp(item['end'])}"
                st.markdown(f"[{stamp}]({item['url']})" if item.get("url") else stamp)
                st.markdown(f"> {item['quote']}\n>\n> — {item['quote_by']}")
                st.write(item["why"])
                if item.get("caption"):
                    st.caption(f"Légende : {item['caption']}")
                clip = RUN / item["clip"] if item.get("clip") else None
                if clip and clip.exists():
                    st.audio(str(clip))
    with st.expander("Relancer l'extraction"):
        extract_args = model_picker("extract", "extract")
        clips = st.checkbox("Découper les extraits audio (note 8 et plus)", value=True)
        if st.button("Extraire", disabled=busy or not (RUN / "transcript.json").exists()):
            launch(run_id, ["extract", run_id, "--force", *(["--clips"] if clips else []), *extract_args])
            st.rerun()


# ---------------------------------------------------------------- transcript

with tab_transcript:
    data = read_json(RUN / "transcript.json")
    if not data:
        st.info("Pas encore de transcript.")
    else:
        rows = [{"Heure": timestamp(s["start"] + data.get("offset", 0)), "Qui": s.get("player") or s["speaker"],
                 "Personnage": s.get("character") or "", "Mode": MODES.get(s.get("mode"), ""), "Texte": s["text"],
                 "Doute": "⚠" if (s.get("confidence") or 1) < 0.5 else ""} for s in data["segments"]]
        frame = pd.DataFrame(rows)
        a, b, c = st.columns([2, 2, 3])
        who = a.multiselect("Qui", sorted(frame["Qui"].unique()))
        mode = b.multiselect("Mode", [m for m in MODES.values() if m in set(frame["Mode"])])
        query = c.text_input("Recherche dans le texte")
        if who:
            frame = frame[frame["Qui"].isin(who)]
        if mode:
            frame = frame[frame["Mode"].isin(mode)]
        if query:
            frame = frame[frame["Texte"].str.contains(query, case=False, regex=False)]
        st.caption(f"{len(frame)} réplique(s) sur {len(rows)} · transcription : {data['provider']} / {data['model']}")
        st.dataframe(frame, hide_index=True, width="stretch", height=560,
                     column_config={"Texte": st.column_config.TextColumn(width="large")})
        if (RUN / "transcript.md").exists():
            st.download_button("Télécharger le script (Markdown)", (RUN / "transcript.md").read_text(),
                               file_name=f"{run_id}-transcript.md")


# ---------------------------------------------------------------- distribution

with tab_cast:
    cast = read_json(RUN / "cast.json")
    if not cast:
        st.info("Pas encore de distribution.")
    else:
        st.write("Corrige ici qui est qui. Deux voix qui portent le même nom de joueur sont traitées comme une seule personne.")
        table = pd.DataFrame([{"Voix": e["speaker"], "Joueur": e["player"], "Rôle": e["role"],
                               "Personnages": ", ".join(e["characters"]), "Confiance": e["confidence"],
                               "Indice": e["evidence"]} for e in cast["speakers"]])
        edited = st.data_editor(
            table, hide_index=True, width="stretch", disabled=["Voix", "Confiance", "Indice"],
            column_config={"Rôle": st.column_config.SelectboxColumn(options=["mj", "joueur", "autre"]),
                           "Indice": st.column_config.TextColumn(width="large")})
        with st.expander("Modèle"):
            identify_args = model_picker("identify", "identify")
        save, redo = st.columns(2)
        if save.button("Enregistrer et réannoter le transcript", type="primary", disabled=busy):
            for entry, row in zip(cast["speakers"], edited.to_dict("records")):
                entry["player"], entry["role"] = row["Joueur"].strip(), row["Rôle"]
                entry["characters"] = [c.strip() for c in row["Personnages"].split(",") if c.strip()]
            (RUN / "cast.json").write_text(json.dumps(cast, ensure_ascii=False, indent=2))
            launch(run_id, ["identify", run_id, *identify_args])
            st.rerun()
        if redo.button("Recalculer la distribution", disabled=busy):
            launch(run_id, ["identify", run_id, "--redo-cast", *identify_args])
            st.rerun()


# ---------------------------------------------------------------- contexte

with tab_context:
    left, right = st.columns(2)
    with left:
        st.subheader("Fiche de contexte")
        if (RUN / "context.md").exists():
            st.markdown((RUN / "context.md").read_text())
        else:
            st.info("Pas encore de fiche de contexte.")
        frames = sorted((RUN / "frames").glob("*.jpg")) if (RUN / "frames").is_dir() else []
        if frames:
            st.image(str(frames[0]), caption="Image lue pour relever les participants")
    with right:
        st.subheader("Fichier de contexte")
        st.caption("Markdown libre : noms, lieux, participants, extraits, liens Google Docs ou fichiers locaux.")
        current = (RUN / "context.input.md").read_text() if (RUN / "context.input.md").exists() else ""
        raw = st.text_area("Contenu", current, height=420, label_visibility="collapsed")
        with st.expander("Modèle"):
            context_args = model_picker("context", "context")
        if st.button("Enregistrer et reconstruire la fiche", type="primary", disabled=busy):
            (RUN / "context.ui.md").write_text(raw)
            launch(run_id, ["context", run_id, str(RUN / "context.ui.md"), *context_args])
            st.rerun()
        st.caption("La fiche sert au lexique de transcription : pour qu'elle agisse sur le texte, relance le "
                   "pipeline depuis la transcription (onglet Pipeline).")


# ---------------------------------------------------------------- pipeline

with tab_run:
    st.subheader("Relancer le pipeline")
    st.write("Sans option, la transcription et l'identification existantes sont gardées : seuls les résumés et "
             "l'extraction sont refaits.")
    choice = st.radio("Reprendre à partir de", ["résumés et extraction", "identification", "transcription", "contexte"],
                      horizontal=True)
    flags = {"résumés et extraction": [], "identification": ["--from", "identify"],
             "transcription": ["--from", "transcribe"], "contexte": ["--from", "context"]}[choice]
    if choice == "transcription":
        st.warning("La transcription sera refaite et facturée.")
    if st.button("Relancer", disabled=busy):
        launch(run_id, ["run", run_id, *flags])
        st.rerun()

    st.subheader("Réglages par défaut (config.toml)")
    st.dataframe(pd.DataFrame([{"Tâche": task, "Fournisseur": CFG.get("tasks", {}).get(task, {}).get("provider", ""),
                                "Modèle": CFG.get("tasks", {}).get(task, {}).get("model", "")} for task in TASKS]),
                 hide_index=True, width="stretch")

    st.subheader("Journal des étapes")
    steps = (read_json(RUN / "run.json", {}) or {}).get("steps", [])
    if steps:
        log_rows = [{"Quand": s["at"].replace("T", " "), "Étape": s["step"], "Fournisseur": s.get("provider", ""),
                     "Modèle": s.get("model", ""), "Durée (s)": s.get("elapsed_seconds"),
                     "Coût estimé ($)": s.get("estimated_cost_usd"),
                     "Détail": s.get("output") or ", ".join(f"{k}={v}" for k, v in s.items()
                                                            if k in ("segments", "speakers", "annotated", "kept", "rejected", "words"))}
                    for s in steps]
        st.dataframe(pd.DataFrame(log_rows), hide_index=True, width="stretch")
        total = sum(s.get("estimated_cost_usd") or 0 for s in steps)
        st.caption(f"Coût de transcription estimé, cumulé : {total:.2f} $. Les appels de texte ne sont pas chiffrés.")
    else:
        st.info("Aucune étape enregistrée.")
