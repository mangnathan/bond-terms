# ADR 0003 : citations en deux morceaux, taux hybrides, revue humaine, exceptions et nouveau test

- Statut : accepté
- Date : 28 octobre 2026
- Version : v0.3

## Contexte

La v0.2 a retenu le LLM (`gemini-3.5-flash-lite`) : sur le test, 90,8 % d'exactitude globale contre 83,3 % pour les règles. Elle a aussi montré deux limites, analysées après l'ouverture du test : des valeurs justes refusées par la vérification des citations, et une convention de FIRDS instable pour les titres à taux fixe puis variable. La v0.3 doit les traiter, puis construire ce que le cadrage prévoyait : une file de revue humaine et un rapport d'exceptions.

Les trois jeux déjà ouverts (développement, test et émetteurs jamais vus de la v0.2, soit 588 couples document-ISIN) sont désormais connus. Ils forment le développement de la v0.3. Les mesures ci-dessous y ont été faites avec `scripts/adr0003/mesures.py` ; le résumé est dans `docs/v0.3-revue/data/mesures-adr0003.json`.

## Mesures sur les données connues

### Citations en deux morceaux

Dans certaines mises en page sur deux colonnes, l'intitulé (« Fixed Rate(s) of Interest: ») et la valeur sont séparés par d'autres lignes dans le texte extrait du PDF. La citation du modèle les recolle et la règle actuelle la refuse. Règle mesurée : la citation est coupée au premier deux-points ; l'intitulé (au moins 6 caractères) et la valeur (au moins 8) doivent se trouver sur la même page, l'intitulé moins de 400 caractères avant la valeur.

| Valeurs refusées par la règle actuelle | Récupérées | Toujours refusées |
|---|---|---|
| Justes | 29 | 33 |
| Fausses | 0 | 2 |

La règle récupère près de la moitié des valeurs justes refusées et n'accepte aucune valeur fausse.

### Taux hybrides

Pour les titres à taux fixe puis variable ou révisables, le type de taux déclaré par FIRDS dépend de l'année et de l'émetteur :

| Année d'approbation | Déclarés en taux fixe | Déclarés en taux variable |
|---|---|---|
| 2021 | 13 | 0 |
| 2022 | 17 | 3 |
| 2023 | 17 | 3 |
| 2024 | 13 | 3 |
| 2025 | 18 | 12 |
| 2026 | 8 | 10 |

FIRDS n'est pas une vérité fiable sur le type de ces titres : la part déclarée en taux variable passe d'environ 15 % à plus de la moitié en deux ans.

### File de revue

Règle mesurée : un document part en revue si le LLM n'a pas justifié une valeur parmi la devise, l'échéance, le type de taux, le taux fixe (pour un taux fixe), la valeur nominale et le rang, ou si le LLM et les règles donnent deux valeurs différentes pour l'un de ces champs.

| Jeu | Documents | Envoyés en revue | Documents comptés faux | Dont attrapés par la revue |
|---|---|---|---|---|
| Développement v0.2 | 341 | 25 (7 %) | 70 | 22 |
| Test v0.2 | 148 | 27 (18 %) | 68 | 27 |
| Émetteurs jamais vus v0.2 | 99 | 26 (26 %) | 36 | 18 |

La part envoyée en revue reste sous le plafond de 30 % fixé au cadrage. La revue n'attrape qu'une partie des documents comptés faux : beaucoup de ces écarts viennent de FIRDS (montant, taux hybrides), pas de la lecture, et relèvent du rapport d'exceptions.

### Rapport d'exceptions

Une exception est une valeur que le LLM justifie par une citation vérifiée, mais qui diffère de FIRDS. Sur les données connues : 126 exceptions dans 115 documents, dont 51 sur le montant et 39 sur le type de taux.

## Décisions

### 1. Un nouveau jeu de test, tiré avant toute extraction

