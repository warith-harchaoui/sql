# Examples — Text2SQL demo cookbook

Runnable recipes for the hospital text2sql demo. All commands assume the
repository root as the working directory, a running `ollama serve`, and
`pip install -r requirements.txt` done. See [`README.md`](README.md) for setup and
[`PROS_CONS.md`](PROS_CONS.md) for the approach comparison.

> The examples below use `print(...)` for readability — that is a tutorial
> exception; the library code itself uses `logging` (see `CODING.md` §6).

---

## 1. Build the database

Deterministic build (seed fixed) — 30 tables, ~33k rows.

```bash
python -m backend.build_db
# Base créée : data/institut.db
#   ...
#   TOTAL                  32775 lignes  (30 tables)
```

Custom output path:

```bash
python -m backend.build_db --out /tmp/my_institut.db
```

---

## 2. Inspect the schema (what the models see)

```python
from backend import db

print(len(db.list_tables()))          # 30
print(db.schema_ddl()[:200])          # CREATE TABLE absences ( ... )
```

Add a few example rows per table to help the model guess filter values:

```python
print(db.schema_ddl(sample_rows=2))   # DDL + /* Exemples ... */ blocks
```

---

## 3. Generate SQL with each approach

### 3a. QwenCoder — raw prompt, no framework

```python
from backend.approaches.qwen_ollama import QwenOllamaApproach
from backend import db

approach = QwenOllamaApproach()
gen = approach.generate("Combien de patients par localisation de cancer ?")
print(gen.sql)
# SELECT localisation, COUNT(DISTINCT patient_id) ... GROUP BY localisation ...

result = db.run_select(gen.sql, max_rows=5)
print(result.columns, result.rows[0])
# ['localisation', 'n'] ['Rein', 47]  # alias 'n' (AS n) ; peut varier selon le modèle
```

### 3b. LangChain — the well-known toolbox

```python
from backend.approaches.langchain_sql import LangChainApproach

lc = LangChainApproach()
print(lc._how)                        # e.g. "reconstruction LCEL (SQLDatabase + ChatOllama)"
gen = lc.generate("Nombre d'employés par catégorie.")
print(gen.sql)                        # SELECT categorie, COUNT(...) FROM employes GROUP BY ...
```

### 3c. Vanna — RAG trained on the schema

```python
from backend.approaches.vanna_rag import VannaApproach

vn = VannaApproach()                  # trains the ChromaDB index on first run
gen = vn.generate("Masse salariale mensuelle par service.")
print(gen.sql)
```

---

## 4. Run everything through the API

Start the server (also serves the web front at `http://localhost:8000`):

```bash
uvicorn backend.server:app --reload --port 8000
```

Health and availability:

```bash
curl -s localhost:8000/api/health | python -m json.tool
# {"ollama_up": true, "approaches": {"qwen": true, "langchain": true, "vanna": true}, ...}
```

Translate + execute one question with a chosen approach:

```bash
curl -s localhost:8000/api/query \
  -H 'Content-Type: application/json' \
  -d '{"question": "Quels médicaments sont sous leur seuil d'\''alerte de stock ?", "approach": "qwen"}' \
  | python -m json.tool
```

Compare **all three** approaches on the same question (`"approach": "toutes"`):

```bash
curl -s localhost:8000/api/query \
  -H 'Content-Type: application/json' \
  -d '{"question": "Chiffre d'\''affaires encaissé par mois en 2026.", "approach": "toutes"}'
```

---

## 5. Let Gemma pick a figure (Vega-Lite)

```python
from backend import figures

res = figures.make_figure(
    "Patients par localisation de cancer",
    columns=["localisation", "n"],
    rows=[["Sein", 47], ["Poumon", 40], ["Côlon", 45]],
)
print(res.spec["chart_type"])         # "bar"
print(res.vega_spec["$schema"])       # https://vega.github.io/schema/vega-lite/v5.json
```

Via the API:

```bash
curl -s localhost:8000/api/figure \
  -H 'Content-Type: application/json' \
  -d '{"question": "Patients par localisation", "columns": ["localisation","n"], "rows": [["Sein",47],["Poumon",40]]}'
```

---

## 6. Evaluate accuracy (execution accuracy)

```bash
python -m eval.run_eval --approach qwen
# Exactitude d'exécution : 100% (10/10)  | seuil 60%  => PASS

python -m eval.run_eval --approach vanna --threshold 0.7
```

Programmatic use:

```python
from eval.run_eval import run_approach_eval

report = run_approach_eval("qwen")
print(report["accuracy"], report["ok"])   # 0.9 True
```

DeepEval-wrapped metric (fully local, no OpenAI judge):

