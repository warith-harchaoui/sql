"""
bench_charts.py — Figures du benchmark (Vega-Lite → PNG), bilingues et épurées.

Lit ``eval/benchmark_results.json`` (produit par :mod:`eval.benchmark`) et rend,
**en français et en anglais**, trois figures dans un style volontairement épuré
(pas de cadre, pas de grille, pas de ticks, texte qui explique la lecture),
avec la palette https://harchaoui.org/warith/colors/ :

  1. **Violin de latence** — distribution complète du temps de génération
     (densité miroir), inspiré de ``eval/violin.py`` du projet ``intentions``.
  2. **Exactitude par difficulté** — barres avec la valeur écrite dessus (pas
     besoin de lire un axe : la figure « parle » toute seule).
  3. **Qualité vs vitesse** — nuage (latence médiane × exactitude) : le compromis.

Chaque langue écrit dans ``docs/img/<lang>/`` : ``fr`` pour la doc française
(LISEZMOI / BENCHMARK.fr.md), ``en`` pour la doc anglaise (README / BENCHMARK.md).

Usage :
    python -m eval.bench_charts            # rend fr ET en
    python -m eval.bench_charts --lang fr  # une seule langue
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_RESULTS_PATH = Path(__file__).resolve().parent / "benchmark_results.json"
_IMG_DIR = Path(__file__).resolve().parent.parent / "docs" / "img"

# Palette https://harchaoui.org/warith/colors/ — « Concept palette » (chaque
# couleur a un sens), triplet Bleu/Orange/Violet : distinct et sûr pour les
# daltoniens (bleu vs orange = la paire la plus robuste, le violet tranche).
_COLORS: dict[str, str] = {
    "qwen": "#007AFF",  # Blue — Trust (bon prompt, on contrôle tout)
    "qwen_naive": "#8E8E93",  # Gray — Neutral (le témoin « prompt paresseux »)
    "langchain": "#FF9500",  # Orange — Friendly (la toolbox populaire)
    "vanna": "#AF52DE",  # Purple — Creative (le RAG)
}

# Teintes neutres épurées : texte foncé, axe gris très clair, sous-titre gris.
_FG = "#1D1D1F"
_MUTED = "#6E6E73"
_AXIS = "#C7C7CC"

# Bloc config commun, ÉPURÉ : une seule police (Roboto — vl_convert ne bundle pas
# « Roboto Mono »), pas de cadre, pas de grille, pas de ticks, domaine d'axe très
# discret. Le moins d'encre possible pour un maximum de données.
_CONFIG = {
    "font": "Roboto",
    "view": {"stroke": None},
    "axis": {
        "labelFont": "Roboto",
        "titleFont": "Roboto",
        "grid": False,
        "ticks": False,
        "domain": True,
        "domainColor": _AXIS,
        "labelColor": _FG,
        "titleColor": _MUTED,
        "labelFontSize": 12,
        "titleFontSize": 12,
        "titlePadding": 10,
        "labelPadding": 6,
    },
    "axisX": {"domain": True, "domainColor": _AXIS},
    "axisY": {"domain": False},  # pas de barre d'axe verticale : plus léger
    "header": {"labelFont": "Roboto", "titleFont": "Roboto", "labelColor": _FG},
    "title": {
        "font": "Roboto",
        "anchor": "start",
        "fontSize": 16,
        "color": _FG,
        "subtitleFont": "Roboto",
        "subtitleColor": _MUTED,
        "subtitleFontSize": 12,
        "subtitlePadding": 6,
        "offset": 12,
    },
    "legend": {
        "labelFont": "Roboto",
        "titleFont": "Roboto",
        "labelColor": _FG,
        "symbolType": "circle",
    },
}

# Chaînes traduites : tout le texte visible des figures, par langue. Les libellés
# d'approches et de difficulté sont traduits pour que la figure soit 100 % FR ou EN.
_STR: dict[str, dict] = {
    "fr": {
        "violin_title": "Distribution de la latence par approche",
        "violin_sub": "{n} requêtes · temps de génération (secondes) · plus fin = plus rapide",
        "lat_axis": "Latence (s)",
        "acc_title": "Exactitude d'exécution, par difficulté",
        "acc_sub": "part des requêtes dont le résultat est identique à la référence",
        "acc_axis": "Exactitude",
        "scatter_title": "Qualité contre vitesse",
        "scatter_sub": "en haut à gauche = rapide ET juste (le meilleur coin)",
        "scatter_x": "Latence médiane (s)",
        "scatter_y": "Exactitude globale",
        "lower_better": "plus c'est bas, mieux c'est",
        "higher_better": "plus c'est haut, mieux c'est",
        "diff": {"facile": "facile", "moyen": "moyen", "difficile": "difficile"},
        "approach": {
            "qwen": "QwenCoder (bon prompt)",
            "qwen_naive": "QwenCoder (prompt naïf)",
            "langchain": "LangChain",
            "vanna": "Vanna (RAG)",
        },
    },
    "en": {
        "violin_title": "Latency distribution per approach",
        "violin_sub": "{n} queries · generation time (seconds) · thinner = faster",
        "lat_axis": "Latency (s)",
        "acc_title": "Execution accuracy, by difficulty",
        "acc_sub": "share of queries whose result matches the reference",
        "acc_axis": "Accuracy",
        "scatter_title": "Quality versus speed",
        "scatter_sub": "top-left = fast AND accurate (the best corner)",
        "scatter_x": "Median latency (s)",
        "scatter_y": "Overall accuracy",
        "lower_better": "the lower, the better",
        "higher_better": "the higher, the better",
        "diff": {"facile": "Easy", "moyen": "Medium", "difficile": "Hard"},
        "approach": {
            "qwen": "QwenCoder (good prompt)",
            "qwen_naive": "QwenCoder (naive prompt)",
            "langchain": "LangChain",
            "vanna": "Vanna (RAG)",
        },
    },
}


def _ordered_present(report: dict) -> list[dict]:
    """Renvoie les résumés d'approches présents, dans l'ordre pédagogique fixe.

    Parameters
    ----------
    report : dict
        Le rapport ``benchmark_results.json`` parsé.

    Returns
    -------
    list[dict]
        Les résumés des approches mesurées, ordonnés qwen → langchain → vanna.
    """
    order = ["qwen", "qwen_naive", "langchain", "vanna"]
    by_key = {s["key"]: s for s in report.get("summaries", []) if s.get("n")}
    return [by_key[k] for k in order if k in by_key]


def build_violin_spec(report: dict, lang: str = "fr") -> dict:
    """Construit la spec Vega-Lite du violin de latence, dans la langue voulue.

    Parameters
    ----------
    report : dict
        Rapport parsé (contient ``approaches[].records[].latency_s``).
    lang : str
        Langue des libellés (« fr » ou « en »).

    Returns
    -------
    dict
        Spec Vega-Lite v5 : une densité miroir par approche, facettée en colonnes.
    """
    t = _STR[lang]
    present = _ordered_present(report)
    labels = [t["approach"][s["key"]] for s in present]
    colours = [_COLORS[s["key"]] for s in present]

    # Format long : une ligne {approche traduite, latence} par requête mesurée.
    rows: list[dict] = []
    raw = {a["key"]: a for a in report.get("approaches", [])}
    for s in present:
        for rec in raw[s["key"]]["records"]:
            rows.append({"approche": t["approach"][s["key"]], "latence": rec["latency_s"]})

    max_lat = max((r["latence"] for r in rows), default=1.0)
    return {
        "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
        "title": {
            "text": t["violin_title"],
            "subtitle": t["violin_sub"].format(n=report.get("n_cases", 0)),
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
        "mark": {"type": "area", "orient": "horizontal", "opacity": 0.92},
        "width": 120,
        "height": 400,
        "encoding": {
            # Polarité explicite sur l'axe : la latence, plus c'est bas mieux c'est.
            "y": {
                "field": "latence",
                "type": "quantitative",
                "title": f"{t['lat_axis']} — {t['lower_better']}",
            },
            # Densité miroir (stack center) : la forme de la violine, sans axe.
            "x": {
                "field": "densite",
                "type": "quantitative",
                "stack": "center",
                "impute": None,
                "title": None,
                "axis": {
                    "labels": False,
                    "ticks": False,
                    "grid": False,
                    "domain": False,
                    "values": [],
                },
            },
            "column": {
                "field": "approche",
                "type": "nominal",
                "sort": labels,
                "title": None,
                "header": {
                    "titleOrient": "bottom",
                    "labelOrient": "bottom",
                    "labelPadding": 8,
                    "labelFontSize": 13,
                    "labelColor": _FG,
                },
            },
            "color": {
                "field": "approche",
                "type": "nominal",
                "scale": {"domain": labels, "range": colours},
                "legend": None,
            },
        },
    }


def build_accuracy_spec(report: dict, lang: str = "fr") -> dict:
    """Construit les barres d'exactitude par difficulté, avec la valeur écrite dessus.

    Épuré : pas d'axe Y (les pourcentages sont posés sur les barres — la figure
    se lit sans chercher une graduation).

    Parameters
    ----------
    report : dict
        Rapport parsé (contient ``summaries[].accuracy_by_difficulty``).
    lang : str
        Langue des libellés.

    Returns
    -------
    dict
        Spec Vega-Lite v5 : barres groupées + étiquettes de valeur.
    """
    t = _STR[lang]
    present = _ordered_present(report)
    labels = [t["approach"][s["key"]] for s in present]
    colours = [_COLORS[s["key"]] for s in present]
    # Ordre des difficultés traduit, en gardant l'ordre facile→moyen→difficile.
    diff_order = [t["diff"][k] for k in ("facile", "moyen", "difficile")]

    rows: list[dict] = []
    for s in present:
        for niveau in ("facile", "moyen", "difficile"):
            d = s.get("accuracy_by_difficulty", {}).get(niveau)
            if d:
                rows.append(
                    {
                        "approche": t["approach"][s["key"]],
                        "difficulte": t["diff"][niveau],
                        "exactitude": d["accuracy"],
                    }
                )

    # Encodage commun aux barres et aux étiquettes (barres groupées par approche).
    enc = {
        "x": {
            "field": "difficulte",
            "type": "nominal",
            "sort": diff_order,
            "title": None,
            "axis": {"labelAngle": 0, "labelFontSize": 13},
        },
        "xOffset": {"field": "approche", "sort": labels},
        "y": {
            "field": "exactitude",
            "type": "quantitative",
            "scale": {"domain": [0, 1]},
            "axis": None,
        },  # ÉPURÉ : pas d'axe Y, la valeur est sur la barre
        "color": {
            "field": "approche",
            "type": "nominal",
            "scale": {"domain": labels, "range": colours},
            "legend": {"title": None, "orient": "top", "labelFontSize": 13},
        },
    }
    return {
        "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
        # Pas d'axe Y (épuré) → la polarité « plus haut = mieux » va au sous-titre.
        "title": {"text": t["acc_title"], "subtitle": f"{t['acc_sub']} · {t['higher_better']}"},
        "config": _CONFIG,
        "data": {"values": rows},
        "width": 380,
        "height": 300,
        "layer": [
            {"mark": {"type": "bar", "cornerRadiusEnd": 3}, "encoding": enc},
            # Étiquette de valeur au-dessus de chaque barre (« texte bien expliqué »).
            {
                "mark": {"type": "text", "dy": -7, "fontSize": 11, "color": _FG, "font": "Roboto"},
                "encoding": {
                    **enc,
                    "color": {
                        "field": "approche",
                        "type": "nominal",
                        "scale": {"domain": labels, "range": colours},
                        "legend": None,
                    },
                    "text": {"field": "exactitude", "type": "quantitative", "format": ".0%"},
                },
            },
        ],
    }


def build_scatter_spec(report: dict, lang: str = "fr") -> dict:
    """Construit le nuage « qualité vs vitesse » (latence médiane × exactitude).

    Parameters
    ----------
    report : dict
        Rapport parsé (contient ``summaries``).
    lang : str
        Langue des libellés.

    Returns
    -------
    dict
        Spec Vega-Lite v5 : un point par approche + son étiquette.
    """
    t = _STR[lang]
    present = _ordered_present(report)
    labels = [t["approach"][s["key"]] for s in present]
    colours = [_COLORS[s["key"]] for s in present]

    rows = [
        {
            "approche": t["approach"][s["key"]],
            "latence_med": s["latency_median"],
            "exactitude": s["accuracy"],
        }
        for s in present
    ]

    base_enc = {
        # Polarité sur les DEUX axes : latence (bas = mieux), exactitude (haut = mieux).
        "x": {
            "field": "latence_med",
            "type": "quantitative",
            "title": f"{t['scatter_x']} — {t['lower_better']}",
            "scale": {"zero": True, "nice": True},
        },
        "y": {
            "field": "exactitude",
            "type": "quantitative",
            "title": f"{t['scatter_y']} — {t['higher_better']}",
            "axis": {"format": "%"},
            "scale": {"domain": [0, 1]},
        },
        "color": {
            "field": "approche",
            "type": "nominal",
            "scale": {"domain": labels, "range": colours},
            "legend": None,
        },
    }
    return {
        "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
        "title": {"text": t["scatter_title"], "subtitle": t["scatter_sub"]},
        "config": _CONFIG,
        "data": {"values": rows},
        "width": 420,
        "height": 320,
        "layer": [
            {
                "mark": {"type": "point", "filled": True, "size": 260, "opacity": 0.95},
                "encoding": base_enc,
            },
            {
                "mark": {
                    "type": "text",
                    "dy": -16,
                    "font": "Roboto",
                    "fontWeight": "bold",
                    "fontSize": 13,
                },
                "encoding": {**base_enc, "text": {"field": "approche"}},
            },
        ],
    }


def render_all(report: dict | None = None, langs: tuple[str, ...] = ("fr", "en")) -> list[Path]:
    """Rend les trois figures en PNG, pour chaque langue, et renvoie leurs chemins.

    Parameters
    ----------
    report : dict | None
        Rapport pré-chargé ; lu depuis le disque si ``None``.
    langs : tuple[str, ...]
        Langues à produire (``fr`` → ``docs/img/fr/``, ``en`` → ``docs/img/en/``).

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

    if report is None:
        if not _RESULTS_PATH.is_file():
            raise FileNotFoundError(
                f"{_RESULTS_PATH} introuvable — lancez `python -m eval.benchmark`."
            )
        report = json.loads(_RESULTS_PATH.read_text(encoding="utf-8"))

    written: list[Path] = []
    # Une sous-arborescence par langue : docs/img/fr, docs/img/en.
    for lang in langs:
        out_dir = _IMG_DIR / lang
        out_dir.mkdir(parents=True, exist_ok=True)
        figures = [
            ("bench-latency-violin.png", build_violin_spec(report, lang)),
            ("bench-accuracy-difficulty.png", build_accuracy_spec(report, lang)),
            ("bench-quality-vs-speed.png", build_scatter_spec(report, lang)),
        ]
        for name, spec in figures:
            # Rendu 2× pour un PNG net (retina) dans la doc.
            png = vlc.vegalite_to_png(vl_spec=json.dumps(spec), scale=2.0)
            path = out_dir / name
            path.write_bytes(png)
            written.append(path)
            logger.info("Figure écrite : %s", path)
    return written


def main() -> int:
    """CLI : rend les figures du benchmark (fr et/ou en) et affiche leurs chemins.

    Returns
    -------
    int
        Code de sortie (0).
    """
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description="Figures du benchmark (bilingues).")
    parser.add_argument("--lang", choices=["fr", "en", "all"], default="all")
    args = parser.parse_args()
    langs = ("fr", "en") if args.lang == "all" else (args.lang,)
    for path in render_all(langs=langs):
        logger.info("→ %s", path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
