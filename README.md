# rpsum

POC de résumé de parties de jeu de rôle enregistrées. À partir d'une vidéo YouTube ou d'un replay Twitch :

1. `ingest` — extrait l'audio.
2. `context` — tire d'un fichier libre et de l'écran de la vidéo les noms, lieux et participants.
3. `transcribe` — transcrit et sépare les voix (ElevenLabs, Mistral).
4. `identify` — retrouve MJ, joueurs et personnages, puis annote chaque réplique (en jeu, hors jeu, narration, règles).
5. `summarize` — résume selon un ton, une longueur et un format.
6. `extract` — sort moments forts, bêtisier et mèmes, avec citations vérifiées.

Chaque tâche choisit son fournisseur et son modèle (`config.toml`). Fournisseurs : Mistral, ElevenLabs, Ollama, llama.cpp.

```bash
uv sync
cp .env.example .env   # puis renseigner les clés
uv run rpsum doctor
uv run rpsum run "https://www.youtube.com/watch?v=..." --id ma-session --context ma-campagne.md
uv run rpsum summarize ma-session --preset chronique   # un résumé de plus, sans rien retranscrire
uv run streamlit run app.py                            # interface locale
```

Relancer `rpsum run ma-session` garde la transcription et l'identification, et refait résumés et extraction. `--force` refait tout depuis la transcription.

Mode d'emploi complet : `docs/wiki/` (source du wiki du dépôt). Plan, résultats d'essais et backlog : `PLAN.md`.
