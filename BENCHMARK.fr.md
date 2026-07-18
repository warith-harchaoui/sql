[🇫🇷](BENCHMARK.fr.md) · [🇬🇧](BENCHMARK.md)

# Benchmark — latence, vitesse et exactitude

> Étude numérique comparant les approches text2sql sur un **grand jeu de 500
> requêtes** de l'hôpital fictif. Point crucial : **les quatre configurations
> partagent le MÊME LLM** (`qwen2.5-coder`, en local via Ollama), la même base et
> le même garde-fou d'exécution — on compare donc les **approches** (la façon de
> donner le contexte au modèle), pas des modèles différents.
>
> Reproductible : `python -m eval.benchmark --repeats 1 && python -m eval.bench_charts`.

<!-- Chiffres et figures produits par le benchmark ; ne pas éditer à la main. -->

## Les quatre configurations comparées

| Config | LLM | Ce qui change |
|---|---|---|
| **QwenCoder (bon prompt)** | qwen2.5-coder | schéma + **valeurs énumérées** des colonnes + exemples + **auto-correction** sur erreur |
| **QwenCoder (prompt naïf)** | qwen2.5-coder | schéma **nu**, consigne minimale, **aucune** aide — le témoin « paresseux » |
| **LangChain** | qwen2.5-coder | la toolbox charge le schéma et prompte le LLM à sa façon |
| **Vanna (RAG)** | qwen2.5-coder | récupère le contexte pertinent (RAG) avant de générer |

Les deux configs QwenCoder ne diffèrent **que par le prompt** : leur écart mesure
directement **ce que vaut un bon prompt**.

## Méthodologie

**Jeu de 500 requêtes** — 46 questions écrites et vérifiées à la main (dont les
jointures et questions en langage naturel) + 454 cas générés par patrons sûrs sur
le schéma réel (comptages, regroupements, agrégats, filtres). Le SQL de référence
est correct par construction. Trois paliers : facile / moyen / difficile.

**Exactitude = exactitude d'exécution** : on exécute le SQL généré ET la référence
et on compare les **résultats** (métrique standard, cf. Spider/BIRD).

**Latence robuste au bruit** : `--repeats` générations par requête, on garde le
**minimum** (le bruit n'ajoute que du temps) ; on rapporte **médiane** et **p95**.
Sur le chemin QwenCoder, on lit en plus le **temps mesuré par Ollama**
(`total_duration`, `eval_duration`) et la vitesse **tokens/s** — le temps de calcul
*utile*, insensible aux autres activités de la machine.

> ⚠️ Mesuré sur un portable en usage normal : valeurs absolues *indicatives*,
> c'est l'**ordre relatif** et les **écarts** qui comptent (et ils survivent au bruit).

## Résultats — tableau récapitulatif

<!-- BENCH_TABLE -->
_(rempli après exécution)_
<!-- /BENCH_TABLE -->

## Un bon prompt, ça joue : bon prompt vs prompt naïf

<!-- BENCH_PROMPT -->
_(rempli après exécution — l'écart d'exactitude entre les deux configs QwenCoder)_
<!-- /BENCH_PROMPT -->

## Latence : distribution par approche

![Distribution de latence (violin)](docs/img/fr/bench-latency-violin.png)

## Qualité : exactitude par difficulté

![Exactitude par difficulté](docs/img/fr/bench-accuracy-difficulty.png)

## Le compromis : qualité vs vitesse

![Qualité vs vitesse](docs/img/fr/bench-quality-vs-speed.png)

## Temps de calcul « utile » vs horloge murale (QwenCoder)

<!-- BENCH_COMPUTE -->
_(rempli après exécution)_
<!-- /BENCH_COMPUTE -->

## Analyse des erreurs — pour faire mieux

On distingue deux types d'échec : **erreur d'exécution** (SQL invalide, la base
refuse) et **erreur sémantique** (SQL valide mais mauvais résultat — l'« erreur
silencieuse », la plus dangereuse).

<!-- BENCH_ERRORS -->
_(rempli après exécution — répartition exec/sémantique par approche + exemples)_
<!-- /BENCH_ERRORS -->

## Lecture & limites

<!-- BENCH_TAKEAWAYS -->
_(rempli après exécution)_
<!-- /BENCH_TAKEAWAYS -->

---

Reproduire : `python -m eval.benchmark --repeats 1` puis `python -m eval.bench_charts`.
Voir aussi [`ASSESSMENT.md`](ASSESSMENT.md) et [`PROS_CONS.md`](PROS_CONS.md).
