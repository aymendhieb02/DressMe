# Fusion de `main` dans `elyes` et genre du compte

Validation locale du 4 novembre 2026. Cette note décrit l'état après intégration ; les anciens bilans BO5 restent des photographies de leurs versions respectives.

## Résultat fonctionnel

Le module utilisateur de l'équipe et le chat BO1/BO5 fonctionnent dans la même application `api:app`.

- L'inscription propose **Femme**, **Homme** et **Sans préférence**.
- Le menu **Account** permet aussi de renseigner ou modifier ce choix sur un compte existant.
- Le serveur lit le genre dans le compte authentifié à chaque requête. Le navigateur ne fournit ni identifiant utilisateur ni genre dans la requête de chat.
- « Compose deux tenues » utilise le genre du compte, avec les articles classés unisexes également admissibles.
- Une demande explicite telle que « Compose deux tenues pour femme » prend la priorité sur un compte homme. Les modifications suivantes de cette sélection conservent ce critère explicite.
- Une nouvelle demande indépendante reprend le défaut du compte. Un compte sans genre ou sans préférence ne reçoit pas de filtre automatique.
- La conversation, les préférences et les pièces déclarées possédées sont isolées par compte et retrouvées après reconnexion.

## Résolution des conflits

Les deux branches avaient des historiques indépendants, avec **173 chemins en conflit**. La fusion conserve les fonctionnalités de l'équipe au lieu de remplacer globalement les fichiers par une seule branche.

- `api.py` : base intégrée de `main`, incluant authentification, BO3, dressing, scoring, complétion, avatars et essayage ; ajout des routeurs BO5 et du contrat BO1 à identifiants stables.
- `static/index.html` : interface et navigation de `main`, complétées par la section Assistant et les contrôles du genre du compte.
- `wardrobe.py` : version de `main`, avec ses dépendances utilisateur et son stockage.
- `similar.py` : conservation de l'accès Hugging Face via `hf_auth()`, qui donne priorité à `hf_syrine`.
- `.env.example` et `.gitignore` : réunion des réglages et exclusions des deux intégrations. Le vrai `.env` et ses tokens n'ont pas été modifiés.
- `data/` : ensemble cohérent de `main` à 653 articles. Son catalogue et ses poids BO1 correspondent à l'export utilisé par le chat ; les octets LFS ont été vérifiés par SHA256. Les images, embeddings et poids ne sont pas mélangés avec l'ancien export à 159 articles.
- Documentation : guide de `main` conservé ; ancien README BO1/BO5 conservé dans `docs/BO1_BO5_LOCAL.md` comme référence historique.
- Dépendances : entrée commune `requirements-integrated.in` et verrou testé `requirements-integrated.lock.txt`, compatible avec le parseur NF4 CUDA. L'environnement BO6 reste séparé. Les anciens verrous des branches restent disponibles comme références historiques.

## Compte, session et protection des données

Le cookie historique `dressme_session` appartient désormais exclusivement à l'authentification de l'équipe. Le chat intégré n'en crée ni n'en remplace aucun.

Le middleware authentifie la requête avant d'accéder aux routes du chat, puis fournit côté serveur l'identifiant et le genre. L'état du chat utilise une clé interne dérivée de cet identifiant. Un cookie de chat fabriqué ne permet pas de choisir le compte d'un autre utilisateur.

Les mutations BO5 exigent le jeton CSRF et une origine autorisée. Le client du chat partage le transport authentifié du Studio, y compris le renouvellement de session et du jeton CSRF. Les requêtes anonymes ou utilisant une session révoquée sont refusées.

Le mode isolé utilisé par les tests BO5 garde un cookie distinct `dressme_chat`. Les anciennes conversations anonymes sont conservées dans leur stockage local ; elles ne sont pas réattribuées automatiquement à un compte.

## Stockage et migration

La migration Alembic `0010_user_gender`, après `0009_password_recovery`, ajoute `users.gender`, nullable, avec validation `men`, `women`, `unisex`.

Les anciens comptes et leurs sessions sont conservés. Le genre n'est pas deviné pour ces comptes : il se renseigne dans **Account**. L'aller-retour de migration sur une base contenant un utilisateur et une session est couvert par un test.

Le genre par défaut est ajouté à la spécification de recherche **après** l'audit des citations du parseur. Sa provenance est `authenticated account.gender` ; il n'est pas présenté comme un mot écrit dans le message de l'utilisateur.

