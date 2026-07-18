"""
Package d'évaluation IA de la démo text2sql.

Contenu
-------
- ``golden`` : jeu de questions de référence (question → SQL correct attendu).
- ``execution_match`` : métrique d'**exactitude d'exécution** (le résultat du SQL
  généré est-il identique à celui du SQL de référence ?) — la métrique reine du
  text2sql, indépendante de la façon d'écrire la requête.
- ``deepeval_metric`` : la même métrique empaquetée pour DeepEval (100 % local).
- ``giskard_scan`` : scan de robustesse (perturbations de la question).
- ``run_eval`` : point d'entrée CLI qui calcule l'accuracy par approche.

Toute cette couche se dégrade proprement si DeepEval / Giskard ne sont pas
installés : seule l'exactitude d'exécution « maison » est alors calculée.
"""
