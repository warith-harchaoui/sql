# Text-to-SQL (NL2SQL) en Python : comparatif pour ingénieurs data

> Document de cadrage pour l'équipe — « comment on fait du text2sql, et lequel
> choisir ». Il compare quatre approches, du plus « bas niveau » (prompting brut)
> au plus « framework RAG » (Vanna). **Toutes les affirmations chiffrées sont
> sourcées inline** ; quand un chiffre n'a pas été trouvé, c'est indiqué.
>
> La démo de ce dépôt implémente **trois** de ces approches (prompting brut,
> LangChain, Vanna) ; LlamaIndex est inclus ici pour le contexte comparatif.

Les quatre approches comparées :
1. **Prompting brut d'un LLM de code** (ex. Qwen2.5-Coder ou SQLCoder servis localement via Ollama, sans framework) — on écrit soi-même le prompt schéma + question.
2. **LangChain** (`create_sql_query_chain`, `SQLDatabase`, SQL agent).
3. **LlamaIndex** (`NLSQLTableQueryEngine`).
4. **Vanna AI** (RAG : DDL + docs + paires question/SQL vectorisés dans ChromaDB, few-shot récupéré à l'exécution).

---

## 1. Grand tableau comparatif

| Critère | 1. Prompting brut (Ollama + Qwen2.5-Coder / SQLCoder) | 2. LangChain (`create_sql_query_chain` / SQL agent) | 3. LlamaIndex (`NLSQLTableQueryEngine`) | 4. Vanna AI (RAG + ChromaDB) |
|---|---|---|---|---|
| **Principe : comment le schéma arrive au LLM** | Vous construisez le prompt à la main : `CREATE TABLE …` + question collés dans le contexte. Contrôle total, aucune abstraction. | La chaîne injecte le schéma via `SQLDatabase.get_table_info()` (colonnes + lignes d'exemple) ; l'**agent** récupère d'abord la liste des tables puis ne charge que les schémas pertinents via l'outil `sql_db_schema` [[LangChain SQL agent](https://docs.langchain.com/oss/python/langchain/sql-agent)]. | Le moteur synthétise le SQL à partir des schémas des tables passées à l'init. Si aucune table n'est spécifiée, il charge **tout** le schéma — risque de dépassement du contexte [[LlamaIndex NL SQL](https://developers.llamaindex.ai/python/framework-api-reference/query_engine/NL_SQL_table/)]. | **RAG** : on « entraîne » un index vectoriel (DDL + docs métier + paires question/SQL). À l'exécution, il récupère les **10 éléments les plus pertinents** et les met dans le prompt [[Vanna docs](https://ask.vanna.ai/docs/sqlite-ollama-chromadb/)]. Schéma ciblé, pas exhaustif. |
| **Précision / benchmarks** | Dépend du modèle. SQLCoder-15B : **64,6 %** sur l'éval Defog vs GPT-4 **74,3 %**, GPT-3.5-turbo **60,6 %** [[HF defog/sqlcoder](https://huggingface.co/defog/sqlcoder)]. Fine-tuné sur un schéma donné, SQLCoder « égale ou dépasse GPT-4 » [[Defog blog](https://defog.ai/blog/open-sourcing-sqlcoder)]. Qwen2.5-Coder-32B = SOTA open-source code [[Qwen report](https://arxiv.org/pdf/2409.12186)]. | Pas de score de benchmark propre au framework (LangChain est une plomberie, la précision vient du LLM sous-jacent). Non trouvé. | Idem : pas de score de benchmark propre au framework. Non trouvé. | Vanna revendique une meilleure précision grâce au RAG, mais **aucun score officiel Spider/BIRD publié par Vanna** n'a été trouvé. Principe RAG proche des pipelines qui atteignent 83-84 % sur Spider [[Promethium](https://promethium.ai/guides/text-to-sql-evaluation-benchmarks-metrics/)]. |
| **Passage à l'échelle (gros schémas)** | Limité par la fenêtre de contexte : au-delà de quelques dizaines de tables, il faut coder soi-même le filtrage/schema-linking. | L'**agent** filtre les tables pertinentes → tient mieux sur gros schémas que la chaîne simple [[LangChain SQL agent](https://docs.langchain.com/oss/python/langchain/sql-agent)]. | Le moteur de base **déborde** le contexte sur gros schéma ; il faut passer à `SQLTableRetrieverQueryEngine` (récupération de tables par index) [[LlamaIndex struct indices](https://developers.llamaindex.ai/python/examples/index_structs/struct_indices/sqlindexdemo/)]. | Conçu pour ça : la récupération vectorielle sélectionne un sous-ensemble pertinent, gardant le contexte dans un budget maîtrisé [[Vanna scaling](https://medium.com/@mkruts03/adapting-text-2-sql-for-large-scale-databases-c5fc62604bfa)]. Rappel : sur les schémas géants réels (Spider 2.0, >3000 colonnes), **toutes** les méthodes chutent (~6 % pour GPT-4) [[Promethium](https://promethium.ai/guides/text-to-sql-evaluation-benchmarks-metrics/)]. |
| **Facilité de mise en place** | Très rapide à démarrer (un prompt + un appel Ollama) mais tout le reste (schema-linking, retry, garde-fous) est à votre charge. | Moyenne : quelques lignes pour la chaîne ; l'agent demande plus de config. `create_sql_agent` renvoie un `AgentExecutor` **legacy**, non recommandé pour la prod [[create_sql_agent ref](https://reference.langchain.com/python/langchain-community/agent_toolkits/sql/base/create_sql_agent)]. | Simple pour un petit nombre de tables connues à l'avance [[LlamaIndex NL SQL](https://developers.llamaindex.ai/python/framework-api-reference/query_engine/NL_SQL_table/)]. | Deux étapes : `train()` puis `ask()`. Facile à démarrer, mais nécessite un travail d'« entraînement » (fournir DDL/docs/exemples) pour être bon [[Vanna scaling](https://medium.com/@mkruts03/adapting-text-2-sql-for-large-scale-databases-c5fc62604bfa)]. |
| **Dépendances / lock-in** | Quasi nul : juste le client Ollama + votre code. Zéro framework. | Écosystème LangChain (nombreuses dépendances) ; couplage au style chaînes/agents. | Écosystème LlamaIndex. | Package `vanna` + un vector store (ChromaDB par défaut) + un LLM. MIT, mais on adopte l'abstraction train/ask [[Vanna GitHub](https://github.com/asif-reh/vanna-ai)]. |
| **Sécurité (exécution du SQL généré)** | Vous décidez tout : par défaut rien n'est exécuté tant que vous ne le codez pas. À vous d'imposer read-only, allowlist, validation. | Docs explicites : exécuter du SQL généré comporte des risques ; outils « **not intended to be secure or used in production** ». Recommandations : permissions étroites, **read-only**, validation applicative, human-in-the-loop [[LangChain SQL agent](https://docs.langchain.com/oss/python/langchain/sql-agent)]. | Le moteur peut exécuter le SQL sur la base ; mêmes précautions read-only/permissions requises (à cadrer côté connexion). | **Historique de CVE** : CVE-2024-5565 (CVSS 8,1) — injection de prompt menant à du RCE via `exec` (intégration Plotly) [[JFrog](https://jfrog.com/blog/prompt-injection-attack-code-execution-in-vanna-ai-cve-2024-5565/)] ; CVE-2024-5826 associée [[Wiz](https://www.wiz.io/vulnerability-database/cve/cve-2024-5826)]. Corrigé depuis, mais impose vigilance/mise à jour. |
| **Local-first / confidentialité (100 % offline via Ollama ?)** | **Oui** : Qwen2.5-Coder et SQLCoder tournent en local via Ollama (0.5B → 32B) [[Ollama Qwen2.5-Coder](https://ollama.com/library/qwen2.5-coder)]. Aucune donnée ne sort. | Possible en branchant un LLM local (Ollama) au lieu d'OpenAI, mais orienté par défaut vers les API cloud. | Idem : possible avec LLM local, orienté API cloud par défaut. | **Oui, 100 % offline** documenté : LLM via Ollama + vecteurs via ChromaDB local, aucun appel externe [[Vanna docs](https://ask.vanna.ai/docs/sqlite-ollama-chromadb/)]. |
| **Coût** | Nul en API si local (coût = GPU/CPU + électricité). | Nul en framework (open-source) ; coût = tokens LLM si API cloud, sinon local. | Idem. | Package et ChromaDB gratuits/open-source ; coût = LLM (nul si Ollama local) [[Vanna docs](https://ask.vanna.ai/docs/sqlite-ollama-chromadb/)]. |
| **Maintenabilité / transparence / débogage** | Transparence maximale (vous voyez le prompt exact), mais **vous** maintenez toute la logique. | Abstractions pratiques mais couches d'agent qui compliquent le débogage ; API agent legacy à surveiller. | Abstraction moyenne ; débogage via inspection des prompts synthétisés. | Bonne transparence côté données (on voit ce qui a été « entraîné ») ; comportement dépend fortement de la qualité du corpus d'entraînement. |
| **Cas d'usage idéal + limites** | Idéal : local-first strict, contrôle fin, petit/moyen schéma, POC rapide. Limite : tout le tooling avancé à écrire soi-même. | Idéal : app qui a besoin de retry/multi-requêtes/agent. Limite : lourdeur, API agent legacy, sécurité à durcir. | Idéal : petit ensemble de tables connu, intégration dans un RAG LlamaIndex existant. Limite : débordement de contexte sur gros schéma sans retriever. | Idéal : gros schéma + besoin de few-shot métier réutilisable, 100 % local. Limite : dépend du corpus d'entraînement, historique de CVE, pas de score benchmark officiel. |

---

## 2. Avantages / Inconvénients / Quand l'utiliser

### Approche 1 — Prompting brut d'un LLM de code (Ollama + Qwen2.5-Coder / SQLCoder)

**Avantages**
- Contrôle total du prompt et de la logique ; transparence maximale pour le débogage.
- 100 % local et offline via Ollama (Qwen2.5-Coder de 0.5B à 32B) [[Ollama](https://ollama.com/library/qwen2.5-coder)].
- Aucun lock-in, dépendances minimales, coût d'API nul.
- Un modèle spécialisé fine-tuné sur *votre* schéma peut égaler/dépasser GPT-4 (cas SQLCoder) [[Defog](https://defog.ai/blog/open-sourcing-sqlcoder)].

**Inconvénients**
- Tout est à coder : schema-linking, few-shot, retry sur erreur, garde-fous read-only.
- SQLCoder-15B « générique » reste sous GPT-4 (64,6 % vs 74,3 %) [[HF](https://huggingface.co/defog/sqlcoder)].
- Passe mal à l'échelle sur gros schéma sans filtrage maison (limite de fenêtre de contexte).

**Quand l'utiliser** : POC rapide, contrainte de confidentialité forte, schéma petit/moyen, équipe qui veut maîtriser chaque étape. *(C'est l'approche « QwenCoder brut » de la démo.)*

### Approche 2 — LangChain (`create_sql_query_chain` / SQL agent)

**Avantages**
- L'agent gère nativement : sélection des tables pertinentes, validation, **retry sur erreur**, requêtes multiples [[LangChain](https://docs.langchain.com/oss/python/langchain/sql-agent)].
- Meilleur passage à l'échelle que la chaîne simple (ne charge que les schémas utiles).
- Prompt système impose déjà l'interdiction des DML (read-only) [[LangChain](https://docs.langchain.com/oss/python/langchain/sql-agent)].

**Inconvénients**
- Outils SQL « **not intended to be secure or used in production** » — sécurité à durcir soi-même [[LangChain](https://docs.langchain.com/oss/python/langchain/sql-agent)].
- `create_sql_agent` renvoie un `AgentExecutor` **legacy**, non recommandé pour de nouvelles apps prod [[ref](https://reference.langchain.com/python/langchain-community/agent_toolkits/sql/base/create_sql_agent)].
- Nombreuses dépendances ; débogage des couches d'agent plus difficile.

**Quand l'utiliser** : application ayant besoin de robustesse (retry, multi-requêtes) et déjà dans l'écosystème LangChain, avec durcissement sécurité et supervision humaine.

### Approche 3 — LlamaIndex (`NLSQLTableQueryEngine`)

**Avantages**
- Mise en place simple quand les tables cibles sont connues à l'avance [[LlamaIndex](https://developers.llamaindex.ai/python/framework-api-reference/query_engine/NL_SQL_table/)].
- S'intègre naturellement dans un pipeline RAG LlamaIndex existant.
- Chemin d'évolution clair vers un retriever de tables (`SQLTableRetrieverQueryEngine`) pour gros schéma.

**Inconvénients**
- Le moteur de base **déborde le contexte** si l'on ne spécifie pas les tables (il charge tout) [[LlamaIndex](https://developers.llamaindex.ai/python/examples/index_structs/struct_indices/sqlindexdemo/)].
- Pas de score de benchmark propre au framework (dépend du LLM).
- Précautions read-only/permissions à cadrer côté connexion.

**Quand l'utiliser** : petit ensemble de tables connu, ou brique text-to-SQL dans un projet LlamaIndex déjà en place ; passer au retriever dès que le schéma grossit.

### Approche 4 — Vanna AI (RAG + ChromaDB)

**Avantages**
- Approche RAG native : récupère les éléments les plus pertinents (DDL + docs + paires Q/SQL) → contexte ciblé, bon sur gros schéma [[Vanna](https://ask.vanna.ai/docs/sqlite-ollama-chromadb/)].
- **100 % offline** documenté (Ollama + ChromaDB local), MIT, coût nul en local [[Vanna](https://ask.vanna.ai/docs/sqlite-ollama-chromadb/)] [[GitHub](https://github.com/asif-reh/vanna-ai)].
- Le few-shot métier (paires question/SQL) est réutilisable et s'améliore avec l'usage.

**Inconvénients**
- **Historique de sécurité** : CVE-2024-5565 (CVSS 8,1, RCE via injection de prompt et `exec`) et CVE-2024-5826 — corrigées, mais imposent mise à jour et sandboxing [[JFrog](https://jfrog.com/blog/prompt-injection-attack-code-execution-in-vanna-ai-cve-2024-5565/)] [[Wiz](https://www.wiz.io/vulnerability-database/cve/cve-2024-5826)].
- Qualité fortement dépendante du corpus d'entraînement fourni.
- Aucun score officiel Spider/BIRD publié par Vanna (non trouvé).

**Quand l'utiliser** : gros schéma d'entreprise, besoin de capitaliser un few-shot métier, contrainte local-first — à condition de tenir le package à jour et d'isoler l'exécution.

> ⚠️ **Note de sécurité pour la démo** : à cause de l'historique de RCE de Vanna
> (et par bonne hygiène générale), **cette démo n'exécute jamais le SQL depuis
> les frameworks eux-mêmes**. Chaque approche se contente de *générer* la
> requête ; l'exécution passe par l'unique garde-fou lecture seule de
> `backend/db.py` (connexion SQLite `mode=ro`, un seul `SELECT`, mots-clés
> d'écriture refusés, `LIMIT` défensif). Voir aussi la génération de figures :
> on ne rend jamais de code produit par un LLM, seulement une spec Vega-Lite.

---

## 3. Chiffres de benchmark (avec sources)

**SQLCoder vs modèles OpenAI (éval Defog, jeux non vus à l'entraînement)** [[HF defog/sqlcoder](https://huggingface.co/defog/sqlcoder)] :
- GPT-4 : **74,3 %**
- SQLCoder-15B : **64,6 %**
- GPT-3.5-turbo : **60,6 %**
- text-davinci-003 : **54,3 %**
- Note : fine-tuné sur un schéma spécifique, SQLCoder « égale ou dépasse GPT-4 » [[Defog blog](https://defog.ai/blog/open-sourcing-sqlcoder)].

**Spider (execution accuracy)** [[Promethium](https://promethium.ai/guides/text-to-sql-evaluation-benchmarks-metrics/)] :
- GPT-4 baseline (schéma complet) : **70 %**
- Systèmes spécialisés (DIN-SQL, DAIL-SQL) : **85-86 %**
- GPT-4 fine-tuné + RAG : **83-84 %**

**BIRD (bases d'entreprise, données « sales »)** [[Promethium](https://promethium.ai/guides/text-to-sql-evaluation-benchmarks-metrics/)] :
- GPT-4 : **52 %** vs experts humains **93 %**
- SOTA récent open : Arctic-Text2SQL-R1-32B **71,83 %** [[Snowflake](https://www.snowflake.com/en/blog/engineering/arctic-text2sql-r1-sql-generation-benchmark/)]

**Spider 2.0 (schémas réels, >3000 colonnes)** [[Promethium](https://promethium.ai/guides/text-to-sql-evaluation-benchmarks-metrics/)] :
- Spider 2.0-Snow : pic **59 %** ; Spider 2.0-Lite : pic **38 %** ; taux de succès global GPT-4 : **~6 %**.

**Fiabilité des benchmarks** : un travail 2025 (métrique FLEX) montre que l'execution accuracy de BIRD ne coïncide avec le jugement d'experts que ~62 % du temps [[Promethium](https://promethium.ai/guides/text-to-sql-evaluation-benchmarks-metrics/)]. À lire avec prudence.

**Chiffres non trouvés** : aucun score Spider/BIRD officiel publié spécifiquement pour Vanna AI, LangChain ou LlamaIndex (frameworks → précision dépend du LLM branché). Pas de score text-to-SQL Spider/BIRD isolé pour Qwen2.5-Coder-32B [[Qwen report](https://arxiv.org/pdf/2409.12186)].

---

## 4. Sources

- [Defog — Open-sourcing SQLCoder](https://defog.ai/blog/open-sourcing-sqlcoder)
- [Hugging Face — defog/sqlcoder](https://huggingface.co/defog/sqlcoder)
- [LangChain — Build a SQL agent](https://docs.langchain.com/oss/python/langchain/sql-agent)
- [LangChain Reference — create_sql_agent](https://reference.langchain.com/python/langchain-community/agent_toolkits/sql/base/create_sql_agent)
- [LangChain API — create_sql_query_chain](https://api.python.langchain.com/en/latest/chains/langchain.chains.sql_database.query.create_sql_query_chain.html)
- [LlamaIndex — NL SQL Table Query Engine (API)](https://developers.llamaindex.ai/python/framework-api-reference/query_engine/NL_SQL_table/)
- [LlamaIndex — Text-to-SQL Guide (Query Engine + Retriever)](https://developers.llamaindex.ai/python/examples/index_structs/struct_indices/sqlindexdemo/)
- [Vanna.AI — SQLite + Ollama + ChromaDB (local)](https://ask.vanna.ai/docs/sqlite-ollama-chromadb/)
- [Vanna AI — dépôt (RAG text-to-SQL, MIT)](https://github.com/asif-reh/vanna-ai)
- [Adapting Text-2-SQL for Large-Scale Databases (Medium)](https://medium.com/@mkruts03/adapting-text-2-sql-for-large-scale-databases-c5fc62604bfa)
- [JFrog — CVE-2024-5565, injection de prompt / RCE dans Vanna.AI](https://jfrog.com/blog/prompt-injection-attack-code-execution-in-vanna-ai-cve-2024-5565/)
- [Wiz — CVE-2024-5826 (Vanna RCE)](https://www.wiz.io/vulnerability-database/cve/cve-2024-5826)
- [Promethium — Text-to-SQL benchmarks & metrics (Spider, BIRD, Spider 2.0)](https://promethium.ai/guides/text-to-sql-evaluation-benchmarks-metrics/)
- [Snowflake — Arctic-Text2SQL-R1 tops BIRD](https://www.snowflake.com/en/blog/engineering/arctic-text2sql-r1-sql-generation-benchmark/)
- [Ollama — bibliothèque qwen2.5-coder](https://ollama.com/library/qwen2.5-coder)
- [Qwen2.5-Coder Technical Report (arXiv)](https://arxiv.org/pdf/2409.12186)
