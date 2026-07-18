/**
 * i18n.js — Internationalisation EN/FR du front (module ES).
 *
 * Même patron que l'i18n de `roitelet` : un dictionnaire ``TRANSLATIONS`` à clés
 * en notation pointée, un helper ``t(key, vars)`` avec substitution ``{name}``,
 * et ``applyStaticTranslations()`` qui réécrit tout élément annoté
 * ``data-i18n`` / ``data-i18n-placeholder`` / ``data-i18n-aria-label`` /
 * ``data-i18n-html``. La langue est mémorisée dans localStorage et posée sur
 * ``<html lang>`` (utile pour l'accessibilité et les lecteurs d'écran).
 *
 * Principes de traduction : on traduit le SENS, pas mot à mot ; verbes à
 * l'impératif pour les boutons ; messages d'erreur orientés « quoi faire ».
 * Les *données* (questions d'exemple, schéma, résultats) restent en français :
 * c'est la base d'un hôpital français — seule l'ossature de l'UI est bilingue.
 */

const I18N_STORAGE_KEY = "text2sql.lang";

// Dictionnaire des chaînes visibles. `en` d'abord (référence), puis `fr`.
const TRANSLATIONS = {
  en: {
    "app.subtitle": "Natural language → SQL, three approaches, 100% local (Ollama)",
    "theme.toggle": "Toggle light/dark theme",
    "lang.toggle": "Français",
    "question.label": "Ask your question (in French)",
    "question.placeholder": "e.g. Revenue collected per month in 2026",
    "approach.group": "Approach selector",
    "approach.all": "All",
    "run": "Run",
    "examples.heading": "Click an example",
    "how.heading": "How it works?",
    "how.qwen": "<b>QwenCoder (raw)</b> — we paste the schema + the question into a hand-written prompt and call <code>qwen2.5-coder</code>. No framework: everything is visible.",
    "how.langchain": "<b>LangChain</b> — <code>create_sql_query_chain</code> introspects the DB and prompts the LLM for you. Concise, but more of a black box.",
    "how.vanna": "<b>Vanna (RAG)</b> — you \"train\" an index (schema + business knowledge + examples); at query time only the relevant context is retrieved. Ideal for large schemas.",
    "how.figures": "<b>Figures</b> — <code>gemma4</code> picks the visualization; we render it as Vega-Lite. LLM-generated code is never executed.",
    "how.security": "Read-only SQL execution (single SELECT, DB opened <code>mode=ro</code>). See <code>PROS_CONS.md</code>.",
    "schema.summary": "Database schema ({n} tables)",
    "footer": "Teaching demo — 100% fake data. No data leaves the machine.",
    "loading": "Generating (local models may take a few seconds)…",
    "gen.choosing": "Gemma is choosing a visualization…",
    "figure.button": "📊 Generate a figure (Gemma)",
    "figure.none": "No figure: {reason}.",
    "figure.error": "Figure error: {msg}",
    "figure.norelevant": "not relevant",
    "rawoutput": "Raw model output",
    "rows": "{n} row(s)",
    "truncated": " (truncated)",
    "rows.more": "… {n} more rows not shown.",
    "nocolumn": "No column.",
    "unavailable": "unavailable",
    "genfailed": "Generation failed: {err}",
    "execerror": "Execution error: {err}",
    "error": "Error: {msg}",
    "api.down": "API unreachable",
    "table.caption": "Query results: {n} row(s), columns {cols}.",
  },
  fr: {
    "app.subtitle": "Langage naturel → SQL, trois approches, 100 % local (Ollama)",
    "theme.toggle": "Basculer le thème clair/sombre",
    "lang.toggle": "English",
    "question.label": "Pose ta question en français",
    "question.placeholder": "Ex. : Chiffre d'affaires encaissé par mois en 2026",
    "approach.group": "Choix de l'approche",
    "approach.all": "Toutes",
    "run": "Exécuter",
    "examples.heading": "Exemples à cliquer",
    "how.heading": "Comment ça marche&nbsp;?",
    "how.qwen": "<b>QwenCoder (brut)</b> — on colle le schéma + la question dans un prompt maison et on appelle <code>qwen2.5-coder</code>. Zéro framework : tout est visible.",
    "how.langchain": "<b>LangChain</b> — <code>create_sql_query_chain</code> introspecte la base et prompte le LLM pour toi. Concis, mais plus « boîte noire ».",
    "how.vanna": "<b>Vanna (RAG)</b> — on « entraîne » un index (schéma + savoir métier + exemples) ; à l'exécution, seul le contexte pertinent est récupéré. Idéal gros schéma.",
    "how.figures": "<b>Figures</b> — <code>gemma4</code> choisit la visualisation ; on la rend en Vega-Lite. On n'exécute jamais de code produit par un LLM.",
    "how.security": "Exécution SQL en lecture seule stricte (SELECT unique, base ouverte en <code>mode=ro</code>). Voir <code>PROS_CONS.md</code>.",
    "schema.summary": "Schéma de la base ({n} tables)",
    "footer": "Démo pédagogique — données 100 % fictives. Aucune donnée ne quitte la machine.",
    "loading": "Génération en cours (les modèles locaux peuvent prendre quelques secondes)…",
    "gen.choosing": "Gemma choisit une visualisation…",
    "figure.button": "📊 Générer une figure (Gemma)",
    "figure.none": "Pas de figure : {reason}.",
    "figure.error": "Erreur figure : {msg}",
    "figure.norelevant": "non pertinent",
    "rawoutput": "Sortie brute du modèle",
    "rows": "{n} ligne(s)",
    "truncated": " (tronqué)",
    "rows.more": "… {n} lignes supplémentaires non affichées.",
    "nocolumn": "Aucune colonne.",
    "unavailable": "indisponible",
    "genfailed": "Échec de génération : {err}",
    "execerror": "Erreur d'exécution : {err}",
    "error": "Erreur : {msg}",
    "api.down": "API injoignable",
    "table.caption": "Résultats de la requête : {n} ligne(s), colonnes {cols}.",
  },
};

