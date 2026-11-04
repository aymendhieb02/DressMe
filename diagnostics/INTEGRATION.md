# Bilan d’intégration — 2 novembre 2026

**Dernier complément - conversation v2 :** les trois défauts du parcours utilisateur ont été corrigés et retestés. Le compte rendu actuel est [CONVERSATION_FIXES.md](C:/Users/GIGABYTE/Desktop/DressMe/diagnostics/CONVERSATION_FIXES.md) : 82 tests automatisés, 15 cas réels et 5 messages exacts sur le serveur local. Les états antérieurs ci-dessous sont conservés pour traçabilité.

**Complément du 3 novembre :** le bilan technique actuel est dans [BILAN_TECHNIQUE_BO5.md](C:/Users/GIGABYTE/Desktop/DressMe/diagnostics/BILAN_TECHNIQUE_BO5.md). Trois défauts du parcours utilisateur ont été reproduits après les séries ci-dessous ; leur existence limite les conclusions de validation fonctionnelle et de pertinence. Ils sont décrits dans `USER_CHAT_REVIEW.md` et ne sont pas déclarés corrigés.

**Mise à jour du parseur :** les erreurs de recherche d'articles et de remplacement ont été corrigées dans une couche de réconciliation traçable, avec les mêmes poids LoRA. La dernière série compte **60 tests automatisés réussis** et **50 demandes réelles : 49 conformes, une hors limites rejetée comme attendu**. Les détails actuels sont dans `PARSER_FIXES.md` et `chat-parser-fixed.json`. Les essais et limites ci-dessous décrivent aussi les étapes antérieures, dont les rapports ont été conservés.

## Réalisé

- FastAPI et le template existant conservés ; ajout de **Style Assistant** au menu.
- Manifeste commun BO5 : **653 articles et 653 photos locales**, contre 159 dans le catalogue historique de l’application. Les anciens endpoints conservent leurs indices ; BO5 et son contrat utilisent des identifiants produits.
- Scoreur BO1 réel chargé depuis `bo1/score/`, architecture importée du module fourni, poids non visuels vérifiés strictement et inférence en mode évaluation.
- Parseur configuré pour **Qwen/Qwen3-1.7B** à la révision du reçu et **l’adaptateur sélectionné au checkpoint 400**. Empreinte de l’adaptateur vérifiée. Aucun entraînement ni remplacement par Ollama.
- RAG BM25 + **multilingual-e5-small**, 653 documents indexés, conventions `query:` / `passage:`, révision épinglée et cache local.
- Assemblage borné BO5 distinct de MiniGPT, contrôle des contraintes, score BO1 de la combinaison exacte, contributions du classement, préférences facultatives et comparaison des rangs sur le même pool.
- Remplacement avec conservation des autres pièces par identifiant, comparaison recalculée et delta réel du score.
- Dressing par session, corrections privées des métadonnées, photos personnelles enregistrables mais exclues du score tant que l’encodage n’est pas vérifié.
- `hf_syrine` conservé ou configuré dans `.env` ignoré par Git ; **aucune variable `HF_TOKEN` ajoutée** et aucun secret dans les réponses HTTP.
- Documentation, commandes de lancement et script ciblé pour exporter la complétion depuis le kernel entraîné existant.

## Vérifications exécutées

**46 tests passent** via `python -m unittest discover -s tests -v` : contraintes, valeurs inconnues, budgets, propriété, négation/préférence/genre dans les garde-fous, fusion des suivis, scores et identifiants, remplacement, what-if avec préférences persistantes ou temporaires, isolation des sessions et des photos privées, contrat HTTP et maintien du template. Les trois régressions ajoutées couvrent les couleurs inventées, les références injustifiées au contexte et les quantités hors limites.

Ces tests d’orchestration utilisent des plans contrôlés. Ils ne constituent pas une mesure de compréhension du vrai LoRA.

Les scores de référence du notebook sont reproduits à partir des embeddings exportés :

| Combinaison de référence | Rechargement local | Sortie arrondie du notebook |
| --- | --- | --- |
| 3 premiers identifiants du tirage `random.Random(0)` | 3.4180865 / 10 | 3.42 / 10 |
| 4 premiers identifiants du même tirage | 3.3186622 / 10 | 3.32 / 10 |

