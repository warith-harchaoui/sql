/**
 * app.js — Logique du front Text2SQL (module ES, vanilla JS).
 *
 * Rôle : parler à l'API FastAPI (/api/*), afficher côte à côte le SQL généré
 * par chaque approche, exécuter la requête et présenter le résultat, puis — à
 * la demande — rendre une figure Vega-Lite choisie par Gemma.
 *
 * Aucune dépendance de build : on charge Tailwind + Vega par <script>. Le style
 * suit le house style front-ui (dark mode par classe, focus rings, motion-reduce).
 */

// État applicatif minimal : l'approche sélectionnée. « qwen » par défaut car
// c'est la plus pédagogique (aucune magie de framework).
const state = {
  approach: "qwen",
  // Derniers résultats reçus, gardés en mémoire JS (PAS dans le DOM) : cela
  // évite tout problème d'échappement quand une valeur contient une apostrophe
  // (ex. « Col de l'utérus »), qui casserait un attribut data-* de la carte.
  lastResults: [],
  lastQuestion: "",
};

/**
 * Raccourci de sélection d'un élément du DOM.
 *
 * @param {string} sel - Sélecteur CSS.
 * @returns {Element|null} Le premier élément correspondant.
 */
const $ = (sel) => document.querySelector(sel);

/**
 * Échappe une chaîne pour l'insérer sans risque dans du HTML.
 *
 * Empêche l'injection de balises quand on affiche du SQL, des messages
 * d'erreur ou des valeurs de cellules provenant de la base.
 *
 * @param {unknown} value - Valeur brute à afficher.
 * @returns {string} La chaîne échappée (`&`, `<`, `>` neutralisés).
 */
function escapeHtml(value) {
  // On passe par un nœud texte : le navigateur fait l'échappement pour nous.
  const div = document.createElement("div");
  div.textContent = value === null || value === undefined ? "" : String(value);
  return div.innerHTML;
}

/**
 * Appelle une route JSON de l'API et renvoie l'objet parsé.
 *
 * @param {string} url - Chemin de l'API (ex. "/api/health").
 * @param {object|null} body - Corps POST (JSON) ou null pour un GET.
 * @returns {Promise<object>} La réponse JSON.
 * @throws {Error} Si la réponse HTTP n'est pas OK.
 */
async function api(url, body = null) {
  // GET si pas de corps, POST JSON sinon.
  const options = body
    ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }
    : {};
  const resp = await fetch(url, options);
  if (!resp.ok) {
    // On remonte une erreur lisible plutôt qu'un JSON à moitié parsé.
    throw new Error(`HTTP ${resp.status} sur ${url}`);
  }
  return resp.json();
}

// ---------------------------------------------------------------------------
// Thème clair/sombre
// ---------------------------------------------------------------------------

/**
 * Applique le thème (clair/sombre) et le mémorise dans localStorage.
 *
 * @param {boolean} dark - Vrai pour activer le mode sombre.
 * @returns {void}
 */
function applyTheme(dark) {
  // Tailwind est configuré en darkMode:"class" → on bascule la classe racine.
  document.documentElement.classList.toggle("dark", dark);
  localStorage.setItem("theme", dark ? "dark" : "light");
}

// ---------------------------------------------------------------------------
// Santé + schéma + exemples (au chargement)
// ---------------------------------------------------------------------------

/**
 * Charge l'état de santé et affiche les badges (Ollama, approches).
 *
 * @returns {Promise<void>}
 */
async function loadHealth() {
  const box = $("#health-badges");
  try {
    const h = await api("/api/health");
    // Petite fabrique de badge coloré selon un booléen (dispo/indispo).
    const badge = (label, ok) =>
      `<span class="rounded-full px-2 py-1 ${
        ok
          ? "bg-green-100 text-green-800 dark:bg-green-900/40 dark:text-green-300"
          : "bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300"
      }">${label}</span>`;

    // Un badge pour Ollama, puis un par approche disponible.
    const parts = [badge(h.ollama_up ? "Ollama ✓" : "Ollama ✗", h.ollama_up)];
    for (const [key, ok] of Object.entries(h.approaches || {})) {
      parts.push(badge(key, ok));
    }
    box.innerHTML = parts.join("");
    box.classList.remove("hidden");
  } catch (e) {
    // En cas d'API muette, on affiche un badge d'erreur discret.
    box.innerHTML = `<span class="text-red-500">API injoignable</span>`;
    box.classList.remove("hidden");
  }
}

