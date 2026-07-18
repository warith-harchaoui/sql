"""
golden.py — Jeu de questions de référence pour l'évaluation text2sql.

Chaque cas associe une question en langage naturel à une requête SQL de
*référence* écrite et vérifiée à la main. On n'évalue PAS la ressemblance
textuelle entre le SQL généré et le SQL de référence (deux requêtes très
différentes peuvent être toutes deux correctes) : on compare les **résultats
d'exécution**. Le SQL de référence sert donc à produire le résultat attendu sur
la base déterministe.

Les cas couvrent les grands domaines (médical, RH, compta, pharmacie, matériel,
recherche) et plusieurs difficultés (agrégats simples, jointures, filtres,
regroupements temporels) pour que l'accuracy mesurée soit représentative.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GoldenCase:
    """Un cas d'évaluation : question + SQL de référence vérifié.

    Attributes
    ----------
    id : str
        Identifiant stable du cas (utile dans les rapports).
    domaine : str
        Domaine métier couvert.
    question : str
        Question en langage naturel soumise aux approches.
    sql_ref : str
        Requête SQL correcte de référence (produit le résultat attendu).
    ordered : bool
        Vrai si l'ordre des lignes fait partie de la réponse (présence d'un
        ORDER BY sémantiquement important). Sinon la comparaison est faite en
        ensembliste (ordre ignoré).
    """

    id: str
    domaine: str
    question: str
    sql_ref: str
    ordered: bool = False


# Jeu de référence. Les requêtes sont volontairement « canoniques » et lisibles ;
# elles sont testées à l'import de la suite d'éval (elles doivent toutes
# s'exécuter sans erreur sur la base générée).
GOLDEN: list[GoldenCase] = [
    GoldenCase(
        id="med-01",
        domaine="Médical",
        question="Combien de patients distincts par localisation de cancer ?",
        sql_ref="SELECT localisation, COUNT(DISTINCT patient_id) AS n "
        "FROM diagnostics GROUP BY localisation",
    ),
    GoldenCase(
        id="med-02",
        domaine="Médical",
        question="Nombre de diagnostics par stade global du cancer.",
        sql_ref="SELECT stade_global, COUNT(*) AS n FROM diagnostics GROUP BY stade_global",
    ),
    GoldenCase(
        id="med-03",
        domaine="Médical",
        question="Combien de patients ont le statut vital 'Décédé' ?",
        sql_ref="SELECT COUNT(*) AS n FROM patients WHERE statut_vital = 'Décédé'",
    ),
    GoldenCase(
        id="rh-01",
        domaine="RH",
        question="Nombre d'employés par catégorie.",
        sql_ref="SELECT categorie, COUNT(*) AS n FROM employes GROUP BY categorie",
    ),
    GoldenCase(
        id="rh-02",
        domaine="RH",
        question="Combien de services l'institut compte-t-il ?",
        sql_ref="SELECT COUNT(*) AS n FROM services",
    ),
    GoldenCase(
        id="pharma-01",
        domaine="Pharmacie",
        question="Quels médicaments sont sous leur seuil d'alerte de stock ?",
        sql_ref="SELECT m.nom FROM stocks s JOIN medicaments m "
        "ON m.medicament_id = s.medicament_id WHERE s.quantite < s.seuil_alerte",
    ),
    GoldenCase(
        id="pharma-02",
        domaine="Pharmacie",
        question="Nombre de médicaments par classe thérapeutique.",
        sql_ref="SELECT classe, COUNT(*) AS n FROM medicaments GROUP BY classe",
    ),
    GoldenCase(
        id="compta-01",
        domaine="Comptabilité",
        question="Combien de factures sont impayées ?",
        sql_ref="SELECT COUNT(*) AS n FROM factures WHERE statut = 'Impayée'",
    ),
    GoldenCase(
        id="materiel-01",
        domaine="Matériel",
        question="Combien d'équipements par catégorie ?",
        sql_ref="SELECT categorie, COUNT(*) AS n FROM equipements GROUP BY categorie",
    ),
    GoldenCase(
        id="recherche-01",
        domaine="Recherche",
        question="Combien d'essais cliniques sont au statut 'Ouvert' ?",
        sql_ref="SELECT COUNT(*) AS n FROM essais_cliniques WHERE statut = 'Ouvert'",
    ),
]


# Jeu DIFFICILE : regroupements temporels, multi-jointures, HAVING, fonctions de
# date, filtres croisés. Il existe pour EXPOSER le plafond réel — sur ce jeu, un
# modèle local ne fait pas 100 %. C'est l'honnêteté qui manquait à un jeu trop
# facile (cf. ASSESSMENT.md). À lancer avec `--hard`.
GOLDEN_HARD: list[GoldenCase] = [
    GoldenCase(
        id="hard-temporel-01",
        domaine="Activité",
        question="Nombre de séances de radiothérapie par mois en 2026, par ordre chronologique.",
        sql_ref="SELECT strftime('%Y-%m', date) AS mois, COUNT(*) AS n "
        "FROM seances_radio WHERE date >= '2026-01-01' AND date < '2027-01-01' "
        "GROUP BY mois ORDER BY mois",
        ordered=True,
    ),
    GoldenCase(
        id="hard-having-01",
        domaine="Médical",
        question="Quelles localisations de cancer comptent plus de 40 patients distincts ?",
        sql_ref="SELECT localisation, COUNT(DISTINCT patient_id) AS n FROM diagnostics "
        "GROUP BY localisation HAVING COUNT(DISTINCT patient_id) > 40",
    ),
    GoldenCase(
        id="hard-join-01",
        domaine="RH",
        question="Masse salariale mensuelle par service, pour les contrats en cours seulement.",
        sql_ref="SELECT se.nom AS service, SUM(c.salaire_brut_mensuel) AS masse "
        "FROM contrats c JOIN employes e ON e.employe_id = c.employe_id "
        "JOIN services se ON se.service_id = e.service_id "
        "WHERE c.date_fin IS NULL GROUP BY se.nom",
    ),
    GoldenCase(
        id="hard-join-02",
        domaine="Médical",
        question="Nombre de patients décédés par localisation de cancer.",
        sql_ref="SELECT d.localisation, COUNT(DISTINCT p.patient_id) AS n "
        "FROM patients p JOIN diagnostics d ON d.patient_id = p.patient_id "
        "WHERE p.statut_vital = 'Décédé' GROUP BY d.localisation",
    ),
    GoldenCase(
        id="hard-date-01",
        domaine="Activité",
        question="Durée moyenne de séjour en jours pour les hospitalisations complètes.",
        sql_ref="SELECT AVG(julianday(date_sortie) - julianday(date_entree)) AS duree_moyenne "
        "FROM sejours WHERE type_sejour = 'Hospitalisation'",
    ),
    GoldenCase(
        id="hard-agg-01",
        domaine="Comptabilité",
        question="Montant total facturé et reste à charge total pour les factures impayées.",
        sql_ref="SELECT SUM(montant_total_eur) AS total, SUM(reste_a_charge_eur) AS rac "
        "FROM factures WHERE statut = 'Impayée'",
    ),
]
