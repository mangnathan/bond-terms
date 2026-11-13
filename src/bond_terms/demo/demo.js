"use strict";

// Page de démonstration de bond-terms. Le texte venu des documents n'est jamais interprété
// comme du HTML : tout passe par textContent.

const CHAMPS = [
  ["devise", "Devise", "La monnaie de l'emprunt."],
  ["montant", "Montant emprunté", "Le total levé pour cette obligation."],
  ["valeur_nominale", "Valeur d'un titre", "Le prix unitaire d'un titre, souvent 1 000 ou 100 000."],
  ["date_echeance", "Date de remboursement", "Le jour où l'emprunteur rend l'argent (l'échéance)."],
  ["type_taux", "Type de taux", "Fixe : le même taux jusqu'au bout. Variable : il suit un taux de marché."],
  ["taux_fixe", "Taux d'intérêt", "Ce que l'emprunteur paie chaque année, en pourcentage du montant."],
  ["reference_taux", "Taux de référence", "Le taux de marché que suit un taux variable (Euribor, €STR...)."],
  ["duree_reference", "Durée du taux de référence", "Par exemple l'Euribor à 3 mois."],
  ["marge_pb", "Marge", "Ce qui s'ajoute au taux de référence."],
  ["rang", "Rang de la dette", "L'ordre de remboursement si l'emprunteur fait faillite."],
  ["remboursement_emetteur", "Remboursement anticipé possible", "L'emprunteur peut-il rembourser avant l'échéance ? Absent de la base officielle : seule la lecture du document le dit."],
  ["date_premier_remboursement", "Remboursement anticipé à partir du", "La première date à laquelle il peut le faire."],
];
const LIBELLES = Object.fromEntries(CHAMPS.map(([nom, libelle]) => [nom, libelle]));
const MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
  "septembre", "octobre", "novembre", "décembre"];

function el(tag, classe, texte) {
  const noeud = document.createElement(tag);
  if (classe) noeud.className = classe;
  if (texte !== undefined && texte !== null) noeud.textContent = texte;
  return noeud;
}

function nombre(valeur) {
  const n = Number(valeur);
  if (!Number.isFinite(n)) return String(valeur);
  return n.toLocaleString("fr-FR", { maximumFractionDigits: 4 });
}

function date(valeur) {
  if (valeur === "perpetuelle") return "Aucune (obligation perpétuelle)";
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(valeur || "");
  if (!m) return String(valeur);
  return `${Number(m[3])} ${MOIS[Number(m[2]) - 1]} ${m[1]}`;
}

const TYPES = { fixed: "Fixe", floating: "Variable", fixe_puis_variable: "Fixe, puis variable" };
const RANGS = {
  senior: "Senior (dette ordinaire)",
  senior_non_prefere: "Senior non préférée",
  subordonne: "Subordonnée (remboursée après les autres)",
  subordonne_profond: "Très subordonnée (remboursée en dernier)",
  SNDB: "Senior",
  SBOD: "Subordonnée",
  JUND: "Junior subordonnée",
  MZZD: "Mezzanine",
};
const UNITES = { D: "jour", M: "mois", Y: "an", W: "semaine",
  DAYS: "jour", MNTH: "mois", YEAR: "an", WEEK: "semaine" };

function duree(valeur) {
  const m = /^(\d+)\s*([A-Z]+)$/.exec(String(valeur).toUpperCase());
  if (!m || !UNITES[m[2]]) return String(valeur);
  const unite = UNITES[m[2]];
  const pluriel = Number(m[1]) > 1 && unite !== "mois" ? "s" : "";
  return `${m[1]} ${unite}${pluriel}`;
}

