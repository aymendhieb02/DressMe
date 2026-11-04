# Correction du nombre de tenues et des scénarios du parseur

Message signalé : `ompose deux tenues pour une sortie`.

L'erreur fournie indiquait `before_facets.0.field='number'`, alors que le schéma BO5 attend `count`. L'ancienne normalisation de contrat ne parcourait que `facets` et ne connaissait pas cet alias. La validation Pydantic arrêtait donc le traitement avant la réconciliation sémantique.

## Changements

- Les deux listes `facets` et `before_facets` passent par la même normalisation avant validation du schéma.
- Les alias structurels `number`, `quantity` et `nombre` deviennent `count` uniquement si la valeur correspond à une quantité de tenues explicitement citée dans le message. Les champs inconnus, fausses citations, quantités inventées et types invalides restent rejetés.
- Une demande indépendante de composition ou de recherche ne possède qu'un scénario courant. Ses critères placés à tort dans `before_facets` sont déplacés dans `facets`, puis audités normalement. Les critères d'occasion ne sont pas supprimés. Une vraie comparaison conserve ses deux scénarios.
- La forme `ompose` est reconnue comme opération de composition, sans modifier le message original ni ses citations. Une nouvelle demande ne réutilise donc pas accidentellement l'ancienne recherche parce que le « c » manque.
- Le diagnostic conserve le JSON brut et le contrat normalisé même si la validation du schéma échoue.
- Les poids, le prompt d'entraînement et l'adaptateur LoRA restent inchangés. Aucun parseur alternatif ou réentraînement n'est introduit.

## Vérifications

Résultat final : **269 tests automatiques réussis** et **10 cas réels réussis**, avec Qwen3/LoRA, RAG hybride et score BO1.

Les tests couvrent les alias dans les deux listes, le français et l'anglais, les quantités citées avec l'article « une » d'une occasion, le rejet des quantités inventées ou hors limites, la conservation de l'occasion et la séparation des vrais scénarios What-if.

`diagnostics/count-parser-tests.xml` contient la validation automatique. Le test isolé du scorer historique initialise désormais son propre backend pour fonctionner sans dépendre de l'ordre d'import des autres tests.

`scripts/verify_count_parser.py` exécute les vrais modèles dans des bases et comptes de test isolés, pour un compte homme puis un compte femme. Chaque séquence contient :

1. `Compose deux tenues.`
2. `ompose deux tenues pour une sortie`
3. `Et si je préférais le vert ?`
4. `Compose deux tenues pour une sortie`
5. `Et si je préférais le beige ?`

Le rapport `diagnostics/count-parser-live.json` vérifie le nombre exact de propositions, l'occasion conservée, le genre du compte, les scores BO1 exacts et la comparaison What-if sur un ensemble commun d'alternatives, avec les vraies propositions précédentes conservées.

Le relevé brut préalable `diagnostics/count-parser-firstpass.json` contient trois générations réelles avant correction. Il montre également une réutilisation erronée du contexte sur le message sans « c ». La variante précise `field=number` signalée par l'utilisateur est reproduite comme fixture de régression ; elle ne s'est pas produite dans ces trois générations préalables. Ces quelques exemples ne constituent pas une mesure générale de précision du LoRA.