/**
 * Charge et affiche le schéma (nombre de tables + DDL) dans la barre latérale.
 *
 * @returns {Promise<void>}
 */
async function loadSchema() {
  try {
    const s = await api("/api/schema");
    $("#table-count").textContent = s.tables.length;
    $("#schema-ddl").textContent = s.ddl;
  } catch (e) {
    $("#schema-ddl").textContent = "Schéma indisponible.";
  }
}

/**
 * Charge les questions d'exemple et les rend comme « chips » cliquables.
 *
 * @returns {Promise<void>}
 */
async function loadSamples() {
  const box = $("#samples");
  try {
    const data = await api("/api/samples");
    // Chaque exemple devient un bouton : au clic, il remplit le champ question.
    box.innerHTML = data.samples
      .map(
        (s, i) =>
          `<button data-q="${i}" class="sample-chip text-xs rounded-full border border-gray-300 dark:border-gray-700 px-3 py-1 hover:bg-brand hover:text-white focus:outline-none focus:ring-2 focus:ring-brand" title="${escapeHtml(s.domaine)}">${escapeHtml(s.q)}</button>`
      )
      .join("");
    // On garde les libellés en mémoire pour les réinjecter au clic.
    box._samples = data.samples;
  } catch (e) {
    box.innerHTML = `<span class="text-red-500 text-xs">Exemples indisponibles.</span>`;
  }
}

// ---------------------------------------------------------------------------
// Rendu d'un résultat d'approche
// ---------------------------------------------------------------------------

/**
 * Construit le HTML d'un tableau de résultats (colonnes + lignes).
 *
 * @param {string[]} columns - Noms des colonnes.
 * @param {Array<Array>} rows - Lignes de valeurs.
 * @returns {string} Le fragment HTML du tableau (borné à 100 lignes affichées).
 */
function renderTable(columns, rows) {
  if (!columns || columns.length === 0) return "<p class='text-xs text-gray-500'>Aucune colonne.</p>";
  // En-tête : scope="col" pour que les lecteurs d'écran associent chaque cellule
  // à sa colonne.
  const head = columns.map((c) => `<th scope="col" class="px-2 py-1 text-left font-medium">${escapeHtml(c)}</th>`).join("");
  // On n'affiche que les 100 premières lignes pour garder le DOM léger.
  const shown = rows.slice(0, 100);
  const body = shown
    .map(
      (r) =>
        `<tr class="border-t border-gray-100 dark:border-gray-800">${r
          .map((v) => `<td class="px-2 py-1 font-mono">${escapeHtml(v)}</td>`)
          .join("")}</tr>`
    )
    .join("");
  // Note si le tableau est tronqué à l'affichage.
  const more = rows.length > 100 ? `<p class="text-[11px] text-gray-500 mt-1">… ${rows.length - 100} lignes supplémentaires non affichées.</p>` : "";
  // <caption> en sr-only : décrit le tableau pour les lecteurs d'écran sans
  // encombrer l'affichage visuel.
  const caption = `<caption class="sr-only">Résultats de la requête : ${rows.length} ligne(s), colonnes ${escapeHtml(columns.join(", "))}.</caption>`;
  return `<div class="overflow-auto max-h-80 rounded-lg border border-gray-200 dark:border-gray-800">
      <table class="w-full text-xs">${caption}<thead class="bg-gray-50 dark:bg-gray-800 sticky top-0"><tr>${head}</tr></thead><tbody>${body}</tbody></table>
    </div>${more}`;
}

