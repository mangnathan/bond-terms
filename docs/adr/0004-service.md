# ADR 0004 : un service à coût nul, et les corrections de lecture de la v0.3

- Statut : accepté
- Date : 10 novembre 2026
- Version : v0.4

## Contexte

Jusqu'à la v0.3, bond-terms est un outil de mesure lancé à la main. Le cadrage prévoyait pour la v0.4 un service : une API, une collecte planifiée et une surveillance de la qualité des données. La v0.3 a aussi laissé des corrections de lecture à faire, mesurées sur un jeu jamais vu. Le niveau B (clauses littérales) passe à la v1.0 ou est abandonné.

Les offres gratuites ont été vérifiées le 10 novembre 2026, au moment de les choisir.

## Faits mesurés ou vérifiés

- **Flux de documents.** Les obligations suivies reçoivent 130 à 140 documents d'émission par an (130 en 2026 au 23 octobre), soit 2 à 3 par semaine. Une collecte hebdomadaire suffit ; elle coûte quelques requêtes au modèle par semaine.
- **GitHub Actions.** Les machines standard sont gratuites pour un dépôt public. Dans un dépôt public, une tâche planifiée est désactivée après 60 jours sans activité du dépôt.
- **Render.** Le plan gratuit donne 750 heures d'instance par mois ; un service sans trafic s'arrête après 15 minutes et redémarre en une minute environ ; son disque n'est pas conservé. Les sources se contredisent sur la demande d'une carte bancaire pour un service web : le point est vérifié à l'inscription.
- **Hugging Face Spaces.** Les espaces Docker demandent désormais un abonnement payant : écarté.
- **Prospectus à plusieurs titres.** Cinq des sept lectures fausses du nouveau test viennent d'un prospectus qui décrit plusieurs obligations. Le registre signale lui-même les documents qui citent plusieurs ISIN (6 sur 768 documents connus).

## Décisions

### 1. L'API ne fait que lire

