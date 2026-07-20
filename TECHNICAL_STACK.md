# Stack technique — Démo text2SQL (Hôpital)

> Carte de la stack : *quelle brique, pour quel rôle, et pourquoi.* Document de référence
> pour reprendre le projet ou l'auditer. Tout est **100 % local** (Ollama) — aucune donnée
> ne quitte la machine, aucune clé d'API, aucun cloud.

## Philosophie

Artefact **pédagogique** (pas un produit) : montrer *comment* le text-to-SQL marche et
*quelle* approche choisir, en isolant **une seule variable** — comment le schéma de la base
atteint le LLM — pour que la différence se **lise** au lieu d'être assénée. D'où : même LLM
partout, même base, même garde-fou d'exécution ; seul change le contexte fourni au modèle.

## Langage & runtime

| Élément | Choix | Notes |
|---|---|---|
| Langage | **Python ≥ 3.10** (dev en 3.13) | `requires-python = ">=3.10"` |
| Licence | **MIT** | `pyproject.toml` |
| Version paquet | `text2sql-hopital` v1.1.0 | — |
| LLM runtime | **[Ollama](https://ollama.com)** (local) | serveur de modèles ; en multi-users/concurrence, préférer **vLLM** |

### Modèles (Ollama), un rôle chacun
| Modèle | Rôle |
|---|---|
| `qwen2.5-coder` | **génération SQL** — le même pour les 5 configs (comparaison honnête) |
| `gemma4:e4b-mlx` | **choix de la figure** → spec Vega-Lite |
| `nomic-embed-text` | **embeddings** du RAG Vanna (ChromaDB) |

## Données

- **SQLite** — `data/institut.db` : 30 tables, ~33 000 lignes, parcours de soins cohérent
  (dx → traitement → cures/séances/chirurgie → imagerie → labo → facturation).
- **[Faker](https://faker.readthedocs.io/)** — données synthétiques françaises réalistes (seed fixe, 0 donnée réelle).
- **`data/institut_wide.db`** — variante « gros schéma » (`backend/widen_db.py` : mêmes tables +
  ~130 colonnes de décor NULL/table → DDL ×18) pour l'étude *petit vs gros schéma* (l'inversion RAG).

## Les approches text2SQL

Toutes exposent le même contrat (`backend/approaches/base.py`) ; seul diffère l'accès au schéma.

| # | Approche | Module | Stack |
|---|---|---|---|
| 1 | **QwenCoder brut** (bon prompt + naïf) | `qwen_ollama.py` | prompt écrit à la main + client Ollama synchrone (`requests`) ; DDL introspecté ; auto-correction sur erreur d'exécution |
| 2 | **LangChain** | `langchain_sql.py` | `langchain` + `langchain-community` + `langchain-ollama` + `sqlalchemy` (`SQLDatabase` + LCEL + `ChatOllama`) |
| 3 | **Vanna AI (RAG 1 & 2)** | `vanna_rag.py` | `vanna` + `chromadb` (index schéma + docs + exemples) ; `n_results` ; auto-correction |
| + | **Figures** | `figures.py` | `gemma4` → **spec Vega-Lite** (jamais du code exécuté) |

> Le client Ollama synchrone reprend le **style** du framework local de l'auteur, `roitelet`
> (docstrings numpy, commentaires), mais reste autoportant.

## API & Front

| Couche | Stack |
|---|---|
| **API** | **FastAPI** + **uvicorn** (ASGI) + **pydantic** (`backend/server.py`) |
| **Front** | **vanilla JS** + **Tailwind** (vendored) + **Vega-Lite** (rendu des figures) ; `frontend/{index.html,app.js,i18n.js}` |
| **i18n** | **`locales/i18n.yaml`** = source de vérité unique (chaînes GUI **et** prompts) ; `backend/prompts.py` (chargeur YAML, cache) ; `/api/i18n` expose les chaînes |
| **Langue** | **`langdetect`** — détecte fr/en de la question, prompts *language-aware*, affiché dans le front |

## Sécurité (garde-fous)

- `backend/db.py` : connexion SQLite **`mode=ro`** (lecture seule), **un seul `SELECT`** autorisé,
  mots-clés d'écriture rejetés, **`LIMIT` défensif**.
- Le SQL généré par le LLM n'est **jamais** exécuté par les frameworks eux-mêmes — tout passe par `db.py`.
- Les figures sont des **specs Vega-Lite** déclaratives (inertes), pas du code → pas de RCE.
- Motivé en partie par le **CVE d'exécution de code de Vanna** (voir `PROS_CONS.md`).

## Évaluation & benchmark (CODING.md §14)

| Outil | Rôle | Fichier |
|---|---|---|
| **DeepEval** | métrique **exactitude d'exécution** (100 % locale, pas de juge OpenAI) | `eval/deepeval_metric.py` |
| **Giskard** | scan de **robustesse** (invariance sous perturbation) | `eval/giskard_scan.py` |
| Golden set | requêtes de référence (dont `GOLDEN_HARD`) | `eval/golden.py`, `eval/run_eval.py` |
| Benchmark | jeu **équilibré 768** (256/256/256) × 5 configs, exécution + latence robuste | `eval/benchmark.py`, `eval/benchmark_set.py` |
| Comparaison | **execution accuracy** (compare les *résultats*, pas le texte — cf. Spider/BIRD) | `eval/execution_match.py` |

## Figures

- Specs **Vega-Lite** (house style *front-figures*), rendues en **PNG** via **`vl-convert-python`**
  (module `vl_convert`) — `eval/bench_charts.py`.
- Boucle de validation *export → regarde → corrige* appliquée (violin plafonné, axes, palette).
- **Identité couleur par moteur** (palette harchaoui.org) figée : qwen 🟦 bleu · naïf 🟪 violet ·
  LangChain 🟩 vert · Vanna 1 🟧 orange · Vanna 2 🟥 rouge — propagée Vega + Mermaid + texte.

## EDA (companion pédagogique)

- **`skrub.TableReport`** (`backend/eda_report.py`) + **pandas** — profil interactif « voici les données ».
  N'entre **pas** dans le pipeline text2sql (artefact séparé). *skore* écarté (pas d'estimateur sklearn ici).

