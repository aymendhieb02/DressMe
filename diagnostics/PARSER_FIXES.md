# Correction de l'interprétation du chat — 2 novembre 2026

## Changements

Le même Qwen3-1.7B et le même adaptateur sélectionné au checkpoint 400 restent chargés en NF4. Aucun réentraînement, téléchargement de modèle ou remplacement du LoRA. Le prompt d'entraînement et les poids d'origine restent inchangés. Le traitement conserve un appel au modèle par demande.

La correction se trouve dans `dressme/grounding.py`, après la génération LoRA et avant les contraintes et le RAG :

- Les noms de vêtements explicites FR/EN sont réconciliés avec les types canoniques. Un type omis est ajouté ; une traduction connue incorrecte est corrigée, par exemple la confusion entre mocassins et baskets. Une recherche d'article conserve son intention de recherche.
- Une couleur positive d'article utilise la présence de cette couleur ; une restriction explicite de palette reste stricte. Les exclusions ne sont pas affaiblies. Une préférence facultative ne devient pas une obligation, y compris pour un type de vêtement ajouté.
- Un remplacement vise le rôle nommé, conserve le numéro de tenue et ne crée pas de couleur à partir du vocabulaire fourni au modèle. Un nouveau type de chaussure explicitement demandé contraint le rôle remplacé.
- Le champ structurel `target_role` malencontreusement émis dans une facette peut être normalisé en `role` uniquement si sa valeur correspond au vêtement réellement cité. Les autres champs inconnus restent invalides.
- Le contexte transmis au modèle contient toutes les tenues affichées, avec leur numéro et leurs rôles, selon le contrat d'entraînement. Une nouvelle recherche ne reprend pas les filtres précédents. Une comparaison hypothétique conserve son intention de comparaison.
- Une réponse de devise complète uniquement une clarification de budget réellement en attente.

Chaque correction contient une règle, une citation exacte du message et des valeurs avant/après. Les diagnostics exposent la sortie brute, le plan initial, le contrat normalisé et le plan réconcilié. L'état de ces diagnostics reste propre au thread de la requête ; il n'est pas ajouté à l'état de santé global du serveur.

La réconciliation n'est pas un modèle réentraîné ni un oracle sémantique général. Son lexique est limité. Elle ne choisit aucun article, ne modifie aucune métadonnée produit et ne fabrique aucun score. Les validations, filtres stricts et le vrai scoreur BO1 s'appliquent après ces corrections. Les erreurs non résolues restent visibles.

## Vérification

**60 tests automatisés passent. Sur 50 demandes API réelles distinctes, 49 passent les contrôles et une est rejetée comme attendu : la demande de six tenues. Aucune erreur de compréhension inattendue ne reste dans cette série.** Les conversations concernées ont été rejouées après les corrections ; les règles finales ont aussi été rejouées sur les sorties brutes réellement enregistrées des 50 demandes, avec un plan final identique ou le rejet hors limites attendu.

Les tests automatisés couvrent notamment types FR/EN, polarité, palette exclusive, préférences facultatives, mots composés, traductions erronées, champ structurel mal placé, sélection de la deuxième tenue et conservation des identifiants des autres pièces.

La série API réelle utilise le LoRA, le RAG hybride et les poids BO1 locaux, dans une base de test séparée du navigateur. Elle vérifie les articles et photos retournés, les types, les facettes, les pièces conservées et les scores recalculés. Une erreur de compréhension inattendue fait échouer le test ; elle n'est plus comptée comme un succès de sécurité. Seule une demande explicitement hors de la limite d'une à cinq tenues peut être rejetée comme attendu.

Le cas « robe rouge » a été corrigé pour attendre une absence de résultat : aucun produit fourni n'est décrit comme une robe rouge. Un cas positif distinct recherche une robe bleue réellement présente. Aucune donnée n'a été inventée pour satisfaire un test.

Les essais réels réussis incluent les chemises bleues, bottes noires, jupe rose, blazer beige, T-shirt blanc, robe bleue et mocassins, ainsi que les remplacements FR/EN, la deuxième tenue, les sandales rouges, le rôle absent, la comparaison sur le même pool et les préférences facultatives. Les trois entrées HTTP invalides (vide, trop longue, champ supplémentaire) sont également rejetées avec HTTP 422. Ces résultats décrivent la couche LoRA + réconciliation sur cette série, pas la précision générale du LoRA brut.

Rapport courant : `chat-parser-fixed.json`. Le fichier `chat-parser-fixed-firstpass.json` conserve les premières erreurs découvertes dans les nouvelles formulations, avant la correction de traduction et du contrat. Les anciens rapports `chat-verification*.json` restent conservés.

## Rejouer

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests
.\.venv\Scripts\python.exe scripts/verify_chat.py --report diagnostics/chat-parser-fixed.json
```

Pour une sélection avec `--ids`, les étapes précédentes de la même conversation sont rejouées automatiquement. Le script lit la sélection actuelle via l'API avant chaque demande ; un échec intermédiaire ne lui fait pas perdre la tenue réellement conservée par le backend.

Redémarrer le processus Uvicorn pour charger les changements si le serveur tournait sans `--reload`. Les dossiers `bo1/score/` et `bo5/parser_for_local/parser_adapter/` restent nécessaires.