/**
 * Construit le bloc HTML d'un résultat d'approche (SQL, note, table, actions).
 *
 * @param {object} block - Un élément du tableau `results` renvoyé par /api/query.
 * @param {string} question - La question d'origine (pour la figure).
 * @param {number} index - Index du bloc (pour identifiants uniques).
 * @returns {string} Le HTML de la carte.
 */
function renderBlock(block, question, index) {
  // Cas 1 : approche indisponible (dépendance/serveur manquant).
  if (!block.available) {
    return `<div class="rounded-2xl border border-amber-300 dark:border-amber-800 bg-amber-50 dark:bg-amber-900/20 p-4">
        <h3 class="font-bold text-sm">${escapeHtml(block.approach_key)} — indisponible</h3>
        <p class="text-xs mt-1 text-amber-800 dark:text-amber-300">${escapeHtml(block.error)}</p>
      </div>`;
  }

  // En-tête : nom de l'approche + modèle + latence.
  const header = `<div class="flex items-center gap-2 flex-wrap">
      <h3 class="font-bold text-sm">${escapeHtml(block.approach)}</h3>
      ${block.model ? `<span class="text-[11px] rounded bg-gray-100 dark:bg-gray-800 px-2 py-0.5 font-mono">${escapeHtml(block.model)}</span>` : ""}
      <span class="text-[11px] rounded bg-blue-100 text-blue-800 dark:bg-blue-900/40 dark:text-blue-200 px-2 py-0.5">${block.latency_s}s</span>
    </div>`;

  // Cas 2 : la génération du SQL a échoué.
  if (!block.gen_ok) {
    return `<div class="rounded-2xl border border-red-300 dark:border-red-800 bg-red-50 dark:bg-red-900/20 p-4 space-y-2">
        ${header}
        <p class="text-xs text-red-700 dark:text-red-300">Échec de génération : ${escapeHtml(block.gen_error)}</p>
      </div>`;
  }

  // SQL généré (toujours affiché : c'est le cœur pédagogique).
  const sqlBlock = `<pre class="sql-code rounded-lg bg-gray-900 text-gray-100 dark:bg-black p-3 text-xs font-mono overflow-auto">${escapeHtml(block.sql)}</pre>`;

  // Sortie BRUTE du modèle, dépliable : transparence totale (on voit l'éventuel
  // bavardage que le nettoyage a retiré). Affichée seulement si elle diffère du SQL.
  let rawBlock = "";
  if (block.raw && block.raw.trim() !== block.sql.trim()) {
    rawBlock = `<details class="text-xs">
        <summary class="cursor-pointer text-gray-500 dark:text-gray-400">Sortie brute du modèle</summary>
        <pre class="sql-code mt-1 rounded-lg bg-gray-100 dark:bg-gray-800 p-2 font-mono overflow-auto">${escapeHtml(block.raw)}</pre>
      </details>`;
  }

  // Résultat d'exécution : tableau, erreur SQL, ou rien.
  let resultBlock = "";
  let figureButton = "";
  if (block.exec_ok === false) {
    resultBlock = `<p class="text-xs text-red-600 dark:text-red-400">Erreur d'exécution : ${escapeHtml(block.exec_error)}</p>`;
  } else if (block.columns) {
    const trunc = block.truncated ? " (tronqué)" : "";
    resultBlock = `<p class="text-xs text-gray-500 mb-1">${block.row_count} ligne(s)${trunc}</p>` + renderTable(block.columns, block.rows);
    // Bouton figure seulement s'il y a des données à tracer. L'index permet de
    // retrouver les données côté JS (state.lastResults), sans les stocker en DOM.
    if (block.row_count > 0) {
      figureButton = `<button class="figure-btn mt-2 text-xs rounded-lg border border-gray-300 dark:border-gray-700 px-3 py-1.5 hover:bg-brand hover:text-white focus:outline-none focus:ring-2 focus:ring-brand"
          data-index="${index}">📊 Générer une figure (Gemma)</button>`;
    }
  }

  // Carte complète. Aucune donnée n'est stockée dans le DOM : le bouton figure
  // porte juste son index et relit les données depuis state.lastResults.
  return `<div class="rounded-2xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-4 shadow-sm space-y-3">
      ${header}
      <p class="text-[11px] text-gray-500 dark:text-gray-400 italic">${escapeHtml(block.notes)}</p>
      ${sqlBlock}
      ${rawBlock}
      ${resultBlock}
      ${figureButton}
      <div class="figure-target"></div>
    </div>`;
}