```python
from eval.deepeval_metric import ExecutionAccuracyMetric, deepeval_available

if deepeval_available():
    from deepeval.test_case import LLMTestCase
    metric = ExecutionAccuracyMetric()
    tc = LLMTestCase(
        input="Combien de services ?",
        actual_output="SELECT COUNT(*) FROM services",
        expected_output="SELECT COUNT(*) AS n FROM services",
    )
    print(metric.measure(tc))          # 1.0  (same execution result)
```

Robustness (Giskard-style invariance to question perturbations):

```python
from backend.approaches.qwen_ollama import QwenOllamaApproach
from eval.giskard_scan import robustness_score

report = robustness_score(QwenOllamaApproach(), subset=3)
print(report.score)                    # e.g. 0.83
```

---

## 6b. Full numerical benchmark (latency + speed + accuracy)

Balanced **768-query** set (256 easy / 256 medium / 256 hard), five configs
(same LLM `qwen2.5-coder` everywhere), noise-robust latency + Ollama compute time.

```bash
python -m eval.benchmark --repeats 1   # writes eval/benchmark_results.json (incremental)
python -m eval.bench_charts            # writes bilingual PNGs in docs/img/{fr,en}/
```

Add just one config to an existing report (merges by key — no full re-run):

```bash
python -m eval.benchmark --approaches vanna_plus   # runs "Vanna 2", merges in
```

The **well-fed Vanna** (Vanna 2) is trained with the enumerated column values +
more example pairs — a fair-context comparison against QwenCoder's good prompt:

```python
from backend.approaches.vanna_rag import VannaApproach
vn2 = VannaApproach(rich=True)          # name == "Vanna 2"
print(vn2.generate("Combien de factures sont impayées ?").sql)
```

## 6c. Language detection & i18n (YAML source of truth)

Question language is detected server-side and returned by `/api/query`:

```python
from backend.llm import detect_language
print(detect_language("Combien de patients par sexe ?"))   # fr
print(detect_language("How many patients by sex?"))        # en
```

All UI strings **and** LLM prompts live in `locales/i18n.yaml` (edit there to
translate). The server exposes the GUI strings as JSON:

```bash
curl -s localhost:8000/api/i18n | python -m json.tool   # {"gui": {"en": {...}, "fr": {...}}}
```

```python
from backend import prompts
print(prompts.sql_system("en")[:40])    # English system prompt from the YAML
print(prompts.figure_system("fr")[:40]) # French figure prompt from the YAML
```

## 6d. Small schema vs large schema — the ranking reversal

The whole point of RAG is a schema too big to fit in a prompt. To *measure* it,
build a **HEAVY** copy of the database: same tables, same key columns, same data,
but each table padded with ~130 realistic **decoy** columns (audit / GDPR / legacy
fields, all `NULL`). Only the **DDL size** the LLM sees changes — from ~7.5k to
~132k characters (×18) — so the reference SQL still runs unchanged.

```bash
python -m backend.widen_db                       # writes data/institut_wide.db
```

Run the same question set on both databases (a small per-tier sample: on HEAVY the
giant prompt makes generation slow, ~100 s/query for schema-in-prompt approaches):

```bash
python -m eval.benchmark --per-level 8 --out eval/benchmark_light_sample.json
python -m eval.benchmark --per-level 8 --db data/institut_wide.db \
                         --out eval/benchmark_heavy_sample.json
```

Then render the two comparison figures (accuracy + latency, faceted by regime):

```python
from pathlib import Path
from eval.bench_charts import render_lightheavy
render_lightheavy(Path("eval/benchmark_light_sample.json"),
                  Path("eval/benchmark_heavy_sample.json"))   # docs/img/{fr,en}/bench-light-vs-heavy-*.png
```

On **LIGHT**, QwenCoder (whole schema in the prompt) leads; on **HEAVY**, the
prompt overflows and the retrieval-based Vanna moves ahead — the reversal that
justifies RAG. See the "Small schema vs large schema" section of the README.

## 6e. Explore the data with skrub (companion EDA)

A pedagogical profile of the hospital tables the LLM queries — `skrub.TableReport`
gives types, missing values, cardinalities and distributions with zero plotting code.
This is *not* part of the text2SQL pipeline (no sklearn model): it's a data-understanding
aid.

```bash
python -m backend.eda_report                     # docs/eda/*.html for illustrative tables
python -m backend.eda_report --all               # every table
python -m backend.eda_report --tables patients factures
```

---

## 7. Run the tests

```bash
pytest -q -m "not slow"     # fast suite, no Ollama needed (runs in CI)
pytest -m slow              # integration: really calls the local models
pytest --cov=backend --cov=eval tests/
```
