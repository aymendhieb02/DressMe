# Corrections globales du chat - 3 novembre 2026

Les trois défauts observés dans la conversation utilisateur ont été corrigés dans la gestion des propositions, la réconciliation du plan et la recherche tenant compte des préférences. Les mêmes poids Qwen/LoRA et BO1 sont utilisés ; aucun entraînement n'a été lancé.

## 1. Remplacement d'une proposition

Un remplacement sélectionne une seule ligne, remplace uniquement le rôle demandé et conserve les autres propositions intégralement, avec leurs identifiants et calculs. Le numéro de proposition est renvoyé dans `comparison.selection_number`. La combinaison obtenue ne peut pas dupliquer une autre proposition affichée.

Chaque proposition dispose de son `selection_specs`. Une contrainte introduite pour modifier les chaussures de la première tenue ne devient donc pas une contrainte de la deuxième. Le petit pool des variantes de remplacement est enregistré comme diagnostic d'opération ; il ne remplace plus le pool général de recherche. Un rôle absent, un numéro indisponible ou l'absence d'alternative conforme préserve les propositions existantes dans les cas testés.

Le comportement est testé sur les propositions 1, 2 et 3, sur les chaussures et les vêtements extérieurs, et sur deux remplacements successifs.

## 2. Interprétation de la deuxième tenue et des variantes

La réconciliation `grounded-request-v2` distingue la quantité de propositions demandée du numéro de la proposition modifiée. Elle s'appuie sur l'opération et le vêtement explicitement cités, avec des sélecteurs FR/EN : ordinals, `3e`, `3rd`, `tenue numéro 4`, etc. Une clause de conservation située avant l'opération ne détourne plus le numéro de la pièce à modifier.