function formater(champ, valeur, devise) {
  if (valeur === null || valeur === undefined) return "";
  switch (champ) {
    case "montant":
    case "valeur_nominale":
      return `${nombre(valeur)}${devise ? " " + devise : ""}`;
    case "date_echeance":
    case "date_premier_remboursement":
      return date(valeur);
    case "type_taux":
      return TYPES[valeur] || String(valeur);
    case "taux_fixe":
      return `${nombre(valeur)} % par an`;
    case "marge_pb": {
      const pb = Number(valeur);
      if (!Number.isFinite(pb)) return String(valeur);
      return `${pb >= 0 ? "+" : ""}${nombre(pb / 100)} % (${nombre(pb)} points de base)`;
    }
    case "duree_reference":
      return duree(valeur);
    case "rang":
      return RANGS[valeur] || String(valeur);
    case "remboursement_emetteur":
      return valeur === "oui" ? "Oui, avant l'échéance" : "Non";
    default:
      return String(valeur);
  }
}

function jeu(nom) {
  const m = /^collecte-(\d{4}-\d{2}-\d{2})$/.exec(nom);
  if (m) return `Document lu lors de la collecte du ${date(m[1])}`;
  if (nom.startsWith("test")) return "Document d'un jeu d'évaluation, jamais vu pendant la mise au point";
  return "Document du jeu de mise au point";
}

function pastille(statut) {
  const [classe, texte] = {
    acceptee: ["ok", "Vérifiée"],
    refusee: ["alerte", "À contrôler"],
    absente: ["neutre", "Non trouvée"],
  }[statut] || ["neutre", statut];
  return el("span", `pastille ${classe}`, texte);
}

function visible(nom, champs) {
  const type = champs.type_taux && champs.type_taux.valeur;
  const lu = champs[nom] && champs[nom].statut !== "absente";
  if (["reference_taux", "duree_reference", "marge_pb"].includes(nom) && type === "fixed") return lu;
  if (nom === "taux_fixe" && type === "floating") return lu;
  if (nom === "remboursement_emetteur" || nom === "date_premier_remboursement") return lu;
  return true;
}

function ficheDocument(doc, numero, total) {
  const carte = el("article", "carte");
  const entete = el("div", "entete-fiche");
  entete.append(el("h3", null, total > 1 ? `Document ${numero} sur ${total}` : "Conditions lues dans le document"));
  carte.append(entete);
  const lecteur = doc.extracteur === "regles" ? "lu par des règles automatiques" : "lu par l'IA";
  carte.append(el("p", "meta", `${jeu(doc.jeu)}, ${lecteur}.`));

  if (doc.extracteur === "regles") {
    const raison = doc.repli ? ` (${doc.repli})` : "";
    carte.append(el("p", "bandeau-info alerte",
      `L'IA n'a pas pu lire ce document${raison}. Des règles automatiques, moins fiables, l'ont lu à sa place ; il sera relu par l'IA à la prochaine collecte.`));
  }
  const aProuver = doc.raisons_revue
    .filter((r) => !r.startsWith("information"))
    .map((r) => LIBELLES[r.split(" : ")[0]] || r.split(" : ")[0]);
  if (doc.en_revue) {
    carte.append(el("p", "bandeau-info alerte",
      `À faire relire par une personne : l'outil n'a pas pu prouver ${aProuver.join(", ").toLowerCase()}.`));
  } else {
    carte.append(el("p", "bandeau-info ok", "Aucune relecture nécessaire : les valeurs importantes sont prouvées."));
  }

  const ecarts = Object.fromEntries(doc.exceptions.map((e) => [e.champ, e]));
  const devise = doc.champs.devise && doc.champs.devise.statut === "acceptee" ? doc.champs.devise.valeur : "";
  const liste = el("ul", "valeurs");
  for (const [nom, libelle, aide] of CHAMPS) {
    const champ = doc.champs[nom];
    if (!champ || !visible(nom, doc.champs)) continue;
    const item = el("li", "valeur");
    const ligne = el("div", "ligne");
    const titre = el("span", "libelle", libelle);
    titre.append(el("span", "aide-champ", aide));
    const droite = el("span");
    if (champ.valeur !== null) droite.append(el("span", "donnee", formater(nom, champ.valeur, devise)), " ");
    droite.append(pastille(champ.statut));
    if (ecarts[nom]) droite.append(" ", el("span", "pastille ecart", "Écart"));
    ligne.append(titre, droite);
    item.append(ligne);
    if (champ.citation) {
      const citation = el("blockquote", "citation", champ.citation);
      citation.append(el("cite", null, champ.page ? `Phrase du document, page ${champ.page}` : "Phrase proposée, introuvable telle quelle dans le document"));
      item.append(citation);
    }
    if (ecarts[nom]) {
      const officielle = formater(nom, ecarts[nom].valeur_firds, devise) || "non renseignée";
      item.append(el("p", "ecart-ligne",
        `La base officielle de l'ESMA indique : ${officielle}. Le document dit autre chose ; un écart à examiner, pas forcément une erreur de l'outil.`));
    }
    liste.append(item);
  }
  carte.append(liste);
  return carte;
}