// ---------------------------------------------------------------------------
// Actions principales
// ---------------------------------------------------------------------------

/**
 * Lance la traduction question → SQL puis l'exécution, et affiche les résultats.
 *
 * @returns {Promise<void>}
 */
async function runQuery() {
  const question = $("#question").value.trim();
  // Rien à faire sans question.
  if (!question) {
    $("#question").focus();
    return;
  }

  // État « chargement » : bouton désactivé + spinner + annonce lecteur d'écran.
  const btn = $("#run-btn");
  btn.disabled = true;
  btn.setAttribute("aria-busy", "true");
  $("#run-spinner").classList.remove("hidden");
  // aria-busy sur la zone de résultats : le lecteur d'écran sait qu'elle se met à jour.
  const results = $("#results");
  results.setAttribute("aria-busy", "true");
  results.innerHTML = `<p class="text-sm text-gray-500" role="status">Génération en cours (les modèles locaux peuvent prendre quelques secondes)…</p>`;

  try {
    // Appel API : l'approche « toutes » lance les trois pour la comparaison.
    const data = await api("/api/query", {
      question,
      approach: state.approach,
      execute: true,
    });
    // On mémorise les résultats en JS pour la génération de figure ultérieure.
    state.lastResults = data.results;
    state.lastQuestion = question;
    // Rendu de chaque bloc résultat.
    $("#results").innerHTML = data.results
      .map((b, i) => renderBlock(b, question, i))
      .join("");
  } catch (e) {
    $("#results").innerHTML = `<p class="text-sm text-red-600">Erreur : ${escapeHtml(e.message)}</p>`;
  } finally {
    // On restaure toujours le bouton, succès ou échec.
    btn.disabled = false;
    btn.removeAttribute("aria-busy");
    $("#run-spinner").classList.add("hidden");
    // Fin de mise à jour : on lève le drapeau aria-busy de la zone résultats.
    $("#results").setAttribute("aria-busy", "false");
  }
}

/**
 * Demande une figure à Gemma pour un bloc de résultat et la rend en Vega-Lite.
 *
 * @param {HTMLElement} button - Le bouton « figure » cliqué (porte data-index).
 * @returns {Promise<void>}
 */
async function makeFigure(button) {
  // La cible de rendu est la div .figure-target de la même carte.
  const card = button.closest("div");
  const target = card.querySelector(".figure-target");
  // Message d'attente : Gemma réfléchit au type de figure.
  target.innerHTML = `<p class="text-xs text-gray-500 mt-2">Gemma choisit une visualisation…</p>`;

  // On relit les données depuis l'état JS via l'index du bloc (pas depuis le DOM).
  const block = state.lastResults[Number(button.dataset.index)] || {};
  const columns = block.columns || [];
  const rows = block.rows || [];
  const question = state.lastQuestion;

  try {
    const fig = await api("/api/figure", { question, columns, rows });
    // Gemma peut juger qu'aucune figure n'a de sens : on l'explique.
    if (!fig.ok) {
      target.innerHTML = `<p class="text-xs text-gray-500 mt-2">Pas de figure : ${escapeHtml(fig.error || "non pertinent")}.</p>`;
      return;
    }
    // On emballe le graphique dans <figure role="img"> avec un aria-label
    // descriptif et un <figcaption> visible : c'est le house style front-figures
    // (une figure doit être annoncée aux lecteurs d'écran, pas juste un SVG muet).
    const title = (fig.spec && fig.spec.title) || "Figure";
    const rationale = (fig.spec && fig.spec.rationale) || "";
    // aria-label = titre + justification : ce qu'un lecteur d'écran énonce.
    const label = escapeHtml(rationale ? `${title}. ${rationale}` : title);
    target.innerHTML = `<figure role="img" aria-label="${label}" class="mt-2">
        <div class="vega-holder"></div>
        ${rationale ? `<figcaption class="text-[11px] text-gray-500 dark:text-gray-400 mt-1 italic">${escapeHtml(rationale)}</figcaption>` : ""}
      </figure>`;
    // vega-embed prend la spec renvoyée par le back et rend le graphe. On masque
    // le SVG interne aux lecteurs d'écran (aria-hidden) : c'est la <figure> qui
    // porte la description, pas le SVG brut (sinon double lecture).
    await vegaEmbed(target.querySelector(".vega-holder"), fig.vega_spec, {
      actions: false, // pas de menu « export » : on garde l'UI épurée
      renderer: "svg",
      ariaHidden: true,
    });
  } catch (e) {
    target.innerHTML = `<p class="text-xs text-red-600 mt-2">Erreur figure : ${escapeHtml(e.message)}</p>`;
  }
}