## Outillage, style, CI

| Élément | Choix |
|---|---|
| Lint + format | **Ruff** (`line-length = 100`, `select = E/W/F/I/D/UP/B`, docstrings **numpy**) — garde bloquante |
| Tests | **pytest** + **pytest-cov** ; suite rapide (mock) + tests lents marqués (Ollama réel) |
| Test API | **httpx** (`fastapi.testclient`) |
| Captures | **Playwright** (chromium) — régénère `docs/screenshots` et validation visuelle |
| CI | **GitHub Actions** — `ruff check` + `ruff format --check` + `pytest -q -m "not slow"` |

## Documentation

`README.md` (EN) ↔ `LISEZMOI.md` (FR) · `USERGUIDE.md` ↔ `MODEDEMPLOI.md` · `PROS_CONS.md`
(comparatif sourcé + CVE) · `EXAMPLES.md` (recettes) ·
`CODING.md` (standard) · diagrammes **Mermaid** (archi, 5 moteurs, carte du dépôt).

## Récapitulatif des dépendances par rôle

```
Cœur démo      faker · requests · fastapi · uvicorn · pydantic · langdetect · pyyaml
Approche 1     (cœur ci-dessus : requests → Ollama)
Approche 2     langchain · langchain-community · langchain-ollama · sqlalchemy
Approche 3     vanna · chromadb            (embeddings : nomic-embed-text via Ollama)
Éval IA        deepeval · giskard
Benchmark/fig  vl-convert-python
EDA            skrub · pandas
Dev/CI         pytest · pytest-cov · ruff · httpx · playwright
```

> Les approches 2 et 3 et la couche éval sont **optionnelles** : sans leurs paquets, elles se
> déclarent indisponibles / se skippent proprement. La démo cœur (QwenCoder + figures) tourne
> avec le seul bloc « Cœur démo » + Ollama.
