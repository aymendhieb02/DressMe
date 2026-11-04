# DressMe — intégration locale BO5 / BO1

L’application FastAPI et son template HTML sont conservés. « Style Assistant » est ajouté dans le menu **Style Engine**. Aucune cellule d’installation ou d’entraînement des notebooks n’est exécutée par l’application.

## Diagnostic des fichiers

| Composant | Fichiers réels | Intégration |
| --- | --- | --- |
| Application | `api.py`, `similar.py`, `wardrobe.py`, `static/index.html` | FastAPI + HTML/CSS/JS, navigation et composants conservés ; aucune authentification existante |
| BO1 score | `bo1/score/{scorer.pt,visual.pt,config.json,catalog.json,emb_clip.npy,emb_ft.npy,dressme_core.py}` | 653 produits, 512 dimensions, modèle réel chargé en mode évaluation ; score depuis les embeddings exportés |
| Catalogue historique de l’application | `data/catalog.json` | 159 produits ; indices historiques conservés pour les écrans existants ; correspondance BO5 par identifiant produit |
| Parseur | `bo5/parser_for_local/parser_adapter/` | Qwen3-1.7B + LoRA existant, empreinte vérifiée, révision `70d244cc86ccca08cf5af4e1e306ecf908b1ad5e` ; checkpoint sélectionné 400, arrêt à 550 |
| Complétion entraînée | `bo1/outfitcompletion5item.ipynb` | RQ-VAE + MiniGPT définis et résultats enregistrés ; poids/tables d’inférence absents ; capacité annoncée indisponible |
| Tenue du jour | `bo1/outfitofthedayready.ipynb`, fonctions existantes `api.py` | Écran météo existant conservé ; les politiques de chaussures/robes du notebook complet ne sont pas imposées au chat |
| Recherche BO5 | BM25 + E5 du notebook, extrait dans `dressme/rag.py` | Documents des 653 produits, `passage:` / `query:`, E5 multilingue gelé, révision épinglée, index mis en cache |

L’empreinte SHA-256 de l’adaptateur correspond au reçu : `312555f49aa114b85bb4994d79ea941f31e81a8a23448313b7602ea9e784c003`.

### Peut-on supprimer les dossiers BO1 et BO5 ?

**Pas les dossiers complets.** Le code applicatif est intégré dans `dressme/`, mais il charge toujours les fichiers de `bo1/score/` (architecture, poids, embeddings, catalogue, tenues sources et photos) et de `bo5/parser_for_local/parser_adapter/` (adaptateur, tokenizer et reçu de traçabilité). Conserver ces deux sous-dossiers. Les chemins configurables sont `DRESSME_BO1_DIR` et `DRESSME_PARSER_ADAPTER`.

Les notebooks et `bo5/resume_latest/` ne sont pas chargés au lancement du chat. Ils peuvent être archivés hors du projet sans affecter son exécution ; garder une sauvegarde, en particulier pour retrouver les entraînements et les exports de complétion manquants. Le cache `.cache/models/` contient aussi le modèle Qwen de base nécessaire au parseur hors ligne.

Les deux matrices CLIP exportées sont identiques et `finetuned` vaut `false`. Le Transformer du scoreur a été entraîné ; ces fichiers ne constituent pas un CLIP dont le fine-tuning final aurait été conservé. Le score 0–10 mesure la compatibilité apprise à partir des tenues sources et corruptions artificielles, pas une appréciation esthétique humaine.

## Lancement PowerShell

```powershell
cd C:\Users\GIGABYTE\Desktop\DressMe
python -m venv .venv
# Pour la RTX 4060, installer d’abord la variante CUDA :
.\.venv\Scripts\python.exe -m pip install torch==2.8.0 torchvision==0.23.0 --index-url https://download.pytorch.org/whl/cu126
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
# Préchargement ciblé du modèle de base (~4 Go), sans entraînement :
.\.venv\Scripts\python.exe scripts/prepare_local.py
.\.venv\Scripts\python.exe -m uvicorn api:app --host 127.0.0.1 --port 8000
```

