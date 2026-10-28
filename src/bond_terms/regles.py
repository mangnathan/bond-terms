"""Extracteur à règles : référence que le LLM doit battre, et solution de secours (ADR 0002).

Les conditions définitives suivent une trame numérotée (« 2. Specified Currency: ... »). Pour
chaque champ, l'extracteur cherche la rubrique, lit la valeur qui suit et garde comme citation le
texte de la rubrique jusqu'à la fin de la valeur. Il travaille sur le texte normalisé (minuscules,
sans accents, espaces simples) ; les nombres coupés par l'extraction de texte (« 1,0 00,000 »,
« 202 7 ») sont recollés seulement quand le résultat a une forme valide.
"""

from __future__ import annotations

import re
import time
from collections.abc import Iterable

from bond_terms.documents import normalize
from bond_terms.extraction import HYBRID, PERPETUAL, Extraction, Value, verify
from bond_terms.valeurs import MONTHS_EN, MONTHS_FR

VERSION = "regles-2"

MONTHS = {name: number for number, name in enumerate(MONTHS_EN, start=1)} | {
    name: number for number, name in enumerate(MONTHS_FR, start=1)
}
_MONTH = "|".join(sorted(MONTHS, key=len, reverse=True))
_YEAR = r"(\d\s?\d\s?\d\s?\d)(?!\d)"
# Le jour peut être coupé par l'extraction de texte : « 1 2 july » pour « 12 july ».
_DAY_MONTH_YEAR = re.compile(rf"(?<!\d)(\d ?\d|\d)(?:st|nd|rd|th|er)?\s+({_MONTH})\s*,?\s+{_YEAR}")
_MONTH_DAY_YEAR = re.compile(rf"({_MONTH})\s+(\d{{1,2}})(?:st|nd|rd|th)?\s*,?\s+{_YEAR}")
_NUMERIC_DATE = re.compile(r"(?<!\d)(\d{1,2})\s?[/.]\s?(\d{1,2})\s?[/.]\s?(\d{4})(?!\d)")
_PERPETUAL = re.compile(
    r"perpetual|no fixed (?:maturity|redemption)|undated|not applicable"
    r"|perpetuel|duree indeterminee"
)
_PERCENT = re.compile(r"([+-]?\s?\d{1,3}(?:[.,]\d+)?)\s*(?:per\s?cent|%|pour\s?cent)")
_ISO_IN_BRACKETS = re.compile(r"\(\s*[\"'“”«»]?\s*([a-z]{3})\s*[\"'“”«»]?\s*\)")

CURRENCY_NAMES = {
    "euro": "EUR",
    "united states dollar": "USD",
    "u.s. dollar": "USD",
    "us dollar": "USD",
    "dollar americain": "USD",
    "pound sterling": "GBP",
    "sterling": "GBP",
    "livre sterling": "GBP",
    "swiss franc": "CHF",
    "franc suisse": "CHF",
    "japanese yen": "JPY",
    "yen": "JPY",
    "australian dollar": "AUD",
    "canadian dollar": "CAD",
    "singapore dollar": "SGD",
    "hong kong dollar": "HKD",
    "new zealand dollar": "NZD",
    "norwegian krone": "NOK",
    "swedish krona": "SEK",
    "danish krone": "DKK",
    "romanian leu": "RON",
    "czech koruna": "CZK",
    "polish zloty": "PLN",
    "south african rand": "ZAR",
    "mexican peso": "MXN",
    "chinese renminbi": "CNY",
    "offshore renminbi": "CNH",
}

# Familles de taux de référence ; les taux au jour le jour n'ont pas de durée écrite.
REFERENCES = {
    "euribor": "EURIBOR",
    "€str": "ESTR",
    "estr": "ESTR",
    "ester": "ESTR",
    "sofr": "SOFR",
    "sonia": "SONIA",
    "saron": "SARON",
    "sora": "SORA",
    "bbsw": "BBSW",
    "jibar": "JIBAR",
    "nibor": "NIBOR",
    "stibor": "STIBOR",
    "cibor": "CIBOR",
    "hibor": "HIBOR",
    "tibor": "TIBOR",
    "corra": "CORRA",
    "cdor": "CDOR",
    "bkbm": "BKBM",
    "mid-swap": "SWAP",
    "mid swap": "SWAP",
    "swap rate": "SWAP",
    "cms": "SWAP",
}
OVERNIGHT = {"ESTR", "SOFR", "SONIA", "SARON", "CORRA"}
# Un nom de référence n'est reconnu que comme mot entier (« ester » n'est pas dans « semester »).
_REFERENCE = re.compile(
    r"(?<![a-z])("
    + "|".join(sorted(map(re.escape, REFERENCES), key=len, reverse=True))
    + r")(?![a-z])"
)