Les facettes structurelles erronées du plan observé (`count` citant « deuxième », `role` citant `shoes`, types visant la cible plutôt qu'une nouvelle pièce) sont réconciliées avec cette opération. La vérification des citations reste appliquée aux attributs restants. Une citation inventée sur un attribut non justifié reste rejetée.

Le cas supplémentaire avec une veste a aussi révélé une quantité omise et un type non traduit. Les quantités explicites entre 1 et 5 sont maintenant rétablies depuis leur citation ; les alias de vêtements connus sont normalisés vers leur type canonique et leur rôle structurel. Les demandes hors limites restent rejetées.

## 3. Préférences, quelle que soit la couleur

La nouvelle couche `PreferenceEvidence` est partagée entre la sélection des articles à examiner, la conservation des candidats et le classement. Elle ne contient aucune branche propre au bleu.

- Les pools sont enrichis en représentants des valeurs préférées dans les articles autorisés.
- Une partie du budget des 512 candidats réserve la couverture des préférences ; le reste conserve des alternatives pertinentes ne correspondant pas nécessairement à ces préférences.
- Les préférences sémantiques réservent aussi des candidats de forte affinité documentaire, plutôt que seulement des candidats ayant une affinité non nulle.
- Une préférence de type peut ajouter une variante structurelle facultative, par exemple avec un blazer ou un sac, dans la limite de cinq pièces.
- Les contraintes obligatoires et le périmètre du dressing restent appliqués. Une préférence ne les assouplit pas.
- Les attributs inconnus ne sont pas remplacés par des valeurs inventées. Une exclusion de couleur ne gagne pas de bonus pour une palette incomplète.

Pour une comparaison de préférences, les classements avant/après utilisent le même pool commun, éventuellement élargi. La pertinence des candidats est évaluée sur la même requête pour les deux classements. La sélection réellement affichée avant la demande est conservée séparément dans `comparison.previous_selection`, pour ne pas la confondre avec le classement de référence recalculé.

Le retrait d'une préférence peut réutiliser le pool existant. Une nouvelle préférence déclenche une recherche couvrant les critères actifs. Les limites de recherche restent 20 000 signatures examinées et 512 candidats retenus par assemblage.

`preference_coverage` indique les produits autorisés apportant un support, les candidats concernés, les propositions affichées et la méthode d'évaluation. Le message explique les valeurs indisponibles, l'absence de combinaison compatible ou un arbitrage de classement. Les affinités de style restent explicitement distinguées des propriétés vérifiées.

L'interface affiche le numéro de la proposition remplacée et distingue les propositions précédemment affichées du classement avant recalculé sur les alternatives communes.

## 4. Vérifications exécutées

| Vérification | Résultat |
| --- | --- |
| Tests automatisés, régressions et invariants | 82 réussis |
| Cas réels avec LoRA, RAG hybride et BO1 | 15 réussis, 0 échec |
| Cinq messages exacts sur le serveur corrigé du port 8000 | 5 réussis, 0 échec |
| Relecture de 50 anciennes sorties LoRA par la réconciliation actuelle | Compatible avec les acceptations et le rejet hors limites attendus ; pas de nouvelles générations |
| Compilation Python, syntaxe JavaScript et vérification des différences | Réussies |

Les cinq messages exacts sont :

1. `compose deux tenues`
2. `Explique la première tenue.`
3. `Remplace seulement les chaussures.`
4. `Change les chaussures de la deuxième tenue.`
5. `Et si je préférais le bleu ?`

Les variantes réelles couvrent rouge, vert, rose, blazer, style minimaliste, une couleur indisponible, la troisième tenue en anglais et le remplacement d'une veste dans la deuxième tenue. Elles utilisent un clone de la conversation de test après ses quatre premiers messages, ou une nouvelle conversation. Les tests automatiques couvrent aussi les préférences de type, les valeurs hors vocabulaire fixe, les attributs inconnus, l'absence d'encodeur sémantique, le respect du dressing et les conflits avec les contraintes obligatoires.

Les assertions vérifient les propositions non ciblées dans leur intégralité, les identifiants des autres pièces, le numéro demandé, les scores BO1 recalculés, le chargement des photos, la couverture des préférences et l'usage d'un pool commun. Les tests de mécanique utilisent des plans contrôlés ; la série de 15 cas et la relecture HTTP de cinq messages utilisent le vrai parseur.

Ces résultats valident les comportements décrits sur les cas exécutés. Ils ne constituent pas un benchmark esthétique, un jugement humain de pertinence ou une garantie d'optimalité des pondérations.

## 5. Preuves et reproduction

- [Série réelle de 15 cas](C:/Users/GIGABYTE/Desktop/DressMe/diagnostics/conversation-fixed.json)
- [Relecture des cinq messages sur le serveur local](C:/Users/GIGABYTE/Desktop/DressMe/diagnostics/conversation-deployed.json)
- [Compatibilité des anciennes sorties du parseur](C:/Users/GIGABYTE/Desktop/DressMe/diagnostics/conversation-parser-replay.json)
- [Invariants de conversation](C:/Users/GIGABYTE/Desktop/DressMe/tests/test_conversation.py)
- [Script de reproduction](C:/Users/GIGABYTE/Desktop/DressMe/scripts/verify_conversation.py)

Les premiers résultats avant correction des variantes sont conservés dans `conversation-fixed-firstpass.json`. L'historique et le dressing de la session utilisateur d'origine ont été lus pour reproduire son contexte ; les essais utilisent d'autres sessions. Les modèles ont été chargés depuis les fichiers locaux avec les téléchargements désactivés.

```powershell
$env:DRESSME_STATE_DIR='.runtime/global-chat-unit'
.\.venv\Scripts\python.exe -m unittest discover -s tests
.\.venv\Scripts\python.exe scripts/verify_conversation.py
# Vérification du serveur déjà démarré, dans un autre cookie de session :
.\.venv\Scripts\python.exe scripts/verify_conversation.py --url http://127.0.0.1:8000 --report diagnostics/conversation-deployed.json
```

Le bilan technique et le PDF précédents décrivent l'état audité avant ces corrections. Ce complément documente la version conversationnelle corrigée.