Le test de la v0.2 est connu : toute correction réglée en le regardant doit être jugée sur des documents jamais vus. Un nouveau jeu est tiré au hasard (graine 20261028) parmi les obligations classiques à ISIN français des émetteurs autres que les huit étudiés, en excluant les 300 obligations déjà tirées en v0.1 et tout document déjà présent dans un jeu. On tire 450 obligations, on collecte leurs documents d'émission, et on garde au plus 150 documents. Le jeu est figé et versionné avant toute extraction, puis ouvert une seule fois, comme en v0.2.

### 2. Citations en deux morceaux

La vérification accepte, en plus d'une citation d'un seul tenant, une citation dont l'intitulé et la valeur se trouvent sur la même page, l'intitulé moins de 400 caractères avant la valeur, selon la règle mesurée ci-dessus. Elle reste retenue si, sur le nouveau test, elle n'accepte pas plus de valeurs fausses que la vérification de la v0.2.

### 3. Taux hybrides

Le type de taux prend une troisième valeur, « fixe puis variable », pour les titres à taux fixe puis variable et les titres révisables. Elle est juste si FIRDS déclare un taux fixe ou un taux variable, comme pour le rang « senior non préférée ». Les autres champs suivent la déclaration de FIRDS : le taux fixe initial est comparé quand FIRDS déclare un taux fixe ; la référence, sa durée et la marge de la seconde période quand FIRDS déclare un taux variable. L'extracteur LLM doit donc rendre les deux périodes : le prompt passe en version 3, et le développement est extrait à nouveau (588 requêtes, sur deux jours de quota gratuit).

### 4. File de revue humaine

Un document part en revue selon la règle mesurée ci-dessus. Indicateurs sur le nouveau test : part des documents envoyés en revue (au plus 30 %, seuil du cadrage) et part des documents erronés attrapés (publiée, sans seuil).

### 5. Rapport d'exceptions

Le rapport liste, pour chaque exception, le document, le champ, la valeur de FIRDS, la valeur lue et sa citation. Le seuil du cadrage, au moins 80 % de vrais écarts, se mesure par une vérification humaine : pour chaque exception du nouveau test, Nathan Mang ouvre le PDF à la page citée et note si le document dit bien la valeur lue. C'est une vérification littérale, qui ne demande pas d'expertise financière. Les exceptions sur le type de taux d'un titre hybride ne sont plus des exceptions (décision 3).

### 6. Clauses littérales, niveau B : reportées à la v0.4

Le niveau B prévu au cadrage (remboursement au gré de l'émetteur ou du porteur, remboursement « make-whole », label vert ou social, droit applicable) demande d'annoter environ 50 documents deux fois, à une semaine d'écart. Il est indicatif, sans seuil. La v0.3 se concentre sur la revue et les exceptions, qui comptent dans les seuils du cadrage ; le niveau B passe à la v0.4.

## Alternatives écartées

- **Réutiliser le test de la v0.2** : il a servi à analyser les erreurs ; le réutiliser mesurerait le réglage, pas la généralisation.
- **Accepter une citation dès que la valeur seule figure dans le document** : un taux ou une date isolés se retrouvent souvent ailleurs dans le document ; l'intitulé proche est ce qui rattache la valeur au bon champ.
- **Suivre la convention de FIRDS de l'année** : elle change encore et dépend de l'émetteur ; un modèle réglé sur 2025 se tromperait en 2027.
- **Envoyer en revue tout document compté faux** : impossible en production, où la vérité n'est pas connue ; la règle de revue ne doit utiliser que ce que l'outil sait.

## Conséquences

- La vérification, la comparaison et le prompt changent de version ; la v0.2 reste reproductible par son tag.
- Le nouveau test demande une collecte dans le registre (environ 450 requêtes à une par seconde) et environ 150 requêtes au modèle à son ouverture.
- La vérification humaine des exceptions demande environ une heure de saisie, après l'ouverture du nouveau test.
