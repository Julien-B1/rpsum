# rpsum

`rpsum` transforme l'enregistrement d'une partie de jeu de rôle (vidéo YouTube, replay Twitch ou fichier local) en transcript annoté, résumés et sélection de passages.

## En une commande

```bash
uv run rpsum run "https://www.youtube.com/watch?v=XXXX" --id ma-session --context ma-campagne.md
```

Ou depuis l'[[Interface]] : `uv run streamlit run app.py`.

## Les étapes

| Étape | Commande | Ce qu'elle produit |
|---|---|---|
| Extraction | `rpsum ingest` | l'audio de la session |
| Contexte | `rpsum context` | la fiche des noms, lieux et participants |
| Transcription | `rpsum transcribe` | le texte, découpé par locuteur |
| Identification | `rpsum identify` | qui est MJ, qui joue quel personnage, et le mode de chaque réplique |
| Résumé | `rpsum summarize` | un résumé au ton, à la longueur et au format voulus |
| Extraction de passages | `rpsum extract` | moments forts, bêtisier, mèmes |

Chaque étape lit le résultat de la précédente. Une étape déjà faite n'est pas refaite : on peut produire dix résumés sans repayer la transcription.

## Pages

- [[Installation]]
- [[Utilisation]] — une session de bout en bout
- [[Interface]] — la même chose dans le navigateur
- [[Contexte de campagne]] — noms, lieux, participants
- [[Fournisseurs et modèles]] — choisir l'API et le modèle de chaque tâche
- [[Résumés]] — tons, longueurs, formats, préréglages
- [[Fichiers produits]]
- [[Dépannage et limites]]

## État

C'est un POC. Les fournisseurs locaux (Ollama, llama.cpp) sont codés pour les tâches texte mais n'ont pas encore tourné sur un vrai serveur. La transcription locale n'existe pas encore. Le plan, les résultats d'essais et le backlog sont dans `PLAN.md`.
