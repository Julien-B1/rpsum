# Contexte de campagne

Un transcript automatique écorche les noms inventés, et un modèle ne devine pas qui joue quoi. Le contexte de campagne règle les deux : on donne à `rpsum` un fichier Markdown libre, il en tire une fiche structurée qui sert à toutes les étapes.

## Ce qu'on fournit

Un fichier `.md` sans format imposé : notes du MJ, listes de noms, extraits, résumés des sessions passées, liens. Un modèle se trouve dans `examples/contexte.md`.

```bash
uv run rpsum run "https://www.youtube.com/watch?v=XXXX" --id ma-session --context ma-campagne.md
# ou, sur un run existant :
uv run rpsum context ma-session ma-campagne.md
```

## Ce qui est lu

| Source | Traitement |
|---|---|
| Le texte du fichier | lu tel quel |
| Liens Google Docs, Sheets, Slides | exportés en texte. Le document doit être partagé en « toute personne disposant du lien ». |
| Fichiers locaux `.md`, `.txt`, `.csv`, `.json`, `.pdf` | lus. Chemin absolu, ou relatif au fichier de contexte. |
| Images `.png`, `.jpg`, `.webp` | lues par le modèle de vision |
| Autres liens web | listés, non suivis |
| Titre et description de la vidéo | ajoutés automatiquement |
| Écran de la vidéo | trois images capturées en début de session, voir plus bas |

Une source illisible n'arrête pas le traitement : elle apparaît en échec dans la section « Sources » de la fiche.

## Lecture de l'écran

Beaucoup de vidéos affichent, près de chaque webcam, le pseudo du participant et le nom de son personnage. `rpsum` capture trois images dans la première minute et demande à un modèle de vision de relever ces étiquettes. Si l'URL porte une position de départ (`&t=229s`), la minute commence là : c'est utile quand la vidéo débute par un écran d'attente.

Une étiquette « A - B » ne dit pas laquelle des deux moitiés est le pseudo. Le modèle tranche d'après l'étiquette du MJ (« Maître du Jeu - Karu » implique « personnage - pseudo ») et les autres textes à l'écran. Le résultat est dans `overlay.json`, avec la justification. En cas d'erreur, écrire la bonne distribution dans le fichier de contexte : il l'emporte sur l'écran.

## Ce qui est produit

- `context.json` : la fiche structurée. Participants (pseudo, rôle, personnage), personnages joueurs, PNJ, lieux, factions, objets, termes de l'univers. Chaque entrée a un nom officiel, des variantes et une description.
- `context.md` : la même fiche, lisible, avec l'état de chaque source.

## À quoi sert la fiche

| Étape | Usage |
|---|---|
| `transcribe` | les noms deviennent le lexique du modèle de transcription (100 noms au plus chez Mistral) |
| `identify` | MJ, joueurs et personnages sont donnés comme certains, et les voix en trop sont rattachées à ces personnes |
| `summarize`, `extract` | l'univers et l'orthographe officielle des noms sont rappelés dans chaque prompt |

## Mise à jour

La fiche n'est reconstruite que si ses entrées changent (fichier, description, écran). Pour forcer : `rpsum context <id> --force`.

Modifier le contexte ne retranscrit pas la session. Pour que le nouveau lexique agisse sur le texte : `rpsum run <id> --from transcribe`.

Le modèle qui lit le contexte et celui qui lit les images se règlent dans `config.toml` (`[tasks.context]`, `[tasks.vision]`).
