# Pertinence des tenues et répétitions

## Problème reproduit

Le relevé `relevance-before.json` reproduit les articles transmis par l'utilisateur avec le vrai RAG hybride et le vrai score BO1. Pour isoler le classement, les plans de ces trois demandes étaient fournis par des fixtures explicites, sans présenter cela comme une génération LoRA :

| Demande | Avant correction |
| --- | --- |
| Deux tenues pour une sortie | Chemise en jean bleue, jean bleu/noir, produit simplement nommé « shoes » |
| Une tenue pour dîner | Même chemise en jean, jean bleu et mêmes chaussures |
| Une tenue de sport | Même chemise en jean, jean noir et mêmes chaussures |

Les scores de pertinence de ces tenues restaient proches de 0,92 pour les trois demandes. Avec un poids BO1 de 0,65, de faibles différences de recherche ne pouvaient pas contrebalancer les mêmes combinaisons très bien notées par BO1. Ce score évalue une compatibilité apprise ; il ne prouve pas l'adéquation à une activité. La sélection prenait ensuite les premières lignes sans diversité ni mémoire des vêtements déjà montrés.

Les anciens tests de disponibilité, JSON, filtres et calculs étaient utiles mais insuffisants pour évaluer cette pertinence fonctionnelle. Ils ne constituaient pas un benchmark humain des tenues.

## Correction

### Occasion comprise et contrôlée

Les occasions explicites sont conservées ou rétablies après la sortie du LoRA, avec leurs citations exactes. Une « sortie » non qualifiée reste une sortie décontractée ; elle n'est plus systématiquement traduite en fête habillée. Le sport pratiqué et le style sportif décontracté sont distingués. Les demandes d'autres tenues réutilisent le contexte lorsqu'elles ne définissent pas une nouvelle occasion.

`dressme/context.py` contient une politique de descriptions, lisible et testée, pour sport, style sportif, dîner, bureau, occasion habillée, plage, randonnée et sortie. Les règles portent sur des catégories et mots présents dans les descriptions, jamais sur une liste d'identifiants favoris ni sur des phrases de test complètes.

Pour une occasion reconnue, la sélection exige des indices positifs par rôle et écarte les contradictions évidentes : jean ou chemise en jean pour le sport, vêtement de ski pour une sortie, chaussures génériques sans détail pour un dîner, etc. Les contextes limités à un rôle ne filtrent pas les autres rôles. Les filtres de genre, possession, budget et pièces imposées restent appliqués.

Ces règles sont **des critères éditoriaux explicites**, pas des labels humains entraînés ni une certification technique. La présence de « running » dans une description étaye un choix de chaussures de running ; elle ne mesure pas leurs performances. Les styles libres et usages non couverts restent soumis aux limites de la recherche et des données disponibles.

### Recherche sensible à la demande

Le texte de recherche est enrichi avec les catégories pertinentes de l'occasion. Le genre et les autres contrôles purement structuraux ne sont plus artificiellement ajoutés comme texte de pertinence : leur rôle est de filtrer les articles.

Les scores dense/lexical sont transformés en rangs relatifs à l'intérieur de chaque rôle, parmi les articles admissibles. Les faibles écarts de cosinus peuvent ainsi départager réellement les hauts, bas ou chaussures. Les valeurs brutes sont conservées dans les signaux ; ces rangs ne sont pas présentés comme des probabilités.

BO1 reste inchangé et intervient sur des combinaisons admissibles pour l'usage demandé. Les poids configurés ne sont pas réécrits dans `.env`.

### Diversité et mémoire

La sélection des cartes est séparée du score BO1 et du classement pondéré :

- Deux propositions ne partagent pas plus de la moitié des pièces de la plus petite tenue. Une même robe avec d'autres chaussures ne compte pas comme une seconde tenue différente.
- Les douze dernières combinaisons affichées alimentent une mémoire propre au compte. Une nouvelle composition privilégie des combinaisons qui ne ressemblent pas trop aux précédentes, lorsque le pool le permet.
- Des candidats moins répétitifs sont réservés avant la limite de 512 scores, pour que la diversité ne soit pas recherchée uniquement dans un pool déjà identique.
- Si le choix est trop restreint, l'application le signale au lieu de fabriquer des variantes quasi identiques pour atteindre le nombre demandé.
- Les remplacements continuent de modifier une seule tenue en conservant intégralement les autres. La diversité ne remplace pas les pièces à préserver.
- Les What-if ne reçoivent pas de pénalité historique différente entre leurs deux scénarios : avant et après restent évalués sur le même ensemble commun. Les anciennes cartes réellement affichées restent disponibles séparément.

Le choix reste déterministe. Aucun tirage aléatoire ne remplace la compréhension de l'occasion. Le score affiché est toujours recalculable sur les identifiants réellement montrés, et les raisons de sélection sont exposées séparément.

## Limite réelle du catalogue sportif

Le classement de genre fourni par l'équipe attribue aux femmes les quatre produits dont la description mentionne explicitement la course à pied. Aucun produit classé homme/unisexe ne possède ici une description affirmative de chaussures d'entraînement ou de running.

Pour **une vraie tenue de sport homme**, la réponse indique donc le manque de chaussures descriptivement adaptées. Elle ne substitue plus des bottes et un jean. Pour un **style sportif homme**, le catalogue permet T-shirt, pantalon de survêtement et baskets de mode, sans prétendre vérifier leur performance à l'entraînement. Le catalogue permet des tenues de sport femme avec T-shirt/brassière, leggings/pantalon de survêtement et chaussures de running.

La classification de genre de l'équipe reste issue de CLIP et n'est pas une annotation humaine vérifiée. Aucun genre de produit n'a été inventé pour contourner cette limite.

## Vérification du contenu affiché

`scripts/verify_relevance.py` utilise des comptes et bases isolés et les **vrais modèles** : LoRA/Qwen3 NF4, E5/BM25 et BO1 exporté. Les assertions inspectent les vêtements affichés : catégories interdites, diversité entre les cartes, changement des pièces après une répétition, propriété du compte, score BO1 exact, disponibilité des photos, conservation de l'autre tenue pendant un remplacement et équité du What-if.

La séquence comprend sortie, remplacement de la deuxième tenue, dîner, répétition du dîner, explication, préférence verte, sport, style sportif, autres tenues, mariage et plage, pour chaque genre. Le rapport final est `relevance-live.json`. Les cas mariage et plage ont été rejoués après un affinage de leurs descriptions admissibles ; les autres cas sont conservés. Le premier passage reste dans `relevance-firstpass.json`.

Exemples constatés pour un compte homme :

- Sortie : pull en laine, jean, mocassins ; seconde proposition avec un autre pull et un autre jean.
- Dîner : chemise rayée en lin, pantalon en lin à fines rayures, Derby.
- Même dîner redemandé : autre chemise, autre pantalon, autres mocassins.
- What-if vert : polo bleu, pantalon vert, Derby ; le vert ne transforme pas la tenue en équipement sportif.
- Style sportif : T-shirt, pantalon de survêtement, baskets.

Les **290 tests automatiques réussis** sont enregistrés dans `relevance-all-tests.xml`. Les **22 scénarios réels** du rapport final passent. Ils vérifient les invariants et les cas couverts ; ils ne garantissent pas 100 % de réussite sur toutes les futures demandes, ni une préférence esthétique universelle.

Les poids, l'adaptateur, les embeddings et les tokens Hugging Face ne sont pas modifiés. Les ajustements sont dans l'orchestration, les critères de recherche et la sélection des cartes.
