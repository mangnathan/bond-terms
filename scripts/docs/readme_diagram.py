"""Schéma « Comment ça marche » du README, en SVG.

Une image fixe plutôt qu'un diagramme Mermaid : GitHub dessine Mermaid avec un script chargé à
part, qui peut ne pas se charger chez un visiteur (bloqueur, réseau filtrant). Écrit une version
pour le thème clair et une pour le thème sombre.

    uv run python scripts/docs/readme_diagram.py
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from xml.sax.saxutils import escape

OUTPUT = Path("docs/images")
FONT = "-apple-system, 'Segoe UI', Helvetica, Arial, sans-serif"
HEIGHT_BOX = 56
BOX_WIDTH = 172
GAP = 72
LEFT = 16
ROWS = (20, 132)
WIDTH = LEFT * 2 + 4 * BOX_WIDTH + 3 * GAP
HEIGHT = ROWS[1] + HEIGHT_BOX + 20
THEMES = {
    "clair": {
        "fill": "#f6f8fa",
        "stroke": "#d0d7de",
        "text": "#1f2328",
        "muted": "#59636e",
        "arrow": "#818b98",
    },
    "sombre": {
        "fill": "#161b22",
        "stroke": "#3d444d",
        "text": "#e6edf3",
        "muted": "#9198a1",
        "arrow": "#8b949e",
    },
}
STEPS = (
    ("Registre de l'ESMA", "et base FIRDS"),
    ("Collecte", "GitHub Actions"),
    ("Lecture des PDF", "et OCR des scans"),
    ("Extraction par l'IA", "avec citations"),
    ("Vérification", "des citations"),
    ("Comparaison à FIRDS", "entrepôt dbt"),
    ("Instantané publié", "en release"),
    ("API et page web", "sur Render"),
)
LABELS = {0: "chaque lundi"}  # étiquette de la flèche qui part de l'étape


@dataclass(frozen=True)
class Box:
    x: float
    y: float
    title: str
    detail: str


def layout() -> list[Box]:
    return [
        Box(LEFT + (i % 4) * (BOX_WIDTH + GAP), ROWS[i // 4], title, detail)
        for i, (title, detail) in enumerate(STEPS)
    ]


def box(b: Box, theme: dict[str, str]) -> str:
    cx = b.x + BOX_WIDTH / 2
    return (
        f'<rect x="{b.x}" y="{b.y}" width="{BOX_WIDTH}" height="{HEIGHT_BOX}" rx="8" '
        f'fill="{theme["fill"]}" stroke="{theme["stroke"]}"/>'
        f'<text x="{cx}" y="{b.y + 24}" text-anchor="middle" font-size="13" font-weight="600" '
        f'fill="{theme["text"]}">{escape(b.title)}</text>'
        f'<text x="{cx}" y="{b.y + 42}" text-anchor="middle" font-size="12" '
        f'fill="{theme["muted"]}">{escape(b.detail)}</text>'
    )


def edge(start: Box, end: Box, label: str, theme: dict[str, str]) -> str:
    if start.y == end.y:
        y = start.y + HEIGHT_BOX / 2
        x1 = start.x + BOX_WIDTH
        path = f"M{x1},{y} H{end.x - 2}"
        text = (
            f'<text x="{x1 + GAP / 2}" y="{y - 8}" text-anchor="middle" font-size="11" '
            f'fill="{theme["muted"]}">{escape(label)}</text>'
            if label
            else ""
        )
    else:
        # Retour à la ligne : du bas de la dernière étape au haut de la première de la rangée.
        mid = (start.y + HEIGHT_BOX + end.y) / 2
        path = (
            f"M{start.x + BOX_WIDTH / 2},{start.y + HEIGHT_BOX} V{mid} "
            f"H{end.x + BOX_WIDTH / 2} V{end.y - 2}"
        )
        text = ""
    return (
        f'<path d="{path}" fill="none" stroke="{theme["arrow"]}" stroke-width="1.5" '
        f'marker-end="url(#fleche)"/>{text}'
    )


def svg(theme: dict[str, str]) -> str:
    boxes = layout()
    steps = ", ".join(f"{t} {d}" for t, d in STEPS)
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" '
        f'viewBox="0 0 {WIDTH} {HEIGHT}" font-family="{FONT}" role="img" '
        f'aria-label="Schéma, dans l\'ordre : {escape(steps)}">',
        f'<defs><marker id="fleche" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" '
        f'markerHeight="7" orient="auto"><path d="M0,0 L10,5 L0,10 z" '
        f'fill="{theme["arrow"]}"/></marker></defs>',
    ]
    parts += [edge(boxes[i], boxes[i + 1], LABELS.get(i, ""), theme) for i in range(len(boxes) - 1)]
    parts += [box(b, theme) for b in boxes]
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for name, theme in THEMES.items():
        path = OUTPUT / f"schema-{name}.svg"
        path.write_text(svg(theme), encoding="utf-8", newline="\n")
        print(f"écrit : {path}")


if __name__ == "__main__":
    main()