LABELS = {
    "devise": [
        r"specified currenc(?:y|ies)(?: or currencies)?",
        r"devises?(?: ou devises)? (?:prevue|specifiee)(?:\(s\)|s)?",
    ],
    "date_echeance": [r"maturity date", r"date d'echeance", r"date de maturite"],
    "base": [r"interest basis", r"base d'interet", r"type de coupon"],
    "taux": [
        r"fixed rate of interest",
        r"initial rate of interest",
        r"rate\(?s?\)? of interest",
        r"taux d'interet(?: fixe)?",
    ],
    "reference": [r"reference rate", r"taux de reference", r"floating rate option"],
    "marge": [r"margin\(?s?\)?", r"marge\(?s?\)?"],
    "valeur_nominale": [
        r"specified denominations?(?:\(s\))?",
        r"valeur(?:\(s\)|s)? nominale(?:\(s\)|s)?(?: indiquee(?:\(s\)|s)?)?",
    ],
    "montant": [r"aggregate nominal amount", r"montant nominal total"],
    "rang": [r"status of the notes", r"rang (?:des titres|de credit|des obligations)", r"status"],
}
_FIXED = re.compile(r"fixed\s?rate|taux fixe")
# Taux fixe puis variable ou révisable : « fixed/floating », « fixed to floating », « resettable ».
_HYBRID = re.compile(r"fixe?\s?d\s?(?:/|to)\s?float|resettable|reset rate|taux revisable")
# Début de la rubrique numérotée suivante (« 9. », « 12 . (i) »).
_NEXT_RUBRIC = re.compile(r" \d{1,2} ?\. (?:\([ivx]+\) )?[a-z]")


MAX_COUPON = 20.0


def coupon(text: str) -> tuple[float, int] | None:
    """Premier pourcentage plausible pour un coupon : « 100 per cent » est un prix, pas un taux."""
    for match in _PERCENT.finditer(text):
        rate = float(match.group(1).replace(" ", "").replace(",", "."))
        if 0 <= rate < MAX_COUPON:
            return rate, match.end()
    return None


def until_next_rubric(window: str) -> str:
    match = _NEXT_RUBRIC.search(window, 3)
    return window[: match.start()] if match else window


# Une rubrique citée dans une autre (« Business Day Convention for Maturity Date ») est ignorée.
_QUOTED = re.compile(r"(?:\bfor|\bof|\bthe|\bto|\bat|\bon|\bde|\bdu|\bla|\ba)\s*$")


def flatten(text: str) -> str:
    return re.sub(r"\s+", " ", normalize(text)).strip()


def rubric(flat: str, labels: Iterable[str], width: int) -> tuple[int, int, str] | None:
    """Début de la rubrique, début de sa valeur et fenêtre de texte qui suit."""
    for label in labels:
        for match in re.finditer(rf"(?<![a-z]){label}\s*:", flat):
            if _QUOTED.search(flat[max(0, match.start() - 12) : match.start()]):
                continue
            return match.start(), match.end(), flat[match.end() : match.end() + width]
    return None


