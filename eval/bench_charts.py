"""
bench_charts.py — Figures du benchmark (Vega-Lite → PNG), bilingues et épurées.

Lit ``eval/benchmark_results.json`` (produit par :mod:`eval.benchmark`) et rend,
**en français et en anglais**, quatre figures dans un style volontairement épuré
(pas de cadre, pas de grille, pas de ticks, texte qui explique la lecture),
avec la palette https://harchaoui.org/warith/colors/ :

  1. **Violin de latence** — distribution complète du temps de génération
     (densité miroir), inspiré de ``eval/violin.py`` du projet ``intentions``.
  2. **Exactitude par difficulté** — barres avec la valeur écrite dessus (pas
     besoin de lire un axe : la figure « parle » toute seule).
  3. **Qualité vs vitesse** — nuage (latence médiane × exactitude) : le compromis.
  4. **Anatomie des erreurs** — barres empilées correct / erreur d'exécution /
     erreur sémantique (la « silencieuse ») : « analyser les erreurs pour faire mieux ».

Chaque langue écrit dans ``docs/img/<lang>/`` : ``fr`` pour la doc française
(section « Benchmark » de ``LISEZMOI.md``), ``en`` pour l'anglaise (``README.md``).

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

# IDENTITÉ COULEUR DES MOTEURS — source de vérité unique, réutilisée partout
# (figures Vega ici, diagrammes Mermaid et texte des .md). Palette officielle
# https://harchaoui.org/warith/colors/ : chaque teinte a un SENS qui colle au
# moteur. Une couleur = un moteur, du début à la fin, pour que l'œil relie
# instantanément un point/nœud/mot à son approche.
# Ordre canonique PARTOUT : naïf → bon → LangChain → Vanna 1 → Vanna 2
# (progression pédagogique : on part du témoin « paresseux », puis on améliore).
_COLORS: dict[str, str] = {
    "qwen_naive": "#AF52DE",  # Purple (le témoin « prompt naïf »)
    "qwen": "#007AFF",  # Blue — Trust/Reliable (bon prompt : on contrôle tout)
    "langchain": "#28CD41",  # Green (la toolbox populaire)
    "vanna": "#FF9500",  # Orange (RAG basique = Vanna 1)
    "vanna_plus": "#FF3B30",  # Red — Power/Strength (RAG bien nourri = Vanna 2)
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
        "violin_sub": "{n} requêtes · densité du temps de génération (s) · plus bas = plus rapide",
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
        "err_title": "Anatomie des erreurs, par approche",
        "err_sub": "correct vs erreur d'exécution vs erreur sémantique (la silencieuse)",
        "err_ok": "correct",
        "err_exec": "erreur d'exécution",
        "err_sem": "erreur sémantique",
        "lh_acc_title": "Petit schéma vs gros schéma : l'inversion (exactitude)",
        "lh_acc_sub": "même jeu de questions, deux bases · à gauche le schéma tient dans "
        "le prompt, à droite non · plus c'est long, mieux c'est",
        "lh_lat_title": "Petit schéma vs gros schéma : le coût du prompt géant (latence)",
        "lh_lat_sub": "latence médiane de génération · attention à l'échelle : "
        "le gros schéma se compte en dizaines de secondes",
        "regime_light": "Petit schéma (tient dans le prompt)",
        "regime_heavy": "Gros schéma (déborde du prompt)",
        "diff": {"facile": "Facile", "moyen": "Moyen", "difficile": "Difficile"},
        "approach": {
            "qwen": "QwenCoder (bon prompt)",
            "qwen_naive": "QwenCoder (prompt naïf)",
            "langchain": "LangChain",
            "vanna": "Vanna 1",
            "vanna_plus": "Vanna 2",
        },
    },
    "en": {
        "violin_title": "Latency distribution per approach",
        "violin_sub": "{n} queries · generation-time density (s) · lower = faster",
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
        "err_title": "Anatomy of errors, per approach",
        "err_sub": "correct vs execution error (invalid SQL) vs semantic error (silent)",
        "err_ok": "correct",
        "err_exec": "execution error",
        "err_sem": "semantic error",
        "lh_acc_title": "Small schema vs large schema: the reversal (accuracy)",
        "lh_acc_sub": "same question set, two databases · left: the schema fits in the "
        "prompt, right: it does not · the longer, the better",
        "lh_lat_title": "Small schema vs large schema: the cost of a giant prompt (latency)",
        "lh_lat_sub": "median generation latency · mind the scale: the large schema "
        "is measured in tens of seconds",
        "regime_light": "Small schema (fits in the prompt)",
        "regime_heavy": "Large schema (overflows the prompt)",
        "diff": {"facile": "Easy", "moyen": "Medium", "difficile": "Hard"},
        "approach": {
            "qwen": "QwenCoder (good prompt)",
            "qwen_naive": "QwenCoder (naive prompt)",
            "langchain": "LangChain",
            "vanna": "Vanna 1",
            "vanna_plus": "Vanna 2",
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
    order = ["qwen_naive", "qwen", "langchain", "vanna", "vanna_plus"]
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

    # Plafond ROBUSTE : quelques outliers (machine occupée → 60 s) écraseraient
    # sinon tous les violons au bas de l'axe. On borne l'axe au 97ᵉ centile pour
    # que la forme des distributions reste lisible (les rares points au-dessus
    # sont hors cadre — c'est le but : montrer le corps de la distribution).
    lats = sorted(r["latence"] for r in rows) or [1.0]
    cap = lats[min(len(lats) - 1, int(0.97 * len(lats)))]
    cap = max(cap, 1.0)
    # La densité (KDE) est bornée au plafond ``cap`` : les rares outliers (machine
    # occupée → 60 s) restent hors extent et n'écrasent pas les violons. La queue
    # fine des distributions asymétriques (Vanna, bon prompt) s'arrête donc à ``cap``.
    kde_top = cap
    # On place le HAUT de l'axe un cran au-dessus de ``cap`` : la queue fine finit
    # ainsi en dessous du bord, avec un peu d'air — au lieu de coller à l'arête
    # supérieure du cadre (ce qui se lisait comme un artefact de troncature).
    axis_top = cap * 1.10
    return {
        "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
        "title": {
            "text": t["violin_title"],
            "subtitle": t["violin_sub"].format(n=report.get("n_cases", 0)),
        },
        "config": _CONFIG,
        "data": {"values": rows},
        # KDE de la latence dans chaque approche, sur [0, cap] → violines comparables.
        "transform": [
            {
                "density": "latence",
                "groupby": ["approche"],
                "extent": [0, kde_top],
                "as": ["latence", "densite"],
            }
        ],
        "mark": {"type": "area", "orient": "horizontal", "opacity": 0.92, "clip": True},
        "width": 160,
        "height": 400,
        "encoding": {
            # Polarité explicite sur l'axe : la latence, plus c'est bas mieux c'est.
            "y": {
                "field": "latence",
                "type": "quantitative",
                "title": f"{t['lat_axis']} — {t['lower_better']}",
                "scale": {"domain": [0, axis_top]},
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
                    "labelFontSize": 11,
                    "labelLimit": 200,
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

    # Barres HORIZONTALES groupées : elles partent de 0 (à gauche) et remplissent
    # l'espace par leur longueur (67–100 % = barres longues) ; 3 groupes × 5 moteurs
    # empilés verticalement → densité maximale, aucune barre « flottante ».
    enc = {
        "y": {
            "field": "difficulte",
            "type": "nominal",
            "sort": diff_order,
            "title": None,
            "axis": {"labelFontSize": 14, "labelFontWeight": "bold", "labelPadding": 8},
        },
        "yOffset": {"field": "approche", "sort": labels},
        "x": {
            "field": "exactitude",
            "type": "quantitative",
            "scale": {"domain": [0, 1]},
            "axis": None,
        },  # ÉPURÉ : pas d'axe X, la valeur est écrite au bout de la barre
        "color": {
            "field": "approche",
            "type": "nominal",
            "scale": {"domain": labels, "range": colours},
            "legend": {"title": None, "orient": "top", "labelFontSize": 13},
        },
    }
    return {
        "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
        # Pas d'axe de valeur (épuré) → la polarité « plus haut = mieux » va au sous-titre.
        "title": {"text": t["acc_title"], "subtitle": f"{t['acc_sub']} · {t['higher_better']}"},
        "config": _CONFIG,
        "data": {"values": rows},
        "width": 560,
        "height": 340,
        "layer": [
            {
                "mark": {"type": "bar", "cornerRadiusEnd": 3, "height": {"band": 0.82}},
                "encoding": enc,
            },
            # Étiquette de valeur AU BOUT de chaque barre (« texte bien expliqué »).
            {
                "mark": {
                    "type": "text",
                    "align": "left",
                    "baseline": "middle",
                    "dx": 4,
                    "fontSize": 11,
                    "font": "Roboto",
                },
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
            "key": s["key"],
            "latence_med": s["latency_median"],
            "exactitude": s["accuracy"],
        }
        for s in present
    ]

    # Placement MANUEL des étiquettes : les points se regroupent (qwen ≈ qwen_naive
    # en haut, vanna ≈ vanna_plus à droite). Sans décalage dédié, les libellés se
    # chevaucheraient. On décale chacun (au-dessus / au-dessous / à droite) et on
    # ancre en conséquence pour que rien ne se recouvre — une couche texte par point.
    label_pos: dict[str, dict] = {
        "qwen": {"dx": 0, "dy": 20, "align": "center", "baseline": "top"},
        "qwen_naive": {"dx": 0, "dy": -14, "align": "center", "baseline": "bottom"},
        "langchain": {"dx": 0, "dy": 20, "align": "center", "baseline": "top"},
        "vanna": {"dx": 0, "dy": 20, "align": "center", "baseline": "top"},
        "vanna_plus": {"dx": 0, "dy": -14, "align": "center", "baseline": "bottom"},
    }

    # Marge à droite : le point le plus lent est près du bord ; on étend le domaine
    # X pour que son étiquette centrée ne déborde pas du cadre.
    max_lat = max((r["latence_med"] for r in rows), default=1.0)
    x_max = max_lat * 1.35
    # Zoom vertical : toutes les exactitudes tiennent dans ~84–91 %. Un axe 0–100 %
    # gâcherait l'espace et écraserait les écarts. On zoome sous le point le plus bas
    # (base non nulle : légitime pour un nuage, ≠ barres) et on AFFICHE l'axe Y
    # (graduation + ligne + grille légère) pour lire les valeurs sans ambiguïté.
    min_acc = min((r["exactitude"] for r in rows), default=0.0)
    y_min = max(0.0, min_acc - 0.15)

    base_enc = {
        # Polarité sur les DEUX axes : latence (bas = mieux), exactitude (haut = mieux).
        "x": {
            "field": "latence_med",
            "type": "quantitative",
            "title": f"{t['scatter_x']} — {t['lower_better']}",
            "scale": {"domain": [0, x_max]},
        },
        "y": {
            "field": "exactitude",
            "type": "quantitative",
            "title": f"{t['scatter_y']} — {t['higher_better']}",
            "axis": {
                "format": "%",
                "domain": True,
                "domainColor": _AXIS,
                "ticks": True,
                "tickColor": _AXIS,
                "grid": True,
                "gridColor": "#EFEFF2",
                "labelFontSize": 12,
            },
            "scale": {"domain": [y_min, 1.0], "nice": False},
        },
        "color": {
            "field": "approche",
            "type": "nominal",
            "scale": {"domain": labels, "range": colours},
            "legend": None,
        },
    }
    # Une couche texte par point, chacune filtrée sur sa clé et placée sur mesure.
    text_layers = [
        {
            "transform": [{"filter": f"datum.key === '{s['key']}'"}],
            "mark": {
                "type": "text",
                "font": "Roboto",
                "fontWeight": "bold",
                "fontSize": 13,
                **{k: v for k, v in label_pos[s["key"]].items() if k in ("dx", "dy")},
                "align": label_pos[s["key"]]["align"],
                "baseline": label_pos[s["key"]]["baseline"],
            },
            "encoding": {**base_enc, "text": {"field": "approche"}},
        }
        for s in present
    ]
    return {
        "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
        "title": {"text": t["scatter_title"], "subtitle": t["scatter_sub"]},
        "config": _CONFIG,
        "data": {"values": rows},
        "width": 460,
        "height": 320,
        "layer": [
            {
                "mark": {"type": "point", "filled": True, "size": 180, "opacity": 0.95},
                "encoding": base_enc,
            },
            *text_layers,
        ],
    }


def build_errors_spec(report: dict, lang: str = "fr") -> dict:
    """Barres empilées : part correct / erreur d'exécution / erreur sémantique.

    L'anatomie des échecs distingue l'**erreur d'exécution** (SQL invalide, la base
    refuse) de l'**erreur sémantique** (SQL valide mais mauvais résultat — la plus
    dangereuse, « silencieuse »). Idéal pour « analyser les erreurs pour faire mieux ».

    Parameters
    ----------
    report : dict
        Rapport parsé (``summaries[].errors`` + ``accuracy`` + ``n``).
    lang : str
        Langue des libellés.

    Returns
    -------
    dict
        Spec Vega-Lite v5 : une barre empilée normalisée par approche.
    """
    t = _STR[lang]
    present = _ordered_present(report)
    labels = [t["approach"][s["key"]] for s in present]
    # Trois issues, dans l'ORDRE d'empilement = ordre de légende (correct →
    # exécution → sémantique) avec des couleurs demandées : vert / rouge / jaune.
    types = [t["err_ok"], t["err_exec"], t["err_sem"]]
    colours = ["#28CD41", "#FF3B30", "#FFCC00"]  # correct / exécution / sémantique

    rows: list[dict] = []
    for s in present:
        n = s["n"] or 1
        err = s.get("errors", {})
        exec_n = err.get("exec", 0)
        sem_n = err.get("semantique", 0)
        ok_n = n - exec_n - sem_n
        # Une ligne par (approche × issue) ; « ordre » fixe l'empilement ET la légende.
        rows.append(
            {"approche": t["approach"][s["key"]], "type": t["err_ok"], "part": ok_n / n, "ordre": 0}
        )
        rows.append(
            {
                "approche": t["approach"][s["key"]],
                "type": t["err_exec"],
                "part": exec_n / n,
                "ordre": 1,
            }
        )
        rows.append(
            {
                "approche": t["approach"][s["key"]],
                "type": t["err_sem"],
                "part": sem_n / n,
                "ordre": 2,
            }
        )

    return {
        "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
        "title": {"text": t["err_title"], "subtitle": t["err_sub"]},
        "config": _CONFIG,
        "data": {"values": rows},
        "mark": {"type": "bar"},
        "width": 460,
        "height": 300,
        "encoding": {
            "y": {
                "field": "approche",
                "type": "nominal",
                "sort": labels,
                "title": None,
                "axis": {"labelFontSize": 13},
            },
            "x": {
                "field": "part",
                "type": "quantitative",
                "stack": "normalize",
                "axis": {"format": "%"},
                "title": None,
            },
            "color": {
                "field": "type",
                "type": "nominal",
                # domaine dans l'ordre correct→exécution→sémantique → légende alignée.
                "scale": {"domain": types, "range": colours},
                "legend": {"title": None, "orient": "bottom"},
            },
            # Empilement dans le même ordre que la légende (0→1→2).
            "order": {"field": "ordre", "type": "quantitative"},
        },
    }


def _lightheavy_rows(light: dict, heavy: dict, lang: str, field: str) -> list[dict]:
    """Assemble les lignes {moteur, régime, valeur} pour les figures LIGHT vs HEAVY.

    Parameters
    ----------
    light : dict
        Rapport du benchmark sur la base LIGHT (petit schéma).
    heavy : dict
        Rapport du benchmark sur la base HEAVY (gros schéma), même jeu.
    lang : str
        Langue des libellés.
    field : str
        Champ du résumé à lire (``accuracy`` ou ``latency_median``).

    Returns
    -------
    list[dict]
        Une ligne par (moteur × régime) présent dans les deux rapports.
    """
    t = _STR[lang]
    order = ["qwen_naive", "qwen", "langchain", "vanna", "vanna_plus"]
    rows: list[dict] = []
    # On garde l'ordre canonique des moteurs pour que seule la LONGUEUR des barres
    # change d'un régime à l'autre : l'œil voit alors l'inversion du classement.
    for regime_key, report in (("regime_light", light), ("regime_heavy", heavy)):
        by_key = {s["key"]: s for s in report.get("summaries", []) if s.get("n")}
        for key in order:
            if key in by_key:
                rows.append(
                    {
                        "moteur": t["approach"][key],
                        "key": key,
                        "regime": t[regime_key],
                        "valeur": by_key[key][field],
                    }
                )
    return rows


def build_lightheavy_accuracy_spec(light: dict, heavy: dict, lang: str = "fr") -> dict:
    """Barres d'exactitude par moteur, facettées petit schéma vs gros schéma.

    Le classement (qui est en tête) change d'une facette à l'autre : c'est
    l'inversion. On garde l'ordre canonique des moteurs pour que seule la longueur
    des barres bouge, et on écrit la valeur au bout de chaque barre (figure
    auto-suffisante, sans axe à déchiffrer).

    Parameters
    ----------
    light : dict
        Rapport LIGHT (petit schéma).
    heavy : dict
        Rapport HEAVY (gros schéma).
    lang : str
        Langue des libellés.

    Returns
    -------
    dict
        Spec Vega-Lite v5 facettée par régime.
    """
    t = _STR[lang]
    labels = [t["approach"][k] for k in ("qwen_naive", "qwen", "langchain", "vanna", "vanna_plus")]
    colours = [_COLORS[k] for k in ("qwen_naive", "qwen", "langchain", "vanna", "vanna_plus")]
    rows = _lightheavy_rows(light, heavy, lang, "accuracy")
    regimes = [t["regime_light"], t["regime_heavy"]]

    enc = {
        "y": {
            "field": "moteur",
            "type": "nominal",
            "sort": labels,
            "title": None,
            "axis": {"labelFontSize": 12},
        },
        "x": {"field": "valeur", "type": "quantitative", "scale": {"domain": [0, 1]}, "axis": None},
        "color": {
            "field": "moteur",
            "type": "nominal",
            "scale": {"domain": labels, "range": colours},
            "legend": None,
        },
    }
    return {
        "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
        "title": {"text": t["lh_acc_title"], "subtitle": t["lh_acc_sub"]},
        "config": _CONFIG,
        "data": {"values": rows},
        "columns": 2,
        "facet": {
            "field": "regime",
            "type": "nominal",
            "sort": regimes,
            "title": None,
            "header": {"labelFontSize": 13, "labelFontWeight": "bold", "labelColor": _FG},
        },
        "spec": {
            "width": 300,
            "height": 220,
            "layer": [
                {
                    "mark": {"type": "bar", "cornerRadiusEnd": 3, "height": {"band": 0.82}},
                    "encoding": enc,
                },
                {
                    "mark": {
                        "type": "text",
                        "align": "left",
                        "baseline": "middle",
                        "dx": 4,
                        "fontSize": 11,
                        "font": "Roboto",
                        "color": _FG,
                    },
                    "encoding": {
                        **enc,
                        "color": {"value": _FG},
                        "text": {"field": "valeur", "type": "quantitative", "format": ".0%"},
                    },
                },
            ],
        },
    }


def build_lightheavy_latency_spec(light: dict, heavy: dict, lang: str = "fr") -> dict:
    """Barres de latence médiane par moteur, facettées petit vs gros schéma.

    Montre l'AUTRE moitié de l'histoire : sur le gros schéma, les approches qui
    collent tout le schéma dans le prompt (QwenCoder, LangChain) paient un coût de
    latence énorme (dizaines de secondes), tandis que le RAG (Vanna) reste sobre.
    Chaque facette a sa propre échelle X (``resolve``) car les ordres de grandeur
    sont incomparables ; la valeur est écrite en secondes au bout de la barre.

    Parameters
    ----------
    light : dict
        Rapport LIGHT (petit schéma).
    heavy : dict
        Rapport HEAVY (gros schéma).
    lang : str
        Langue des libellés.

    Returns
    -------
    dict
        Spec Vega-Lite v5 facettée par régime, échelle X indépendante.
    """
    t = _STR[lang]
    labels = [t["approach"][k] for k in ("qwen_naive", "qwen", "langchain", "vanna", "vanna_plus")]
    colours = [_COLORS[k] for k in ("qwen_naive", "qwen", "langchain", "vanna", "vanna_plus")]
    rows = _lightheavy_rows(light, heavy, lang, "latency_median")
    regimes = [t["regime_light"], t["regime_heavy"]]

    enc = {
        "y": {
            "field": "moteur",
            "type": "nominal",
            "sort": labels,
            "title": None,
            "axis": {"labelFontSize": 12},
        },
        "x": {"field": "valeur", "type": "quantitative", "axis": None},
        "color": {
            "field": "moteur",
            "type": "nominal",
            "scale": {"domain": labels, "range": colours},
            "legend": None,
        },
    }
    return {
        "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
        "title": {"text": t["lh_lat_title"], "subtitle": t["lh_lat_sub"]},
        "config": _CONFIG,
        "data": {"values": rows},
        "columns": 2,
        "facet": {
            "field": "regime",
            "type": "nominal",
            "sort": regimes,
            "title": None,
            "header": {"labelFontSize": 13, "labelFontWeight": "bold", "labelColor": _FG},
        },
        # Échelle X propre à chaque facette : petit schéma ≈ secondes, gros ≈ minutes.
        "resolve": {"scale": {"x": "independent"}},
        "spec": {
            "width": 300,
            "height": 220,
            "layer": [
                {
                    "mark": {"type": "bar", "cornerRadiusEnd": 3, "height": {"band": 0.82}},
                    "encoding": enc,
                },
                {
                    "mark": {
                        "type": "text",
                        "align": "left",
                        "baseline": "middle",
                        "dx": 4,
                        "fontSize": 11,
                        "font": "Roboto",
                        "color": _FG,
                    },
                    "encoding": {
                        **enc,
                        "color": {"value": _FG},
                        "text": {"field": "valeur", "type": "quantitative", "format": ".1f"},
                    },
                },
            ],
        },
    }


def render_lightheavy(
    light_path: Path, heavy_path: Path, langs: tuple[str, ...] = ("fr", "en")
) -> list[Path]:
    """Rend les figures LIGHT vs HEAVY (exactitude + latence), par langue.

    Parameters
    ----------
    light_path : pathlib.Path
        JSON du benchmark sur la base LIGHT.
    heavy_path : pathlib.Path
        JSON du benchmark sur la base HEAVY (même jeu de questions).
    langs : tuple[str, ...]
        Langues à produire.

    Returns
    -------
    list[pathlib.Path]
        Les chemins des PNG écrits.
    """
    import vl_convert as vlc

    light = json.loads(Path(light_path).read_text(encoding="utf-8"))
    heavy = json.loads(Path(heavy_path).read_text(encoding="utf-8"))
    written: list[Path] = []
    for lang in langs:
        out_dir = _IMG_DIR / lang
        out_dir.mkdir(parents=True, exist_ok=True)
        figures = [
            (
                "bench-light-vs-heavy-accuracy.png",
                build_lightheavy_accuracy_spec(light, heavy, lang),
            ),
            ("bench-light-vs-heavy-latency.png", build_lightheavy_latency_spec(light, heavy, lang)),
        ]
        for name, spec in figures:
            png = vlc.vegalite_to_png(vl_spec=json.dumps(spec), scale=2.0)
            path = out_dir / name
            path.write_bytes(png)
            written.append(path)
            logger.info("Figure écrite : %s", path)
    return written


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
            ("bench-errors.png", build_errors_spec(report, lang)),
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
