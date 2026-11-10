# Dépannage et limites

## Problèmes courants

**YouTube refuse le téléchargement, ou « Signature solving failed ».**
Vérifier que `bin/deno` existe (`uv run rpsum doctor`). Mettre `yt-dlp` à jour : `uv lock --upgrade-package yt-dlp && uv sync`. En dernier recours, télécharger la vidéo autrement et donner le fichier à `rpsum ingest`.

**Replay Twitch réservé aux abonnés.**
Non géré pour l'instant. Passer par un fichier local.

**« Modèle … incompatible avec … ».**
Le modèle n'a pas les capacités de la tâche. Le message liste ceux qui conviennent. Voir aussi `rpsum models --task <tâche>`.

**« Fournisseur … indisponible ».**
Clé absente de `.env`, ou serveur local éteint ou mal adressé.

**HTTP 429 chez Mistral.**
Limite de débit. Les appels sont relancés automatiquement, avec une attente croissante. Éviter de lancer plusieurs commandes en parallèle.

**Trop de locuteurs, ou une personne coupée en deux.**
Relancer `transcribe` avec `--speakers N`. Sinon, donner le même `player` aux deux identifiants dans `cast.json`.

**Noms propres mal écrits.**
Les lister dans un fichier et relancer `transcribe` avec `--vocab`.

**Distribution fausse.**
Corriger `cast.json` à la main, puis relancer `rpsum identify <id>`.

## Limites connues

- **Parole superposée.** Quand plusieurs personnes parlent en même temps, la séparation des voix se trompe. Des répliques de joueurs se retrouvent attribuées au MJ.
- **Intonation.** Seuls les sons francs (rires, soupirs) sont signalés, et seulement par ElevenLabs.
- **Noms propres dans les résumés.** Un même nom peut s'écrire de plusieurs façons d'une scène à l'autre tant qu'il n'est pas dans le lexique.
- **Notes des passages.** L'extraction note généreusement : beaucoup de passages reçoivent 8 ou plus.
- **Local.** Pas de transcription locale. Ollama et llama.cpp ne sont pas encore validés.
- **Mesure.** La justesse de l'identification a été jugée à la lecture, pas mesurée contre une annotation de référence.