Ouvrir [Style Assistant](http://localhost:8000/#assistant). Le parseur et E5 se chargent à la première utilisation, une seule fois par processus. Utiliser **un worker** ; plusieurs workers dupliquent les modèles en mémoire. Après un échec de chargement du parseur, corriger la cause puis redémarrer le serveur.

Le fichier `.env` est ignoré par Git. Une valeur existante de `hf_syrine` est prioritaire et conservée. Le programme passe ce jeton aux appels Hub sans créer ni modifier `HF_TOKEN`. Si les exports locaux suffisent, le catalogue ne nécessite aucun téléchargement. Aucun jeton n’est renvoyé au navigateur, enregistré dans les diagnostics ou inclus dans cet exemple.

Les variables documentées dans `.env.example` contrôlent les chemins, la précision, le RAG et le classement. Valeurs par défaut : `DRESSME_PARSER_PRECISION=nf4`, CUDA si disponible, RAG `hybrid`, poids `0.65,0.25,0.10`. NF4 conserve le choix QLoRA du notebook et nécessite un PyTorch CUDA ainsi que bitsandbytes. Une RTX 4060 Laptop de 8 Go devrait permettre ce petit modèle quantifié ; le chargeur contrôle la mémoire libre réelle. L’échec CUDA ne déclenche aucun changement silencieux de modèle ou de précision.

Pour une vérification CPU explicite, définir `DRESSME_PARSER_DEVICE=cpu` et `DRESSME_PARSER_PRECISION=fp32`. Le modèle et l’adaptateur restent identiques, mais la précision diffère de l’entraînement NF4 ; ce choix doit apparaître dans les diagnostics. Pour un RAG lexical explicite : `DRESSME_RAG_MODE=lexical`. Aucune panne E5 n’est silencieusement convertie en recherche lexicale.

## Fonctionnement et limites

BO1 fournit actuellement le **scoreur uniquement**. Le contrat expose `can_propose=false`, `can_complete=false`, `can_encode_photo=false`. Les propositions du chat proviennent d’un **assemblage borné BO5**, explicitement distinct de MiniGPT : recherche RAG, pools par rôle, construction `haut + bas + chaussures` ou `pièce unique + chaussures`, pièces supplémentaires explicitement demandées, contrôle des contraintes puis score BO1. Les combinaisons historiques sont exclues des réponses générées. Il n’y a ni réseau aléatoire ni réponse préenregistrée.

L’assemblage examine au plus 20 000 signatures, puis note au plus 512 candidats retenus par pertinence, avec un pool par rôle configurable. Les diagnostics indiquent les nombres réellement examinés. Un résultat vide signifie « aucun candidat conforme parmi ceux examinés », pas « aucun vêtement dans le dataset ».

Les préférences de couleur, genre et type utilisent les métadonnées connues. Les préférences de style, occasion ou saison peuvent contribuer par affinité E5 avec les descriptions lorsque le RAG hybride est chargé ; les détails indiquent explicitement qu’il s’agit d’une affinité sémantique, pas d’une propriété produit vérifiée. En mode lexical, cette contribution sémantique est indisponible.

Le manifeste expose identifiant stable, description, catégorie, rôle, image, couleurs littéralement présentes dans la description, genre/prix inconnus, provenance et appartenance distincte au dressing. Il ne reprend jamais une palette de tenue comme couleur de chaque produit. Les métadonnées supplémentaires vérifiables peuvent être placées dans `data/product_metadata.json`, indexées par identifiant produit, avec `gender`, `price`, `currency`, `provenance`. Les corrections dans l’interface restent propres à la session.

Les données locales n’apportent pas de genres ou de prix vérifiés. Les couleurs citées dans les descriptions ne constituent pas une palette exhaustive : un article décrit comme noir peut comporter des motifs blancs. Les filtres `exclude` et `only` sur les couleurs nécessitent donc une palette complète renseignée explicitement par l’utilisateur. Les couleurs positives et préférences peuvent utiliser les couleurs connues dans les descriptions. Les filtres stricts rejettent les valeurs inconnues. Style, occasion, saison et objectifs restent des signaux de recherche : les cartes indiquent qu’ils ne sont pas des propriétés vérifiées. Une bonne compatibilité visuelle ne prouve ni confort ni protection météo.

Une nouvelle recherche indépendante réinitialise les facettes précédentes. Un suivi explicite conserve le contexte. Un remplacement modifie seulement la proposition ciblée et conserve les autres propositions et pièces ; les contraintes locales restent attachées à leur proposition. Les poids du classement sont configurables et ne sont pas présentés comme optimaux. Une comparaison de préférences peut enrichir les candidats, puis calcule les rangs avant/après sur le même ensemble commun ; la sélection affichée avant la demande est conservée séparément. Un scénario changeant des contraintes relance la recherche et indique que les pools peuvent différer. Les préférences restent facultatives et leur couverture est expliquée.

Le parseur combine le **LoRA existant** et une réconciliation des mots explicites du message dans `dressme/grounding.py`. Un lexique FR/EN des vêtements rétablit les types omis et les rôles de remplacement. Les règles préservent les préférences facultatives, retirent les couleurs sans demande explicite, distinguent une couleur positive d’une palette exclusive et réinitialisent les recherches indépendantes. Les réponses de devise ne complètent que les clarifications réellement en attente. Le contexte transmet toutes les tenues affichées avec leur numéro et leurs rôles, selon le format d’entraînement.

Les poids, le tokenizer et le prompt d’entraînement sont conservés ; un seul appel LoRA est effectué par message. Le panneau « Plan compris » expose `parsing.model_plan`, `parsing.corrections` (règle, citation, avant/après) et `parsing.reconciled_plan`. Les corrections ne sélectionnent aucun vêtement et ne génèrent aucun score. Les contraintes et le vrai BO1 restent appliqués ensuite. Les citations inexistantes et les cas non résolus sont rejetés. Ce lexique limité ne constitue pas une compréhension générale du langage ; aucun second appel au même modèle n’est présenté comme oracle indépendant.

Les sessions locales utilisent un cookie aléatoire HttpOnly/SameSite et SQLite dans `.runtime/`. Aucun identifiant utilisateur fourni par le navigateur ne permet de sélectionner une autre session. L’application d’origine n’a pas de connexion par compte : le dressing reste lié à ce navigateur. Une véritable authentification est nécessaire avant un déploiement multiutilisateur public.

Les photos personnelles sont stockées avec un identifiant et des métadonnées modifiables, mais **ne sont pas proposées à BO1**. Le test enregistré dans le notebook donne des cosinus 0.919–0.962 entre photos exportées et embeddings d’origine, sous son seuil de 0.97. Les exports ont été réduits à 320 px/JPEG qualité 85, contre 448 px/qualité 90 avant encodage ; `visual.pt` est stocké en FP16. Le script de vérification distingue la reproduction depuis les embeddings du chemin photo. Il faut récupérer les images originales des identifiants indiqués dans le rapport et isoler redimensionnement, recompression et précision ; aucun réentraînement n’est requis pour ce diagnostic.

## Contrat HTTP

| Route | Rôle |
| --- | --- |
| `GET /api/assistant/health` | État du catalogue, E5, parseur exact, erreurs, limites et capacité d’assemblage |
| `POST /api/assistant/chat` | `{"message":"Compose une tenue sans rouge."}` |
| `GET /api/assistant/catalog` | Manifeste commun des produits réels, photos, provenance et corrections privées |
| `GET /api/assistant/profile` | Dressing, préférences et conversation de cette session |
| `PUT /api/assistant/preferences` | Facettes avec `strength=prefer` |
| `PUT /api/assistant/wardrobe` | `{"item_ids":["P…"]}` : déclaration explicite de possession |
| `PATCH /api/assistant/wardrobe/{id}` | Métadonnées privées corrigées par l’utilisateur |
| `POST /api/assistant/wardrobe/photo` | Photo multipart, 8 Mio maximum ; encodage déclaré non vérifié |
| `POST /api/assistant/reset` | Réinitialise le chat, conserve le profil |
| `GET /api/bo1/health` | Capacités réelles et identité du scoreur |
| `POST /api/bo1/score` | `{"outfits":[["P…","P…"]]}` ; identifiants et score renvoyés ensemble, 5 pièces maximum |
| `POST /api/bo1/propose`, `/complete`, `/encode-photo` | HTTP 503 structuré tant que la capacité correspondante manque |

Les anciens endpoints de score, recherche visuelle, météo et complétion restent disponibles. La complétion historique de `api.py` utilise des règles/CLIP/MMR et ne charge pas le MiniGPT du notebook ; elle ne doit pas être interprétée comme ce modèle entraîné.

## Vérifications

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe scripts/verify_local.py --photos --rag --parser
.\.venv\Scripts\python.exe scripts/verify_chat.py
node --check static/assistant.js
```

Les tests de contraintes et d’orchestration emploient des plans de test contrôlés et le vrai scoreur exporté : ils ne mesurent pas la précision du LoRA. `verify_local.py --parser` exécute séparément le vrai parseur et rapporte ses sorties, ses échecs et une petite vérification sémantique explicite. Le RAG est inspecté sans inventer de jugements humains de pertinence. Les valeurs BO1 de référence sont celles du notebook, arrondies à 3.42 et 3.32 pour les identifiants tirés avec `random.Random(0)`.

Le rapport de vérification réel est écrit dans `diagnostics/verification.json`. Le bilan de la session d’intégration est dans `diagnostics/INTEGRATION.md`.

Après correction du parseur : **60 tests automatisés réussis**, et **50 demandes API réelles avec 49 comportements conformes et un rejet hors limites attendu**. Le détail de la correction et de ses limites est dans `diagnostics/PARSER_FIXES.md`. Ces résultats portent sur LoRA + réconciliation, pas sur une amélioration des poids du modèle.

**État constaté le 3 novembre 2026 :** le parcours réel de l'utilisateur a révélé trois défauts supplémentaires, reproduits malgré les résultats de cette série : proposition non ciblée écrasée lors d'un remplacement, citation inventée dans un suivi et préférence sans couverture dans le pool. La validation complète de pertinence et de continuité reste ouverte. Voir le [bilan technique détaillé BO5](C:/Users/GIGABYTE/Desktop/DressMe/diagnostics/BILAN_TECHNIQUE_BO5.md) et le [diagnostic du parcours utilisateur](C:/Users/GIGABYTE/Desktop/DressMe/diagnostics/USER_CHAT_REVIEW.md).

**Correction conversationnelle v2 :** ces trois mécanismes ont depuis été corrigés et vérifiés par **82 tests automatisés**, **15 cas réels** et la relecture des **5 messages exacts sur le serveur local**. La couverture concerne plusieurs couleurs, types et préférences sémantiques. Le [compte rendu actuel](C:/Users/GIGABYTE/Desktop/DressMe/diagnostics/CONVERSATION_FIXES.md) détaille les invariants et la portée de cette validation. Les documents et le PDF antérieurs restent des instantanés de l'état avant cette correction.

`verify_chat.py` exécute des requêtes HTTP avec le vrai LoRA, la réconciliation, le RAG hybride et le scoreur, sans téléchargement ni entraînement. Il utilise des sessions et une base SQLite séparées dans `.runtime/chat-verification/` et écrit les messages, plans, réponses, empreintes du code et contrôles dans le rapport. Une erreur de compréhension fait échouer le test ; seules les demandes explicitement hors limites peuvent être rejetées comme attendu. Lancer `scripts/verify_chat.py --report diagnostics/chat-parser-fixed.json` pour reproduire la série élargie. Les rapports `chat-verification*.json` conservent les essais antérieurs à la correction.

## Retrouver la complétion entraînée

Les noms suivants sont des **noms d’export proposés**, pas des fichiers prétendument déjà fournis : `rq.pt`, `gpt.pt`, `tables.npz`, `completion_config.json`.

Dans le kernel Kaggle d’origine qui contient encore les objets **entraînés** `rq` et `gpt`, exécuter le contenu de `scripts/export_completion_from_kernel.py` avec `%run -i`. Il vérifie les variables nécessaires puis exporte poids, `mu/sd`, codes sémantiques avec collisions, correspondances produit/tokens, embeddings CLIP, `COLP/PMI`, vocabulaires de contexte, paramètres de beam/règles/reclassement et identifiants de split. Télécharger seulement `completion_export/` vers `bo1/completion/`. Sans ce kernel, retrouver les sorties ou checkpoints Kaggle sauvegardés ; instancier les classes seules produit des poids aléatoires et ne résout pas le manque.

L’interface BO1 devra ensuite charger cet export strictement et adapter les fonctions `generate`, `complete_multi`, `complete_outfit` du notebook. Les 643 articles de complétion ne doivent être reliés aux 653 du scoreur que par leur identifiant produit. Les métriques enregistrées comportent une limite de séparation train/test : conserver cet avertissement lors de l’export et de toute évaluation.

Références des bibliothèques : [Transformers / PEFT](https://huggingface.co/docs/transformers/peft), [quantification bitsandbytes](https://github.com/huggingface/transformers/blob/main/docs/source/en/quantization/bitsandbytes.md), [installation PyTorch](https://pytorch.org/get-started/previous-versions/).