Les deux matrices d’embeddings sont identiques, de forme `(653, 512)`. `finetuned: false` est conservé et exposé dans les diagnostics.

Le RAG réel a été exécuté : « une chemise bleue en lin » place `P01138418`, **blue linen shirt**, en tête, suivi de **blue floral linen shirt**. Aucun jugement humain, recall ou nDCG n’est inventé à partir de cette inspection.

Le chemin photo réel a été exécuté avec les poids visuels fournis et le prétraitement CLIP. Cosinus reproduits : **0.9620, 0.9253, 0.9294, 0.9187, 0.9387, 0.9580, 0.9187, 0.9544**. Score depuis ces photos : **3.2798264**, contre **3.3186622** depuis les embeddings exportés. Le seuil de parité de 0.97 du notebook échoue : l’encodage des nouvelles photos n’est pas déclaré validé.

Interface vérifiée dans le navigateur : ouverture du chat, catalogue, filtre « linen shirt », chargement des cinq photos trouvées, états du dressing et du modèle. Un débordement du menu mobile a été corrigé ; largeur du document et largeur visible sont toutes deux de **375 px** lors du test. Capture : `interface-mobile.jpg`.

`compileall`, `node --check static/assistant.js`, `git diff --check` et `pip check` ont passé lors de l’intégration.

## Blocages et limites explicites

1. **Complétion MiniGPT absente** : il manque les poids entraînés RQ-VAE/MiniGPT et les tables de tokens, normalisation, vocabulaires et reclassement. Les noms d’export proposés sont `rq.pt`, `gpt.pt`, `tables.npz`, `completion_config.json`. Exécuter `scripts/export_completion_from_kernel.py` avec `%run -i` dans le kernel entraîné original, puis télécharger le dossier exporté. Aucun entraînement n’est lancé par ce script. Le catalogue de 643 articles doit être relié au scoreur uniquement par identifiant ; la limite de séparation train/test du notebook reste documentée.
2. **Parité photo non acquise** : les originaux 448 px/JPEG qualité 90 sont absents. L’export contient des JPEG 320 px/qualité 85 et un visuel stocké en FP16. Récupérer les images originales des huit identifiants listés dans `verification.json`, puis isoler recompression/redimensionnement et précision.
3. **Métadonnées produit incomplètes** : aucun prix ou genre produit vérifié dans le catalogue exporté. Les couleurs des descriptions sont partielles : elles ne prouvent pas l’absence de couleurs secondaires sur des motifs. Les filtres stricts `exclude` et `only` nécessitent une palette complète explicitement renseignée par l’utilisateur. Le fichier distant d’annotations inspecté contient un genre de tenue ; cela ne prouve pas le genre de chaque produit. Ces attributs ne sont pas copiés automatiquement. Les filtres stricts les rejettent tant qu’ils restent inconnus.
4. **Fidélité du parseur encore limitée** : chargement et génération réels réussis, hors réseau, sur la RTX 4060 avec PyTorch 2.8.0+cu126 et NF4. Le tokenizer correspond à la base épinglée ; aucun modèle de secours. Sur six demandes contrôlées, quatre passent les contrôles sémantiques et deux perdent le type de vêtement (dont une mauvaise action). Ces deux plans JSON valides sont maintenant rejetés par un garde-fou générique, et le plan rejeté est visible dans les diagnostics. Un essai supplémentaire dans le navigateur a perdu la quantité « deux tenues » ; un contrôle générique des quantités a été ajouté et testé. Ces petits essais ne constituent pas une mesure de précision humaine ni une preuve de compréhension générale.
5. Les préférences et résultats sont liés au cookie de ce navigateur. L’application initiale n’a pas d’authentification par compte ; le service doit rester local pour cet usage.

Le détail chiffré des exécutions est dans `verification.json`. Les sorties enregistrées des notebooks ne sont pas présentées comme de nouvelles exécutions locales.

## État local final

Les deux shards Qwen et les roues CUDA ont été téléchargés et leurs SHA-256 officiels vérifiés. Le chargement Qwen utilise le chemin physique local pour éviter une requête de métadonnées distante de Transformers. Les six générations de contrôle ont été exécutées avec les téléchargements désactivés. Le serveur local est lancé sur `127.0.0.1:8000` avec la même restriction ; son PID est enregistré dans `.runtime/server.pid`. Les sauvegardes de récupération de paquets et données de test restent dans `.runtime/`, ignoré par Git. Aucun réentraînement.