// ---------------------------------------------------------------------------
// Câblage des événements
// ---------------------------------------------------------------------------

/**
 * Met en surbrillance le bouton d'approche actif.
 *
 * @returns {void}
 */
function refreshApproachButtons() {
  document.querySelectorAll(".approach-btn").forEach((b) => {
    // La classe « active » colore le bouton correspondant à l'état courant.
    const active = b.dataset.approach === state.approach;
    b.classList.toggle("bg-brand", active);
    b.classList.toggle("text-white", active);
    // aria-pressed reflète l'état pour les lecteurs d'écran (toggle button).
    b.setAttribute("aria-pressed", active ? "true" : "false");
  });
}

/**
 * Installe tous les écouteurs d'événements de la page.
 *
 * @returns {void}
 */
function wireEvents() {
  // Sélection d'approche.
  document.querySelectorAll(".approach-btn").forEach((b) => {
    b.addEventListener("click", () => {
      state.approach = b.dataset.approach;
      refreshApproachButtons();
    });
  });

  // Bouton Exécuter + raccourci Ctrl/Cmd+Entrée dans le textarea.
  $("#run-btn").addEventListener("click", runQuery);
  $("#question").addEventListener("keydown", (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key === "Enter") runQuery();
  });

  // Clic sur une chip d'exemple → remplit le champ question.
  $("#samples").addEventListener("click", (e) => {
    const chip = e.target.closest(".sample-chip");
    if (!chip) return;
    const samples = $("#samples")._samples || [];
    $("#question").value = samples[chip.dataset.q].q;
    $("#question").focus();
  });

  // Délégation : clic sur un bouton « figure » dans n'importe quelle carte.
  $("#results").addEventListener("click", (e) => {
    const fbtn = e.target.closest(".figure-btn");
    if (!fbtn) return;
    // Le bouton porte son index : makeFigure retrouve les données côté JS.
    makeFigure(fbtn);
  });

  // Bascule de thème.
  $("#theme-toggle").addEventListener("click", () => {
    applyTheme(!document.documentElement.classList.contains("dark"));
  });
}

// ---------------------------------------------------------------------------
// Démarrage
// ---------------------------------------------------------------------------

/**
 * Point d'entrée : applique le thème mémorisé, câble les événements, charge les
 * données initiales (santé, schéma, exemples).
 *
 * @returns {void}
 */
function main() {
  // Thème : préférence mémorisée, sinon préférence système.
  const saved = localStorage.getItem("theme");
  const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
  applyTheme(saved ? saved === "dark" : prefersDark);

  wireEvents();
  refreshApproachButtons();

  // Chargements initiaux en parallèle (indépendants les uns des autres).
  loadHealth();
  loadSchema();
  loadSamples();
}

// On attend le DOM prêt avant de toucher aux éléments.
document.addEventListener("DOMContentLoaded", main);
