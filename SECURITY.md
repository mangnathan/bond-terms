# Sécurité

## Signaler une faille

Merci de **ne pas ouvrir d'issue publique** pour une faille. Utilisez le signalement privé de GitHub : onglet **Security**, puis **Report a vulnerability**. Une réponse est donnée sous sept jours.

*English: please do not open a public issue for a vulnerability; use GitHub's private vulnerability reporting (Security tab, "Report a vulnerability").*

## Ce qui est exposé

- **L'API et sa page de démonstration** (bond-terms.onrender.com), en lecture seule, sans compte ni base de données.
- **La collecte hebdomadaire** sur GitHub Actions : elle ouvre des PDF publiés par les émetteurs, appelle le modèle de langage et publie l'instantané que l'API sert.
- **La clé de l'API Gemini**, rangée dans les secrets de GitHub, sur un projet Google sans facturation liée.

## Mesures en place

**API**
- Aucun secret sur le serveur, et le modèle de langage n'est jamais appelé : aucune requête extérieure ne peut consommer de quota.
- L'ISIN est vérifié (format et clé de contrôle) avant toute recherche.
- Appels limités par client (60 par minute, sur l'adresse fournie par l'hébergeur, que le client ne peut pas falsifier) et au total (600 par minute).
- L'instantané téléchargé au démarrage est validé champ par champ ; au-delà d'une taille maximale, il est refusé.
- La page n'insère jamais de HTML et n'autorise que ses propres fichiers (politique de sécurité du contenu stricte).
- En-têtes de sécurité sur chaque réponse : HTTPS imposé, affichage dans un cadre interdit, pas de devinette du type de contenu.
- Les journaux ne contiennent pas l'adresse des clients.

**Collecte**
- Le jeton d'écriture de GitHub n'est donné qu'aux étapes qui publient, jamais à celle qui ouvre les PDF, et n'est pas gardé dans la copie du dépôt.
- Une valeur lue par le modèle n'est acceptée que si sa citation est retrouvée dans le document.
- Le XML est lu avec `defusedxml`.

**Dépôt**
- Actions GitHub référencées par l'empreinte de leur commit ; aucune valeur extérieure collée dans un script ; aucun déclencheur qui donne des droits d'écriture à du code de fork. Un test (`tests/unit/test_workflows.py`) vérifie ces règles.
- Dépendances verrouillées par `uv.lock`, sans faille connue au dernier audit (`pip-audit`).
- `.env` n'est jamais versionné.