// Langue courante (mutée par setLang).
let _currentLang = _initialLang();

/**
 * Détermine la langue initiale : choix mémorisé, sinon langue du navigateur.
 *
 * @returns {string} "fr" ou "en".
 */
function _initialLang() {
  try {
    const saved = localStorage.getItem(I18N_STORAGE_KEY);
    if (saved === "fr" || saved === "en") return saved;
  } catch {
    /* localStorage indisponible : on retombe sur la détection navigateur. */
  }
  // Navigateur en français → fr ; tout le reste → en (public international).
  const nav = (navigator.language || "en").toLowerCase();
  return nav.startsWith("fr") ? "fr" : "en";
}

/**
 * Traduit une clé dans la langue courante, avec substitution ``{name}``.
 *
 * @param {string} key - Clé pointée (ex. "run", "rows").
 * @param {object} [vars] - Variables à substituer (``{n}``, ``{msg}``…).
 * @returns {string} La chaîne traduite (ou la clé si absente).
 */
function t(key, vars) {
  const table = TRANSLATIONS[_currentLang] || TRANSLATIONS.en;
  let s = table[key] != null ? table[key] : key;
  // Substitution simple des placeholders {nom} par leur valeur.
  if (vars) {
    for (const [k, v] of Object.entries(vars)) {
      s = s.replaceAll(`{${k}}`, String(v));
    }
  }
  return s;
}

/**
 * Renvoie la langue courante ("fr" / "en").
 *
 * @returns {string} La langue active.
 */
function currentLang() {
  return _currentLang;
}

/**
 * Change la langue, la mémorise, met à jour ``<html lang>`` et réapplique.
 *
 * @param {string} lang - "fr" ou "en".
 * @returns {void}
 */
function setLang(lang) {
  _currentLang = lang === "fr" ? "fr" : "en";
  try {
    localStorage.setItem(I18N_STORAGE_KEY, _currentLang);
  } catch {
    /* localStorage indisponible : la langue vaut au moins pour cette session. */
  }
  document.documentElement.setAttribute("lang", _currentLang);
  applyStaticTranslations();
}

/**
 * Réécrit tous les éléments annotés ``data-i18n*`` selon la langue courante.
 *
 * @returns {void}
 */
function applyStaticTranslations() {
  // Texte simple.
  for (const el of document.querySelectorAll("[data-i18n]")) {
    el.textContent = t(el.getAttribute("data-i18n"));
  }
  // HTML riche (contient des <b>/<code> : on fait confiance à nos chaînes).
  for (const el of document.querySelectorAll("[data-i18n-html]")) {
    el.innerHTML = t(el.getAttribute("data-i18n-html"));
  }
  // Attribut placeholder.
  for (const el of document.querySelectorAll("[data-i18n-placeholder]")) {
    el.setAttribute("placeholder", t(el.getAttribute("data-i18n-placeholder")));
  }
  // Attribut aria-label (accessibilité).
  for (const el of document.querySelectorAll("[data-i18n-aria-label]")) {
    el.setAttribute("aria-label", t(el.getAttribute("data-i18n-aria-label")));
  }
}

export { t, currentLang, setLang, applyStaticTranslations };
