# ADR 0005 : la version 1.0, qualité mesurée et outil présentable

- Statut : proposé
- Date : 12 novembre 2026
- Version : v1.0

## Contexte

La v0.4 a mis le projet en service : collecte hebdomadaire, surveillance avec alertes, API en ligne, à coût nul. Elle a aussi laissé des défauts mesurés. Sur le troisième test, le LLM est juste sur 91,1 % des paires document-champ, mais seule la valeur nominale passe son seuil avec une marge suffisante, et le rapport d'exceptions ne compte que 63,0 % de vrais écarts, pour 80 % exigés. Dix lectures fausses ont été vérifiées à la main ; leurs causes sont connues.

Le cadrage (ADR 0001) prévoyait pour la v1.0 une démonstration publique, une note de synthèse et un business case mesuré. Le niveau B (clauses littérales) avait été reporté par l'ADR 0004.

## Faits mesurés ou vérifiés

- **Causes des lectures fausses du test de la v0.4.** Trois taux écrits à la française (« 2,000 ») convertis en 2 000 par le projet ; trois lectures de l'obligation voisine dans un prospectus qui en décrit quatre ; deux tranches lues au lieu de la série lors d'un abondement ; une échéance prolongée ; une année mal recopiée depuis une citation pourtant juste. La vérification contrôle qu'un montant figure dans sa citation, mais pas un taux ni une date.
- **Écarts de forme.** FIRDS désigne parfois l'indice €STR par son code ISIN (`EU000A2X2A25`), que la comparaison ne reconnaît pas.
- **Replis sur les règles.** Gemini a refusé des documents lors de chaque grande série d'appels (5 à l'ouverture du test de la v0.4, 1 lors de deux collectes). La raison du refus n'est gardée ni dans la fiche ni dans le bilan.
- **Remboursement au gré de l'émetteur.** Sur les 752 documents connus, une recherche de la rubrique la trouve dans 618 : environ 120 la déclarent applicable, environ 500 non applicable. Mesure grossière (une fausse détection repérée dans l'échantillon), suffisante pour dimensionner l'annotation : un tirage au hasard de 30 documents n'en contiendrait que 5 environ.
- **Vivier du nouveau test.** 3 205 obligations d'autres émetteurs n'ont jamais été tirées (4 405 moins les 1 200 des trois tirages précédents).
- **Référence humaine.** La saisie chronométrée du cadrage : 3 minutes par document en médiane, 82 % de champs justes (58 sur 71), sur dix documents approuvés en 2022 ou 2023.

## Décisions

### 1. Corrections de qualité, mesurées sur un quatrième test

- **Vérification v4.** Un taux et une date ne sont acceptés que si leur citation les écrit, comme les montants depuis la v0.4 : la valeur convertie est comparée à la citation, pas seulement la présence de la citation dans le document.
- **Taux à la française.** Une virgule suivie de trois chiffres dans un taux est une virgule décimale (« 2,000 » vaut 2).
- **Tranche et série.** Le prompt précise qu'un abondement donne le montant de la série entière, déjà écrit dans le document.
- **Comparaison.** Le code ISIN de l'indice €STR est reconnu.
- **Raison du repli.** Chaque fiche lue par les règles garde la raison du repli (quota, service indisponible, délai dépassé), et le bilan les compte par raison.

Chaque correction est réglée sur les jeux connus, puis gelée avant l'ouverture d'un quatrième jeu de test tiré selon la règle de l'ADR 0003, parmi les obligations jamais tirées, figé avant tout téléchargement et ouvert une seule fois. Les critères ne changent pas ; les exceptions sont vérifiées à la main, comme en v0.3 et v0.4.

### 2. Niveau B réduit à une clause, à titre indicatif

Une seule clause, absente de FIRDS : le **remboursement anticipé au gré de l'émetteur** (*Issuer Call*). Deux valeurs : la clause est-elle applicable, et si oui, la première date à laquelle l'émetteur peut rembourser. Chaque valeur porte sa citation, vérifiée comme au niveau A.

Trente documents du quatrième test sont annotés une fois par Nathan Mang, sur le PDF, après le gel des extracteurs et avant l'ouverture du test : l'annotation ne peut pas influencer les extracteurs, et les extractions ne peuvent pas influencer l'annotation. L'échantillon est équilibré entre documents où la rubrique semble applicable et documents où elle ne l'est pas, d'après la seule recherche de la rubrique. La mesure n'a pas de seuil : l'annotateur est unique et non spécialiste, ce que le rapport dira.

### 3. Business case mesuré

Nathan Mang relit, chronomètre en main, une vingtaine de documents envoyés en revue par l'outil sur le quatrième test, avec les citations de l'outil à côté du PDF. Le business case compare alors deux mesures réelles : la saisie manuelle (3 minutes et 82 % de champs justes par document) et « outil plus revue humaine » (temps de revue rapporté à la part des documents en revue, exactitude après revue). Le volume de référence est celui mesuré pour les huit émetteurs (130 à 140 documents par an), puis un ordre de grandeur pour un référentiel de banque, présenté comme une extrapolation.

### 4. Démonstration lisible par un non-technicien

Une page servie par l'API elle-même à la racine : on saisit un ISIN, on voit la fiche, chaque valeur avec sa citation et sa page, les écarts avec FIRDS en évidence et l'extracteur qui a lu le document. HTML et JavaScript sans bibliothèque externe ni CDN, pour garder une politique de sécurité de contenu stricte sur cette page. `/docs` reste disponible pour les développeurs.

### 5. Note de synthèse

Une page, pour un décideur : problème, solution, chiffres mesurés, limites, coût. En LaTeX et en PDF, à côté du rapport de la v1.0.

## Alternatives écartées

- **Niveau B complet du cadrage** (plusieurs clauses, 50 documents annotés deux fois) : plusieurs heures d'annotation pour une mesure sans seuil, par un annotateur unique.
- **Abandon du niveau B** : la valeur de l'outil au-delà de FIRDS ne serait jamais montrée.
- **Corrections mesurées sur les seuls jeux connus** : le gain ne serait pas confirmé sur des documents jamais vus.
- **Temps de revue estimé** : le business case reposerait sur une hypothèse.
- **Démonstration dans un outil séparé** (Streamlit, page hébergée ailleurs) : une plateforme de plus à maintenir, quand l'API peut servir une page statique.

## Conséquences

- Le prompt passe en version `extraction-v4` et la vérification en v4 ; le niveau A est remesuré sur le quatrième test, avec le niveau B dans le même appel au modèle.
- Le quatrième test demande environ 150 requêtes au modèle à son ouverture, une heure de vérification des exceptions, une heure et demie d'annotation du niveau B et trois quarts d'heure de revue chronométrée.
- Le service en ligne passe à la v1.0 après l'ouverture : les collectes suivantes utilisent le nouvel extracteur ; les fiches déjà publiées ne sont pas relues.
