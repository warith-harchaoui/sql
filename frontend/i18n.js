/**
 * i18n.js — Chargeur d'internationalisation EN/FR (module ES).
 *
 * IMPORTANT : aucune chaîne traduite n'est codée en dur ici. La source de vérité
 * est ``locales/i18n.yaml`` ; le serveur l'expose en JSON via ``/api/i18n`` et ce
 * module la *récupère* au démarrage. On garde le patron d'API de l'i18n de
 * roitelet : ``t(key, vars)`` (substitution ``{name}``), ``setLang``,
 * ``applyStaticTranslations`` (réécrit les éléments ``data-i18n*``), plus un
 * ``initI18n()`` asynchrone à appeler une fois au chargement.
 */

const I18N_STORAGE_KEY = "text2sql.lang";

// Dictionnaire { lang: { clé: texte } }, rempli par initI18n() depuis /api/i18n.
let _strings = { en: {}, fr: {} };
// Langue courante (choix mémorisé, sinon langue du navigateur).
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
 * Récupère les chaînes depuis l'API (YAML → JSON), pose la langue et applique.
 *
 * @returns {Promise<void>}
 */
async function initI18n() {
  try {
    const resp = await fetch("/api/i18n");
    if (resp.ok) {
      const data = await resp.json();
      // On ne remplace que si la structure est saine.
      if (data && data.gui) _strings = data.gui;
    }
  } catch {
    /* API muette : t() renverra les clés brutes, l'UI reste utilisable. */
  }
  document.documentElement.setAttribute("lang", _currentLang);
  applyStaticTranslations();
}

/**
 * Traduit une clé dans la langue courante, avec substitution ``{name}``.
 *
 * @param {string} key - Clé pointée (ex. "run", "rows").
 * @param {object} [vars] - Variables à substituer (``{n}``, ``{msg}``…).
 * @returns {string} La chaîne traduite (ou la clé si absente).
 */
function t(key, vars) {
  const table = _strings[_currentLang] || _strings.en || {};
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
  // HTML riche (contient des <b>/<code> : on fait confiance à nos chaînes YAML).
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

export { initI18n, t, currentLang, setLang, applyStaticTranslations };