L'API sert, pour un ISIN, les conditions extraites : valeur, citation, page, statut de revue et exceptions avec FIRDS ; elle sert aussi les indicateurs de surveillance et un état de santé. Elle n'appelle jamais le modèle : aucune requête extérieure ne peut consommer le quota gratuit. Les données sont un instantané en lecture seule, chargé au démarrage. FastAPI, validation des entrées (format d'ISIN vérifié avant toute requête), limitation du nombre d'appels.

### 2. Collecte hebdomadaire planifiée par GitHub Actions

Chaque lundi : publication de FIRDS de la semaine, documents du registre pour les obligations suivies, nouveaux documents téléchargés, lus, passés par l'OCR et les contrôles, extraits par les règles et le LLM sous les plafonds existants, puis évalués contre FIRDS. La clé de l'API Gemini est un secret du dépôt, sur le projet Google sans facturation. Un faux modèle reste utilisé en CI.

### 3. Où vont les données collectées

Un instantané par semaine, publié comme fichier joint à une release GitHub (extractions, citations, verdicts et indicateurs ; ni PDF ni texte de document). L'API télécharge le dernier instantané au démarrage. L'historique des indicateurs est commité chaque semaine sur une branche `donnees`, non protégée, ce qui garde aussi le dépôt actif face à la règle des 60 jours.

### 4. Surveillance et alertes

Indicateurs suivis à chaque collecte : part des documents en revue, part des valeurs refusées, part des documents avec exception, documents passés par les règles faute de quota, produits structurés et rattachements erronés écartés. Une alerte ouvre automatiquement une issue GitHub quand un seuil est franchi : part en revue au-dessus de 30 % (plafond du cadrage), valeurs refusées au-dessus de 10 %, documents avec exception au-dessus de 40 %, ou arrêt pour quota.

### 5. Hébergement

Render en plan gratuit, comme complaint-triage : le compte n'a aucun moyen de paiement enregistré. Si Render exigeait une carte pour ce nouveau service, l'hébergement serait remis en question avant tout déploiement.

### 6. Corrections de lecture, mesurées sur un nouveau jeu

- Prospectus à plusieurs titres : quand le registre ou le texte cite plusieurs ISIN, le prompt demande l'obligation qui correspond à l'ISIN et à l'échéance de FIRDS, et la citation doit contenir l'échéance ou le montant de cette obligation.
- Montants à décimales françaises (« 1 000 000,000 ») et fourchettes (« between ... and ... ») : la fourchette est refusée comme montant.
- Taux CMS reconnu comme taux de swap dans la comparaison.
- Produits structurés rédigés en anglais (« Digital », « Rate Linked », « Index Linked ») ajoutés au contrôle du libellé, mesuré sur les jeux connus avant d'être appliqué.

Un nouveau jeu de test est tiré selon la règle de l'ADR 0003, parmi les obligations jamais tirées (graine 20261110), figé avant tout téléchargement et ouvert une seule fois, après le gel des corrections.

## Alternatives écartées

- **Extraction à la demande dans l'API** : un appel extérieur pourrait épuiser le quota gratuit ou servir à des abus ; la collecte planifiée suffit au rythme mesuré.
- **Base de données hébergée** : la base gratuite de Render expire après 30 jours ; un instantané en lecture seule suffit pour quelques milliers de lignes.
- **Hugging Face Spaces** : payant pour un service Docker.
- **Commit des instantanés sur la branche principale** : elle est protégée et ne doit contenir que du code et des résumés.

## Conséquences

- La v0.4 ajoute un module d'API, un workflow planifié, un module de surveillance et un fichier de déploiement.
- Les secrets restent hors du code : clé Gemini en secret du dépôt, rien dans les fichiers versionnés.
- Le nouveau test demande une collecte dans le registre et environ 150 requêtes au modèle à son ouverture.

## Précisions et gel avant l'ouverture du jeu de test de la v0.4

Ajoutés le 10 novembre 2026. Les corrections ont été réglées sur les quatre jeux connus (le test de la v0.3, ouvert, en fait désormais partie : 681 couples), sans extraire ni lire le jeu de test de la v0.4, dont seuls les comptes de lecture ont été vus.

- **Prospectus à plusieurs obligations.** Le début du document est lu : s'il annonce des obligations d'échéances différentes (5 documents connus, dont les 2 à l'origine de 5 des 7 lectures fausses de la v0.3), le message envoyé au modèle le précise et montre le passage où figure l'ISIN. Le prompt `extraction-v3` ne change pas : seuls ces documents ont été renvoyés au modèle.
- **Montants.** Un montant ou une valeur nominale n'est accepté que si sa citation l'écrit. Une fourchette est refusée ; une écriture ambiguë l'est aussi, car « 750 000,000 » vaut 750 millions et « 1 000 000,000 » un million dans les documents mesurés : la valeur part en revue humaine plutôt que d'être devinée.
- **Taux CMS** comparé comme un taux de swap.
- **Produits structurés rédigés en anglais** (autocallable, equity linked, digital rate linked) ajoutés au contrôle du libellé : aucun document des huit émetteurs touché ; 23 documents écartés chez les émetteurs jamais vus de la v0.2, 34 dans le test de la v0.3, 32 dans le jeu de test de la v0.4. Les résultats publiés de la v0.3 restent inchangés ; ils comptaient ces produits et sont donc un peu pessimistes pour le LLM.
- **Effet sur les jeux connus.** Exactitude globale du LLM : 96,3 % contre 96,1 % avec la configuration de la v0.3. Sur le test de la v0.3, étiqueté à la main, les exceptions passent de 30 à 23 : les 6 lectures fausses disparaissent, un vrai écart écrit de façon ambiguë part en revue.

**Gel.** À partir de l'ouverture du jeu de test de la v0.4, rien ne change pour la v0.4 : règles `regles-2`, LLM `gemini-3.5-flash-lite` avec le prompt `extraction-v3` et l'avertissement des prospectus à plusieurs obligations, vérification v3 (citation en deux morceaux, montants écrits sans ambiguïté), vérité terrain et critères de l'ADR 0003. La vérification v3 est gardée si elle n'accepte pas plus de valeurs fausses que celle de la v0.3 sur les mêmes sorties. Les exceptions du nouveau test sont vérifiées à la main, comme en v0.3. Le commit exact est consigné dans `docs/v0.4-service/data/ouverture-du-test.json`, avant toute extraction.
