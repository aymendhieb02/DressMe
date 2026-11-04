# Historique utilisateur reproduit — 3 novembre 2026

**Complément ultérieur :** les défauts diagnostiqués dans cet instantané ont été traités par la correction conversationnelle v2. Voir [CONVERSATION_FIXES.md](C:/Users/GIGABYTE/Desktop/DressMe/diagnostics/CONVERSATION_FIXES.md) pour les changements et leurs nouvelles vérifications. Le diagnostic original ci-dessous est conservé.

Les cinq messages suivants ont été retrouvés dans la session locale, puis rejoués exactement dans une session HTTP distincte sur le serveur en cours, avec la même liste de 12 vêtements déclarés. Aucune modification de la session d'origine.

1. `compose deux tenues`
2. `Explique la première tenue.`
3. `Remplace seulement les chaussures.`
4. `Change les chaussures de la deuxième tenue.`
5. `Et si je préférais le bleu ?`

## Défauts reproduits

### Le remplacement écrase la deuxième proposition

La première recherche affiche deux tenues distinctes :

- `P01124908` (robe fleurie) + `P01133629` (chaussures noires).
- `P01136660` (robe noire) + des baskets blanches.

Après le remplacement demandé sans autre numéro, le chat retourne deux variantes de la première tenue : `P01124908` avec `P01125996`, puis la même robe avec `P01126031`. La deuxième proposition d'origine est perdue.

Cause dans `dressme/engine.py` : le remplacement fixe les pièces de la tenue ciblée, puis remplace toute la liste affichée par les `top_n` variantes de cette seule tenue. Les tests précédents vérifiaient les pièces conservées dans la tenue modifiée ; ils ne vérifiaient pas la conservation de la proposition non ciblée.

### Le remplacement de la deuxième tenue échoue au parseur

L'erreur exacte est `PlanRejected: Une citation du plan ne correspond pas exactement au message.` Le modèle fournit notamment une facette dont la citation est `shoes`, absente de la demande française. Il ajoute aussi les huit couleurs du vocabulaire, une facette de quantité `2` citant `deuxième`, et la cible `les`.

La vérification des citations rejette ce plan avant sa réconciliation. Il ne s'agit donc pas d'une faute dans le message utilisateur. Les essais antérieurs de cette formulation dans une autre séquence n'avaient pas reproduit ce contexte exact.

### La préférence pour le bleu n'a aucun effet visible

Le scénario reprend les sept candidats conservés après le remplacement. Aucun ne contient un produit dont les couleurs connues comprennent le bleu. La contribution de préférence est donc exactement `0.0`, avec les mêmes rangs et les mêmes deux tenues avant/après.

Le chat renvoie cependant sa phrase générique de résultat, sans expliquer directement cette absence d'effet ou le manque de couverture du pool. Le bleu existe ailleurs dans le catalogue ; ces sept variantes ne permettent pas d'en évaluer l'intérêt.

## Portée du constat

Le serveur utilise bien l'adaptateur prévu et la réconciliation `grounded-request-v1`. Les trois défauts sont reproduits avec le vrai modèle, le RAG et le scoreur en cours. Les anciens tests de mécanique et de conformité ne constituent pas une validation de pertinence des recommandations ni de continuité complète d'une liste de propositions.

Les réponses détaillées de la reproduction sont conservées uniquement dans `.runtime/user-chat-review.json`, ignoré par Git. Ce document décrit le diagnostic ; il ne déclare pas ces trois défauts corrigés.