## Parcours réel dans le navigateur

Le LoRA, le RAG hybride et le scoreur ont été exécutés ensemble pour « Compose une tenue. », puis « Remplace seulement les chaussures. ». La robe `P01124908` est conservée ; les chaussures passent de `P01133629` à `P01126806`. Les scores passent de **9.635** à **9.563** / 10, soit **−0.072** affiché. Un recalcul indépendant depuis les identifiants visibles confirme le score affiché. Les deux photos sont chargées. La preuve est dans `interface-verification.json` et la capture `interface-chat.jpg`.

## Essais supplémentaires du chat

`scripts/verify_chat.py` a exécuté **34 demandes distinctes** via les routes FastAPI avec le vrai adaptateur Qwen NF4 sur CUDA, le RAG hybride et les poids BO1 locaux. Aucun téléchargement, entraînement ou changement des sessions du navigateur. Les conversations de test sont dans `.runtime/chat-verification/`. Les parcours concernés ont été rejoués après correction des contrôles ; le rapport fusionne les derniers résultats de chaque cas.

Résultats : **24 comportements conformes aux contrôles explicites et 10 plans rejetés**, sans échec restant des assertions de sécurité du script. Un rejet ne compte pas comme une compréhension réussie. L'un de ces dix rejets est attendu pour « six tenues », hors de la limite de 1 à 5 ; les neuf autres révèlent des limites du parseur. Les entrées vides, trop longues et comportant un champ supplémentaire sont également rejetées avec HTTP 422.

Les cas conformes couvrent composition FR/EN, deux/trois tenues distinctes, exclusions, palette exclusive, préférence beige en anglais, budget décimal et devise ambiguë, genre explicite, dressing vide, absence de contexte, explication, comparaison sur le même pool et préférence enregistrée. Pour les tenues affichées, les identifiants, scores recalculés via le contrat BO1, rapports de contraintes et chargements des photos ont été contrôlés. Un résultat vide correct ne signifie pas qu'une tenue a été générée.

Les nouvelles limites observées :

- « si possible bleue » devient une obligation ; quatre recherches perdent le type de vêtement.
- Deux remplacements de chaussures ajoutent les huit couleurs du vocabulaire sans citation les justifiant. Le nouveau contrôle rejette ces plans. Le succès du parcours historique dans le navigateur ne garantit donc pas tous les parcours de remplacement.
- Après un suivi, une demande indépendante « Compose une tenue. » peut demander abusivement de réutiliser le contexte. Le nouveau contrôle refuse cette référence plutôt que de conserver silencieusement les anciens filtres.
- La réponse « EUR » à la question de devise produit une action `general` avec une facette de devise : plan contradictoire, rejeté. Une réponse correctement structurée de devise reste autorisée quand une clarification est réellement en attente, ce qui est couvert par le test de régression.

La compilation des quantités ne rabat plus silencieusement une valeur hors limites vers 1 ou 5. Les garde-fous vérifient également les valeurs de couleur dans leurs citations, avec équivalences FR/EN. Ils ne remplacent pas le parseur et ne corrigent pas ses sorties. Aucun poids ni reçu d'entraînement n'a été modifié.

Rapports : `chat-verification-initial.json` conserve les 30 premières réponses avant correction ; `chat-verification.json` conserve les derniers résultats des 34 cas, les attentes, plans, réponses et contrôles. Ces essais ne constituent pas un benchmark général de précision.

## Conservation des dossiers BO1 / BO5

Le code applicatif est intégré dans `dressme/`, mais **les dossiers complets ne peuvent pas être supprimés**. `bo1/score/` fournit encore architecture, poids, embeddings, catalogue, tenues sources et images ; `bo5/parser_for_local/parser_adapter/` fournit adaptateur, tokenizer et reçu. Les notebooks et `bo5/resume_latest/` ne sont pas chargés par le chat et peuvent être archivés à part. Ne pas perdre les seules copies des sources ou checkpoints nécessaires aux exports manquants. Aucun de ces fichiers n'a été supprimé.