def as_number(text: str) -> float | None:
    if re.fullmatch(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?", text):
        return float(text.replace(",", ""))
    if re.fullmatch(r"\d{1,3}(?:\.\d{3})+(?:,\d+)?", text):
        return float(text.replace(".", "").replace(",", "."))
    if re.fullmatch(r"\d+(?:[.,]\d+)?", text):
        return float(text.replace(",", "."))
    return None


def glue_number(candidate: str) -> tuple[float, int] | None:
    """Nombre en tête de `candidate` et longueur lue ; recolle les morceaux coupés par un espace."""
    tokens = candidate.split(" ")
    for count in range(len(tokens), 0, -1):
        joined = "".join(tokens[:count])
        joined = joined.rstrip(".,")
        value = as_number(joined)
        if value is None:
            continue
        grouped = re.fullmatch(r"\d{1,3}(?:[,.]\d{3})+(?:[.,]\d+)?", joined) is not None
        french = all(t.isdigit() and len(t) == 3 for t in tokens[1:count])
        if count > 1 and not (grouped or french):
            continue
        return value, len(" ".join(tokens[:count]))
    return None


def find_amount(window: str) -> tuple[float, int] | None:
    """Premier montant de la fenêtre, que la devise le précède (« eur 500,000,000 ») ou le
    suive (« 500 000 000 euros », « 100 000 € ») ; le plus tôt l'emporte."""
    found: list[tuple[int, float, int]] = []
    for match in re.finditer(r"(?:\b[a-z]{3}|€|\$|£)\s?(\d[\d,. ]*)", window):
        if glued := glue_number(match.group(1).strip()):
            found.append((match.start(1), glued[0], match.start(1) + glued[1]))
            break
    for match in re.finditer(r"(\d[\d,. ]*?)\s*(?:euros?\b|d'euros|€)", window):
        if glued := glue_number(match.group(1).strip()):
            found.append((match.start(1), glued[0], match.end()))
            break
    if found:
        _, value, end = min(found)
        return value, end
    return None


def find_date(window: str) -> tuple[str, int, int] | None:
    """Première date de la fenêtre : valeur ISO, début et fin."""
    found: list[tuple[int, str, int]] = []
    if match := _DAY_MONTH_YEAR.search(window):
        day, month, year = (
            int(match.group(1).replace(" ", "")),
            MONTHS[match.group(2)],
            match.group(3),
        )
        found.append((match.start(), _iso(year, month, day), match.end()))
    if match := _MONTH_DAY_YEAR.search(window):
        month, day, year = MONTHS[match.group(1)], int(match.group(2)), match.group(3)
        found.append((match.start(), _iso(year, month, day), match.end()))
    if match := _NUMERIC_DATE.search(window):
        day, month, year = int(match.group(1)), int(match.group(2)), match.group(3)
        found.append((match.start(), _iso(year, month, day), match.end()))
    valid = [(start, iso, end) for start, iso, end in found if iso]
    if not valid:
        return None
    start, iso, end = min(valid)
    return iso, start, end


def _iso(year: str, month: int, day: int) -> str:
    year = year.replace(" ", "")
    if not (1 <= month <= 12 and 1 <= day <= 31):
        return ""
    return f"{year}-{month:02d}-{day:02d}"


def _number_text(value: float) -> str:
    return str(int(value)) if value == int(value) else repr(value)


def _cite(flat: str, start: int, end: int) -> str:
    return flat[start:end].strip()


def currency(flat: str) -> Value:
    found = rubric(flat, LABELS["devise"], 80)
    if not found:
        return Value()
    start, value_start, window = found
    if match := _ISO_IN_BRACKETS.search(window):
        end = value_start + match.end()
        return Value(match.group(1).upper(), _cite(flat, start, end))
    for name, code in sorted(CURRENCY_NAMES.items(), key=lambda item: -len(item[0])):
        if (position := window.find(name)) >= 0:
            end = value_start + position + len(name)
            return Value(code, _cite(flat, start, end))
    if match := re.match(r"\s*([a-z]{3})\b", window):
        end = value_start + match.end()
        return Value(match.group(1).upper(), _cite(flat, start, end))
    return Value()


def maturity(flat: str) -> Value:
    found = rubric(flat, LABELS["date_echeance"], 110)
    if not found:
        return Value()
    start, value_start, window = found
    date = find_date(window)
    perpetual = _PERPETUAL.search(window[:40])
    if perpetual and (not date or perpetual.start() < date[1]):
        return Value(PERPETUAL, _cite(flat, start, value_start + perpetual.end()))
    if date:
        return Value(date[0], _cite(flat, start, value_start + date[2]))
    return Value()


def amount(flat: str, labels: list[str], width: int) -> Value:
    found = rubric(flat, labels, width)
    if not found:
        return Value()
    start, value_start, window = found
    if read := find_amount(window):
        return Value(_number_text(read[0]), _cite(flat, start, value_start + read[1]))
    return Value()


def interest(flat: str) -> dict[str, Value]:
    """Type de taux, taux fixe, référence, durée et marge."""
    values = {
        name: Value()
        for name in ("type_taux", "taux_fixe", "reference_taux", "duree_reference", "marge_pb")
    }
    found = rubric(flat, LABELS["base"], 400)
    if found:
        start, value_start, window = found
        head = until_next_rubric(window)
        # Un taux fixe puis variable, ou révisable, reçoit le type « fixe puis variable »
        # (ADR 0003), avec son taux initial et la référence de sa seconde période.
        hybrid = _HYBRID.search(head)
        fixed = _FIXED.search(head)
        floating = re.search(r"floating|variable", head) or _REFERENCE.search(head)
        marker = hybrid or fixed or floating
        if marker:
            rate_type = HYBRID if hybrid else "fixed" if fixed else "floating"
            values["type_taux"] = Value(rate_type, _cite(flat, start, value_start + marker.end()))
        if (hybrid or fixed) and (read := coupon(head)):
            values["taux_fixe"] = Value(
                _number_text(read[0]), _cite(flat, start, value_start + read[1])
            )
    if values["taux_fixe"].valeur is None and values["type_taux"].valeur in ("fixed", HYBRID):
        found = rubric(flat, LABELS["taux"], 70)
        if found and (read := coupon(found[2])):
            values["taux_fixe"] = Value(
                _number_text(read[0]), _cite(flat, found[0], found[1] + read[1])
            )
    if values["type_taux"].valeur in ("floating", HYBRID):
        values |= reference(flat)
    return values


def reference(flat: str) -> dict[str, Value]:
    values: dict[str, Value] = {}
    found = rubric(flat, LABELS["reference"], 80)
    if found:
        start, value_start, window = found
        if hit := _REFERENCE.search(window):
            position, family = hit.start(), REFERENCES[hit.group(1)]
            end = hit.end()
            values["reference_taux"] = Value(family, _cite(flat, start, value_start + end))
            term = re.search(
                r"(\d{1,2})\s?-?\s?(months?|mois|m\b|years?|ans?\b|y\b|weeks?|w\b)", window
            )
            if term and abs(term.start() - position) < 25:
                unit = {"m": "M", "y": "Y", "a": "Y", "w": "W"}[term.group(2)[0]]
                end = max(end, term.end())
                values["duree_reference"] = Value(
                    f"{int(term.group(1))}{unit}", _cite(flat, start, value_start + end)
                )
            elif family in OVERNIGHT:
                values["duree_reference"] = Value("1D", _cite(flat, start, value_start + end))
    found = rubric(flat, LABELS["marge"], 60)
    if found:
        start, value_start, window = found
        if (percent := _PERCENT.search(window[:40])) and "not applicable" not in window[
            : percent.start()
        ]:
            text = percent.group(1).replace(" ", "").replace(",", ".")
            sign = -1 if text.startswith("-") or "minus" in window[: percent.start()] else 1
            bps = round(sign * abs(float(text)) * 100, 4)
            values["marge_pb"] = Value(
                _number_text(bps), _cite(flat, start, value_start + percent.end())
            )
    return values


SENIORITY_RULES = [
    (r"senior non[- ]?preferred|senior non privilegie", "senior_non_prefere"),
    (r"unsubordinated|non subordonne|senior preferred|senior privilegie|senior", "senior"),
    (
        r"deeply subordinated|super subordinated|tres subordonne|super subordonne",
        "subordonne_profond",
    ),
    (r"subordinated|subordonne", "subordonne"),
]
# Titre de l'émission : « issue of eur 1,000,000,000 0.250 per cent. senior preferred notes due ».
_TITLE = re.compile(r"issue of .{0,200}?(?:notes|obligations|titres) due")


def _seniority_in(text: str) -> tuple[str, int] | None:
    for pattern, label in SENIORITY_RULES:
        if match := re.search(pattern, text):
            return label, match.end()
    return None


def seniority(flat: str) -> Value:
    """Rubrique « Status of the Notes » ; à défaut, le titre de l'émission, où certains
    émetteurs écrivent le rang en laissant la rubrique vide."""
    found = rubric(flat, LABELS["rang"], 60)
    if found:
        start, value_start, window = found
        if read := _seniority_in(window[:45]):
            return Value(read[0], _cite(flat, start, value_start + read[1]))
    if (title := _TITLE.search(flat)) and (read := _seniority_in(title.group(0))):
        return Value(read[0], _cite(flat, title.start(), title.start() + read[1]))
    return Value()


def extract(document_id: str, pages: list[str]) -> Extraction:
    started = time.perf_counter()
    flat = flatten("\n".join(pages))
    champs: dict[str, Value] = {
        "devise": currency(flat),
        "date_echeance": maturity(flat),
        "valeur_nominale": amount(flat, LABELS["valeur_nominale"], 90),
        "montant": amount(flat, LABELS["montant"], 140),
        "rang": seniority(flat),
    }
    champs |= interest(flat)
    extraction = Extraction(document_id, "regles", VERSION, champs)
    extraction.secondes = round(time.perf_counter() - started, 4)
    return verify(extraction, pages)
