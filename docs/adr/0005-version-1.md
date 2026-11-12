# ADR 0005 : la version 1.0, qualité mesurée et outil présentable

- Statut : accepté
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

Trente documents du quatrième test sont annotés une fois à la main, sur le PDF, après le gel des extracteurs et avant l'ouverture du test : l'annotation ne peut pas influencer les extracteurs, et les extractions ne peuvent pas influencer l'annotation. L'échantillon est équilibré entre documents où la rubrique semble applicable et documents où elle ne l'est pas, d'après la seule recherche de la rubrique. La mesure n'a pas de seuil : l'annotateur est unique et non spécialiste, ce que le rapport dira.

### 3. Business case mesuré

Un relecteur humain relit, chronomètre en main, une vingtaine de documents envoyés en revue par l'outil sur le quatrième test, avec les citations de l'outil à côté du PDF. Le business case compare alors deux mesures réelles : la saisie manuelle (3 minutes et 82 % de champs justes par document) et « outil plus revue humaine » (temps de revue rapporté à la part des documents en revue, exactitude après revue). Le volume de référence est celui mesuré pour les huit émetteurs (130 à 140 documents par an), puis un ordre de grandeur pour un référentiel de banque, présenté comme une extrapolation.

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

## Précisions : mesure des corrections de qualité

Ajoutées le 12 novembre 2026. Les réponses du modèle ont été relues dans le cache avec le code de la v1.0, sur les cinq jeux déjà ouverts (le test de la v0.4 compris) : aucune requête n'a été envoyée (`docs/v1.0-publique/data/mesures-adr0005.json`, produit par `scripts/adr0005/mesures_corrections.py`).

- **Taux à la française.** Les trois taux « 2,000 » du test de la v0.4 sont désormais lus 2 : trois valeurs fausses deviennent justes.
- **Vérification v4.** Sur les cinq jeux, elle bloque quatre échéances fausses (année mal recopiée, date d'émission lue à la place de l'échéance) et un taux faux. Une première version refusait aussi cinq valeurs justes ; trois causes ont été corrigées avant le gel : un nombre coupé après sa virgule par l'extraction de texte (« 3. 625 per cent »), un espace perdu entre le jour et le mois (« 8November 2051 »), une échéance qui ne donne que le mois et l'année (« Interest Payment Date falling in or nearest to February 2028 »). Une date en danois (« 6. juli 2027 ») reste refusée et part en revue.
- **Effet global.** Valeurs justes acceptées : 5 334 en v0.4, 5 336 en v1.0. Valeurs fausses acceptées : 131, puis 123. Sur le test de la v0.4 : exactitude du LLM de 91,1 % à 91,5 %, exceptions de 27 à 23, documents erronés attrapés par la revue de 19 sur 29 à 21 sur 28, pour 22 documents en revue au lieu de 20.

## Précisions : prompt v4 et niveau B

Ajoutées le 12 novembre 2026. Le prompt v4 ajoute la clause du niveau B et précise le montant d'un abondement (la série entière, pas la seule nouvelle tranche). Il a été mesuré sur les tests de la v0.3 et de la v0.4, déjà ouverts : 232 documents relus par le modèle, sous les plafonds, 0 € (`docs/v1.0-publique/data/mesures-prompt-v4.json`).

- **Définition de la clause.** Seule la rubrique générale de remboursement au gré de l'émetteur (« Issuer Call », « Call Option », « Option de remboursement au gré de l'Émetteur ») compte ; le make-whole, le clean-up call, le residual maturity call et le remboursement pour raison fiscale sont exclus. Le modèle prenait pourtant ces options pour la rubrique générale dans 9 documents : un « oui » n'est désormais accepté que si sa citation nomme l'option générale une fois les options exclues retirées. Il reste 1 cas sur les deux jeux.
- **Effet sur le niveau A.** Sur le test de la v0.4, aucun changement (728 valeurs justes). Sur celui de la v0.3, 742 valeurs justes avec le prompt v3 et 734 avec le v4, et une valeur fausse de plus : -0,5 point sur 1 586 valeurs, dans les intervalles. Les écarts sont surtout des citations recopiées imparfaitement, comme d'une exécution du modèle à l'autre ; un montant lu sur la série entière diffère désormais de FIRDS, qui donne la tranche. Le prompt v4 est gardé.
- **Cohérence du niveau B avec la rubrique.** Là où la recherche de la rubrique la trouve, le modèle donne la même réponse dans 159 cas sur 177 ; dans 17 autres, il ne donne pas de valeur, et une seule fois une valeur contraire. Ce n'est pas une mesure de justesse : la vérité sera l'annotation.
- **Recherche de la rubrique.** Elle sert à équilibrer le tirage des documents à annoter. Deux défauts corrigés en relisant les désaccords : un renvoi aux modalités entre le titre et le statut (« Call Option (Condition 7(c)) Not Applicable » était lu « applicable »), et les options exclues dont l'intitulé finit aussi par « call option ». Sur les 752 documents connus : 181 applicables, 433 non applicables, 138 sans rubrique trouvée.

## Gel avant l'ouverture du quatrième test

Ajouté le 12 novembre 2026.

- **Jeu de test.** 150 documents (142 conditions définitives, 9 prospectus d'émission isolée), tirés avec la graine 20261112 parmi les obligations jamais tirées et versionnés avant tout téléchargement. Les 151 couples citent tous leur ISIN ; 33 produits structurés sont écartés : 118 couples entrent dans la vérité terrain. Seuls les comptes de lecture ont été vus ; aucune extraction n'a été faite sur ce jeu.
- **Niveau B.** Trente documents tirés parmi les 118 couples gardés, d'après la seule recherche de la rubrique : les 12 où elle semble applicable, 15 où elle ne l'est pas, 3 où elle n'est pas trouvée. Ils sont annotés à la main, une fois, sur le PDF, avant l'ouverture et sans voir aucune sortie de l'outil.
- **Gel.** À partir de maintenant, rien ne change pour la v1.0 : règles `regles-2`, LLM `gemini-3.5-flash-lite` avec le prompt `extraction-v4`, vérification v4 (citation en deux morceaux ; montant, taux et échéance écrits dans leur citation ; clause du niveau B nommée dans sa citation), vérité terrain et critères de l'ADR 0003. La vérification v4 est gardée si elle n'accepte pas plus de valeurs fausses que celle de la v0.4 sur les mêmes sorties. La commande d'ouverture a été répétée sur le test de la v0.3, depuis le cache et sans requête. Les exceptions du nouveau test sont vérifiées à la main ; le commit exact est consigné dans `docs/v1.0-publique/data/ouverture-du-test.json`, avant toute extraction.
