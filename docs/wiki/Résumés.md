# Résumés

Le résumé se fait en deux temps. D'abord des fiches de scène factuelles (`scenes.json`), calculées une seule fois. Ensuite la rédaction, qui applique le ton, la longueur et le format. Changer de ton ne refait donc que la rédaction.

## Paramètres

| Option | Valeurs | Défaut |
|---|---|---|
| `--tone` | texte libre : « épique », « pince-sans-rire », « rapport de police »… | neutre et clair |
| `--length` | `court` (150 mots), `moyen` (400), `long` (900), ou un nombre de mots | `moyen` |
| `--format` | `recit`, `puces`, `fiche`, `article`, `discord` | `recit` |
| `--pov` | texte libre : « narrateur extérieur », « Hécate, à la première personne »… | narrateur extérieur |
| `--scope` | `en-jeu` (la fiction seule) ou `tout` (avec l'ambiance de la table) | `en-jeu` |
| `--instructions` | consigne supplémentaire, en texte libre | aucune |
| `--name` | nom du fichier : `summary.<nom>.md` | nom du préréglage, sinon `defaut` |
| `--redo-scenes` | recalcule les fiches de scène | non |

## Formats

- `recit` : paragraphes continus.
- `puces` : liste chronologique.
- `fiche` : fiche de campagne avec personnages, PNJ, lieux, objets, décisions et pistes ouvertes.
- `article` : article de gazette avec titre, chapeau et intertitres.
- `discord` : message court, moins de 1800 caractères.

## Préréglages

Un préréglage est un fichier `presets/<nom>.toml` qui fixe plusieurs paramètres d'un coup. Les options de la ligne de commande l'emportent.

| Préréglage | Usage |
|---|---|
| `fiche` | fiche factuelle pour préparer la session suivante |
| `chronique` | chronique épique, longue |
| `dark-fantasy` | chronique sombre, sans aucun humour |
| `discord` | récap court et drôle, avec l'ambiance de la table |
| `journal` | journal intime d'un personnage, à choisir avec `--pov` |

```bash
uv run rpsum summarize ma-session --preset journal --pov "Hécate, à la première personne" --name journal-hecate
```

Pour créer le sien, copier un fichier de `presets/` et changer les valeurs :

```toml
tone = "dark fantasy : sombre, grave, oppressant. Aucun humour."
length = "long"
format = "recit"
pov = "chroniqueur extérieur, au passé"
scope = "en-jeu"
instructions = "Insiste sur la menace et le coût des choix."
```

## Garde-fous

- **Longueur.** Si le texte dépasse la consigne de plus de 20 %, une passe de coupe est lancée. Les formats courts restent parfois un peu au-dessus.
- **Répliques.** Le résumé ne doit contenir aucune réplique entre guillemets qui n'existe pas dans le transcript. Celles qui sont repérées sont retirées, et la commande affiche un avertissement s'il en reste.
- **Ce qui n'est pas contrôlé.** Un ton humoristique peut enjoliver un détail en dehors des guillemets. Pour un compte rendu fiable, préférer `fiche` ou un ton neutre.
