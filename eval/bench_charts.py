"""
bench_charts.py — Figures du benchmark (Vega-Lite → PNG).

Lit ``eval/benchmark_results.json`` (produit par :mod:`eval.benchmark`) et rend
trois figures complémentaires, dans le *house style* et avec la palette
https://harchaoui.org/warith/colors/ :

  1. **Violin de latence** — la distribution complète du temps de génération par
     approche (densité miroir). Inspiré de ``eval/violin.py`` du projet
     ``intentions`` : une violine montre l'étalement et le chevauchement, pas
     qu'une moyenne — la bonne image pour « ces approches sont-elles vraiment
     différentes en vitesse ? ».
  2. **Exactitude par difficulté** — barres groupées (facile / moyen / difficile)
     par approche : la *qualité*, ventilée.
  3. **Qualité vs vitesse** — nuage (latence médiane × exactitude globale) : le
     compromis d'un coup d'œil.

Usage :
    python -m eval.bench_charts        # écrit les 3 PNG dans docs/img/
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_RESULTS_PATH = Path(__file__).resolve().parent / "benchmark_results.json"
_IMG_DIR = Path(__file__).resolve().parent.parent / "docs" / "img"

# Palette https://harchaoui.org/warith/colors/ — on suit la « Concept palette »
# (chaque couleur porte un sens), avec un triplet Bleu/Orange/Violet distinct et
# raisonnablement sûr pour les daltoniens (bleu vs orange = la paire la plus
# robuste ; le violet se distingue des deux) :
#   QwenCoder = Blue   #007AFF  (Trust    — on contrôle tout)
#   LangChain = Orange #FF9500  (Friendly — la toolbox populaire)
#   Vanna     = Purple #AF52DE  (Creative — le RAG)
_COLORS: dict[str, str] = {
    "qwen": "#007AFF",  # Blue — Trust
    "langchain": "#FF9500",  # Orange — Friendly
    "vanna": "#AF52DE",  # Purple — Creative
}

# Bloc config commun : une SEULE famille de police (Roboto) car vl_convert ne
# bundle pas « Roboto Mono » — l'utiliser faisait disparaître les étiquettes
# d'axes au rendu PNG. Couleurs de texte explicites pour garantir la lisibilité.
_FG = "#1D1D1F"
_MUTED = "#6E6E73"
_CONFIG = {
    "font": "Roboto",
    "view": {"stroke": None},
    "axis": {
        "labelFont": "Roboto",
        "titleFont": "Roboto",
        "grid": False,
        "labelColor": _FG,
        "titleColor": _FG,
        "labelFontSize": 12,
        "titleFontSize": 13,
    },
    "header": {"labelFont": "Roboto", "titleFont": "Roboto", "labelColor": _FG},
    "title": {"font": "Roboto", "anchor": "start", "fontSize": 15, "color": _FG},
    "legend": {"labelFont": "Roboto", "titleFont": "Roboto", "labelColor": _FG},
}


def _ordered_present(report: dict) -> list[dict]:
    """Renvoie les approches présentes, dans l'ordre pédagogique fixe.

    Parameters
    ----------
    report : dict
        Le rapport ``benchmark_results.json`` parsé.

    Returns
    -------
    list[dict]
        Les résumés d'approches présentes, ordonnés qwen → langchain → vanna.
    """
    order = ["qwen", "langchain", "vanna"]
    by_key = {s["key"]: s for s in report.get("summaries", []) if s.get("n")}
    # On ne garde que les approches réellement mesurées, dans l'ordre voulu.
    return [by_key[k] for k in order if k in by_key]


def build_violin_spec(report: dict) -> dict:
    """Construit la spec Vega-Lite du violin de latence.

    Parameters
    ----------
    report : dict
        Rapport parsé (contient ``approaches[].records[].latency_s``).

    Returns
    -------
    dict
        Spec Vega-Lite v5 : une densité miroir par approche, facettée en colonnes.
    """
    present = _ordered_present(report)
    labels = [s["label"] for s in present]
    colours = [_COLORS[s["key"]] for s in present]

    # Format long : une ligne {approche, latence} par requête mesurée.
    rows: list[dict] = []
    raw = {a["key"]: a for a in report.get("approaches", [])}
    for s in present:
        for rec in raw[s["key"]]["records"]:
            rows.append({"approche": s["label"], "latence": rec["latency_s"]})

    # Borne haute de l'axe = un peu au-dessus de la latence max observée.
    max_lat = max((r["latence"] for r in rows), default=1.0)
    return {
        "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
        "title": {
            "text": "Distribution de la latence par approche",
            "subtitle": f"{report.get('n_cases', 0)} requêtes · temps de génération (s)",
            "subtitleColor": "#6E6E73",
        },
        "config": _CONFIG,
        "data": {"values": rows},
        # KDE de la latence dans chaque approche, sur [0, max] → violines comparables.
        "transform": [
            {
                "density": "latence",
                "groupby": ["approche"],
                "extent": [0, max_lat],
                "as": ["latence", "densite"],
            }
        ],
        "mark": {"type": "area", "orient": "horizontal"},
        "width": 110,
        "height": 420,
        "encoding": {
            "y": {"field": "latence", "type": "quantitative", "title": "Latence (s)"},
            # Densité miroir (stack center) : c'est la forme de la violine.
            "x": {
                "field": "densite",
                "type": "quantitative",
                "stack": "center",
                "impute": None,
                "title": None,
                "axis": {"labels": False, "ticks": False, "grid": False, "values": []},
            },
            "column": {
                "field": "approche",
                "type": "nominal",
                "sort": labels,
                "header": {"titleOrient": "bottom", "labelOrient": "bottom", "labelPadding": 6},
                "title": None,
            },
            "color": {
                "field": "approche",
                "type": "nominal",
                "scale": {"domain": labels, "range": colours},
                "legend": None,
            },
        },
    }


def build_accuracy_spec(report: dict) -> dict:
    """Construit la spec des barres d'exactitude par difficulté.

    Parameters
    ----------
    report : dict
        Rapport parsé (contient ``summaries[].accuracy_by_difficulty``).

    Returns
    -------
    dict
        Spec Vega-Lite v5 : barres groupées, x = difficulté, couleur = approche.
    """
    present = _ordered_present(report)
    labels = [s["label"] for s in present]
    colours = [_COLORS[s["key"]] for s in present]

    # Une ligne {approche, difficulté, exactitude} par (approche × palier).
    rows: list[dict] = []
    for s in present:
        for niveau in ("facile", "moyen", "difficile"):
            d = s.get("accuracy_by_difficulty", {}).get(niveau)
            if d:
                rows.append(
                    {"approche": s["label"], "difficulte": niveau, "exactitude": d["accuracy"]}
                )

    return {
        "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
        "title": {
            "text": "Exactitude d'exécution par difficulté",
            "subtitle": "part des requêtes dont le résultat = la référence",
            "subtitleColor": "#6E6E73",
        },
        "config": _CONFIG,
        "data": {"values": rows},
        "mark": {"type": "bar", "cornerRadiusEnd": 3},
        "width": 320,
        "height": 300,
        "encoding": {
            "x": {
                "field": "difficulte",
                "type": "nominal",
                "sort": ["facile", "moyen", "difficile"],
                "title": None,
                "axis": {"labelAngle": 0},
            },
            "xOffset": {"field": "approche", "sort": labels},
            "y": {
                "field": "exactitude",
                "type": "quantitative",
                "title": "Exactitude",
                "axis": {"format": "%"},
                "scale": {"domain": [0, 1]},
            },
            "color": {
                "field": "approche",
                "type": "nominal",
                "scale": {"domain": labels, "range": colours},
                "legend": {"title": None, "orient": "top"},
            },
            "tooltip": [
                {"field": "approche"},
                {"field": "difficulte"},
                {"field": "exactitude", "format": ".0%"},
            ],
        },
    }


def build_scatter_spec(report: dict) -> dict:
    """Construit le nuage « qualité vs vitesse » (latence médiane × exactitude).

    Parameters
    ----------
    report : dict
        Rapport parsé (contient ``summaries``).

    Returns
    -------
    dict
        Spec Vega-Lite v5 : un point par approche + étiquette.
    """
    present = _ordered_present(report)
    labels = [s["label"] for s in present]
    colours = [_COLORS[s["key"]] for s in present]

    # Un point par approche : x = latence médiane, y = exactitude globale.
    rows = [
        {"approche": s["label"], "latence_med": s["latency_median"], "exactitude": s["accuracy"]}
        for s in present
    ]

    # Le point + son étiquette texte, superposés (layer).
    base_enc = {
        "x": {
            "field": "latence_med",
            "type": "quantitative",
            "title": "Latence médiane (s) — plus à gauche = plus rapide",
            "scale": {"zero": True},
        },
        "y": {
            "field": "exactitude",
            "type": "quantitative",
            "title": "Exactitude globale",
            "axis": {"format": "%"},
            "scale": {"domain": [0, 1]},
        },
        "color": {
            "field": "approche",
            "type": "nominal",
            "scale": {"domain": labels, "range": colours},
            "legend": {"title": None, "orient": "top"},
        },
    }
    return {
        "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
        "title": {
            "text": "Qualité vs vitesse",
            "anchor": "start",
            "subtitle": "en haut à gauche = rapide ET juste",
            "subtitleColor": "#6E6E73",
        },
        "config": _CONFIG,
        "data": {"values": rows},
        "width": 380,
        "height": 300,
        "layer": [
            {"mark": {"type": "point", "filled": True, "size": 220}, "encoding": base_enc},
            {
                "mark": {"type": "text", "dy": -14, "font": "Roboto", "fontWeight": "bold"},
                "encoding": {
                    **base_enc,
                    "text": {"field": "approche"},
                    "color": {
                        "field": "approche",
                        "type": "nominal",
                        "scale": {"domain": labels, "range": colours},
                        "legend": None,
                    },
                },
            },
        ],
    }


def render_all(report: dict | None = None) -> list[Path]:
    """Rend les trois figures en PNG et renvoie leurs chemins.

    Parameters
    ----------
    report : dict | None
        Rapport pré-chargé ; lu depuis le disque si ``None``.

    Returns
    -------
    list[pathlib.Path]
        Les chemins des PNG écrits.

    Raises
    ------
    FileNotFoundError
        Si le fichier de résultats est absent et qu'aucun rapport n'est fourni.
    """
    import vl_convert as vlc

    # Chargement des résultats si non fournis.
    if report is None:
        if not _RESULTS_PATH.is_file():
            raise FileNotFoundError(
                f"{_RESULTS_PATH} introuvable — lancez `python -m eval.benchmark`."
            )
        report = json.loads(_RESULTS_PATH.read_text(encoding="utf-8"))

    _IMG_DIR.mkdir(parents=True, exist_ok=True)
    # (nom de fichier, spec) pour chaque figure.
    figures = [
        ("bench-latency-violin.png", build_violin_spec(report)),
        ("bench-accuracy-difficulty.png", build_accuracy_spec(report)),
        ("bench-quality-vs-speed.png", build_scatter_spec(report)),
    ]
    written: list[Path] = []
    for name, spec in figures:
        # Rendu 2× pour un PNG net (retina) dans la doc.
        png = vlc.vegalite_to_png(vl_spec=json.dumps(spec), scale=2.0)
        path = _IMG_DIR / name
        path.write_bytes(png)
        written.append(path)
        logger.info("Figure écrite : %s", path)
    return written


def main() -> int:
    """CLI : rend les figures du benchmark et affiche leurs chemins.

    Returns
    -------
    int
        Code de sortie (0).
    """
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    for path in render_all():
        logger.info("→ %s", path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