## Genre des articles

Le chat reprend le classement existant de l'équipe dans `data/catalog_gender.json`. Les indices sont convertis au moyen du catalogue source en identifiants produits stables, puis rapprochés du catalogue BO1. Les 653 produits sont renseignés, dont 5 présents dans les deux groupes, représentés comme unisexes.

Ce classement est issu du traitement CLIP de l'équipe : **il ne constitue pas une annotation humaine vérifiée**. Cette provenance reste visible dans les articles. Les métadonnées produit explicites et les corrections propres au dressing restent prioritaires.

## Régression du parseur détectée pendant l'intégration

Le vrai LoRA ajoutait parfois une facette inventée `style=classic`, citée « style », à « Explique la première tenue », selon la structure des tenues précédentes.

Une règle générale reconnaît désormais une demande d'explication composée uniquement d'une opération et d'une référence structurelle à une tenue. Elle conserve le numéro demandé et retire les nouveaux critères sans fondement. Une explication contenant des attributs descriptifs continue de subir la validation normale des citations. Les sorties brutes et les corrections restent dans les diagnostics.

Les corrections précédentes de remplacement d'une seule proposition, de la deuxième tenue et de la couverture des préférences restent actives.

## Vérifications

La suite finale passe **261 tests** (modules de l’équipe, BO3, BO1/BO5, comptes et genre). Le rapport est enregistré dans `diagnostics/merge-tests.xml`. Un avertissement de dépréciation du client de test Starlette/httpx reste présent, sans échec.

Le rejeu `diagnostics/authenticated-chat-replay.json` utilise les **vrais modèles**, sans téléchargement ni réentraînement : Qwen3 avec l'adaptateur LoRA NF4, RAG hybride E5/BM25, embeddings et score BO1 exportés.

Les cinq messages suivants sont rejoués dans l'ordre pour un compte homme puis un compte femme, sans ajouter de genre au texte :

1. `compose deux tenues`
2. `Explique la première tenue.`
3. `Remplace seulement les chaussures.`
4. `Change les chaussures de la deuxième tenue.`
5. `Et si je préférais le bleu ?`

Deux cas supplémentaires vérifient la priorité d'un genre explicite différent et l'effet immédiat d'une modification du compte. Les **12 cas passent** : deux propositions, genre admissible, score BO1 recalculé identique, images disponibles et conservation exacte de l'autre tenue lors des remplacements. Le premier passage, avant correction des explications, reste archivé dans `diagnostics/authenticated-chat-replay-firstpass.json`.

La page d'accueil est reconstruite, son test React passe et le formulaire d'inscription est vérifié visuellement dans le navigateur, sans erreur JavaScript constatée. Les tests HTTP du compte utilisent des bases isolées ; aucun compte utilisateur réel n'a été utilisé.

Les tests des contrats des autres modules sont inclus dans la suite fusionnée. L'inférence BO6 réelle et l'exécution d'un worker Redis/RQ ne sont pas validées ici : elles nécessitent leurs services et poids séparés. Aucun réentraînement ni modification des poids n'a été effectué.

## Lancement

Depuis la racine, avec l'environnement existant mis à jour :

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-integrated.lock.txt
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m uvicorn api:app --host 127.0.0.1 --port 8000
```

Ouvrir `http://127.0.0.1:8000/app#assistant`, puis se connecter ou créer un compte. La page d'accueil React doit être construite après un nouveau clone : `npm ci` puis `npm run build` dans `landing/`. Le chat et le Studio restent accessibles si cette page d'accueil n'a pas encore été construite.

`scripts/dev/setup.ps1` installe également le verrou intégré dans `.venv-app`. Le script de démarrage complet de l'équipe conserve sa procédure séparée pour BO6. Les poids BO1/BO5 et les caches ignorés doivent toujours être restaurés séparément lors d'un nouveau clone.

Pour reproduire les vérifications :

```powershell
$env:DRESSME_STATE_DIR='.runtime/merge-tests'
$env:DRESSME_ALLOW_DOWNLOADS='0'
$env:DRESSME_LLM='off'
$env:DRESSME_RAG_MODE='lexical'
.\.venv\Scripts\python.exe -m pytest tests bo3/tests -q
.\.venv\Scripts\python.exe -X utf8 scripts/verify_authenticated_chat.py
```