function afficher(donnees) {
  const zone = document.getElementById("fiche");
  zone.replaceChildren();
  const titre = el("div", "carte");
  const entete = el("div", "entete-fiche");
  entete.append(el("h2", null, `Obligation ${donnees.isin}`));
  titre.append(entete);
  titre.append(el("p", "meta",
    `${donnees.documents.length} document${donnees.documents.length > 1 ? "s" : ""} lu${donnees.documents.length > 1 ? "s" : ""} pour ce code. Chaque valeur est accompagnée de la phrase qui la prouve.`));
  zone.append(titre);
  donnees.documents.forEach((doc, i) => zone.append(ficheDocument(doc, i + 1, donnees.documents.length)));
  zone.scrollIntoView({ behavior: "smooth", block: "start" });
}

function message(texte, erreur) {
  const zone = document.getElementById("message");
  zone.textContent = texte;
  zone.classList.toggle("erreur", Boolean(erreur));
}

async function charger(isin) {
  const code = isin.trim().toUpperCase();
  if (!code) return;
  document.getElementById("isin").value = code;
  message("Chargement…");
  let reponse;
  try {
    reponse = await fetch(`/v1/obligations/${encodeURIComponent(code)}`);
  } catch {
    message("Le service ne répond pas. S'il dormait, la première réponse peut prendre une minute : réessayez.", true);
    return;
  }
  if (reponse.status === 422) {
    message("Ce code n'est pas un ISIN valide : 12 caractères, par exemple FR0014007NG9.", true);
  } else if (reponse.status === 404) {
    message("Cette obligation n'est pas dans la base. L'outil suit les obligations de huit grands émetteurs français, et des jeux d'évaluation.", true);
  } else if (reponse.status === 429) {
    message("Trop de demandes d'un coup : réessayez dans une minute.", true);
  } else if (!reponse.ok) {
    message("Une erreur est survenue. Réessayez dans un instant.", true);
  } else {
    message("");
    history.replaceState(null, "", `#${code}`);
    afficher(await reponse.json());
  }
}

async function exemples() {
  const zone = document.getElementById("exemples");
  try {
    const reponse = await fetch("/v1/exemples");
    if (!reponse.ok) return;
    for (const ex of await reponse.json()) {
      const bouton = el("button", "exemple");
      bouton.type = "button";
      bouton.append(el("strong", null, ex.titre), el("span", null, ex.explication));
      bouton.addEventListener("click", () => charger(ex.isin));
      zone.append(bouton);
    }
  } catch {
    // Sans exemples, la saisie reste possible.
  }
}

async function fraicheur() {
  try {
    const reponse = await fetch("/v1/sante");
    if (!reponse.ok) return;
    const sante = await reponse.json();
    const collecte = sante.derniere_collecte ? `, dernière collecte le ${date(sante.derniere_collecte)}` : "";
    document.getElementById("fraicheur").textContent =
      `${nombre(sante.obligations)} obligations dans la base${collecte}.`;
  } catch {
    // Information secondaire.
  }
}

document.addEventListener("DOMContentLoaded", () => {
  document.getElementById("recherche").addEventListener("submit", (event) => {
    event.preventDefault();
    charger(document.getElementById("isin").value);
  });
  exemples();
  fraicheur();
  if (location.hash.length > 1) charger(decodeURIComponent(location.hash.slice(1)));
});
