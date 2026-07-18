[🇫🇷](MODEDEMPLOI.md) · [🇬🇧](USERGUIDE.md)

# Mode d'emploi — Text2SQL Institut de Cancérologie

Guide pas-à-pas illustré de l'interface web. Pour l'installation, voir
[LISEZMOI.md](LISEZMOI.md) ; pour les recettes en ligne de commande,
[EXAMPLES.md](EXAMPLES.md).

> Prérequis : `ollama serve` tourne, les modèles sont tirés, et vous avez lancé
> `./start.sh` puis ouvert <http://localhost:8000>.

---

## 1. L'écran d'accueil

![Accueil](docs/screenshots/01-accueil-clair.png)

- **En haut à droite** : des **badges d'état**. `Ollama ✓` confirme que le
  serveur de modèles répond ; un badge par approche (`qwen`, `langchain`,
  `vanna`) indique si elle est disponible (vert) ou non (rouge). Le bouton 🌓
  bascule le thème clair/sombre.
- **Zone de saisie** : tapez votre question **en français**.
- **Sélecteur d'approche** : `QwenCoder`, `LangChain`, `Vanna`, ou **`Toutes`**
  (pour comparer les trois d'un coup).
- **Exemples à cliquer** : des questions prêtes à l'emploi, couvrant tous les
  domaines (médical, RH, compta, pharmacie, matériel, recherche).
- **Colonne de droite** — « Comment ça marche ? » : un rappel de ce que fait
  chaque approche, et l'accès au schéma de la base.

## 2. Thème sombre

![Thème sombre](docs/screenshots/02-accueil-sombre.png)

Le bouton 🌓 (ou votre préférence système) bascule toute l'interface en sombre.
Le choix est mémorisé pour vos prochaines visites.

## 3. Explorer le schéma

![Schéma](docs/screenshots/03-schema.png)

Dépliez **« Schéma de la base (30 tables) »** pour voir le DDL complet — c'est
*exactement* le contexte que reçoivent les modèles pour écrire le SQL. Utile pour
comprendre pourquoi une requête joint telle ou telle table.

## 4. Poser une question et exécuter

![Résultat SQL](docs/screenshots/04-resultat-sql.png)

1. Cliquez un exemple (ou tapez votre question). Astuce : **Ctrl/Cmd + Entrée**
   lance aussi l'exécution.
2. Choisissez une approche, puis **Exécuter**.
3. Chaque résultat affiche, dans l'ordre :
   - le **nom de l'approche**, le **modèle** utilisé et la **latence** ;
   - une **note pédagogique** (ce que fait l'approche) ;
   - le **SQL généré** (le cœur de la démo — toujours visible) ;
   - le **tableau des résultats** (nombre de lignes, aperçu).

Les modèles locaux prennent quelques secondes (davantage au tout premier appel,
le temps de charger le modèle en mémoire).

## 5. Générer une figure (Gemma)

![Figure Vega-Lite](docs/screenshots/05-figure-vega.png)

Cliquez **📊 Générer une figure (Gemma)** sous un tableau. Le modèle `gemma4`
choisit le type de graphique adapté (barres, courbe, camembert, nuage,
histogramme) et les colonnes ; la figure est rendue en **Vega-Lite** dans le
navigateur. La phrase sous le graphique explique *pourquoi* Gemma a choisi cette
visualisation.

> Gemma peut légitimement juger qu'aucune figure n'a de sens (ex. un simple
> `COUNT(*)` sur une ligne) : il vous le dira plutôt que de forcer un graphe.

## 6. Comparer les trois approches

![Comparaison](docs/screenshots/06-comparaison.png)

Choisissez **`Toutes`** puis **Exécuter** : les trois approches traitent la même
question et s'affichent l'une sous l'autre. C'est la vue idéale pour montrer à
des collègues **comment chaque méthode écrit le SQL différemment** — et comparer
latences et résultats.

---

## Questions fréquentes

- **Une approche est grisée / indisponible.** Son badge est rouge : la
  dépendance manque (`pip install ...`) ou Ollama est éteint. QwenCoder ne
  dépend d'aucun framework et marche dès qu'Ollama tourne.
- **« Erreur d'exécution ».** Le SQL généré était invalide — c'est instructif :
  on voit ce que le modèle a produit et pourquoi ça n'a pas passé le garde-fou
  lecture seule.
- **Rien ne se passe / très lent.** Premier appel = chargement du modèle. Les
  suivants sont bien plus rapides.
- **Mes données sortent-elles de la machine ?** Non. Tout est local (Ollama +
  SQLite). Aucune requête vers un service externe (hors polices web du front).
