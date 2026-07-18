"""
benchmark_set.py — Grand jeu de requêtes réaliste pour le benchmark.

On assemble un jeu volumineux et varié (« beaucoup d'exemples ») pour une
comparaison numérique crédible latence / vitesse / exactitude des trois
approches. Trois paliers de difficulté :

  - **facile**    : agrégats simples, filtres directs, une table.
  - **moyen**     : une jointure, GROUP BY, tri, filtres métier courants.
  - **difficile** : multi-jointures, HAVING, sous-requêtes, fonctions de date,
                    fenêtres temporelles (trimestres), bucketing par CASE.

On réutilise les jeux existants (``GOLDEN`` → facile, ``GOLDEN_HARD`` →
difficile) et on ajoute une large batterie de cas intermédiaires et durs. Toutes
les requêtes de référence sont vérifiées à l'import (elles doivent s'exécuter).
"""
from __future__ import annotations

import dataclasses

from .golden import GOLDEN, GOLDEN_HARD, GoldenCase

# --------------------------------------------------------------------------- #
# Cas MOYENS : une jointure / un GROUP BY / un tri / un filtre métier.        #
# --------------------------------------------------------------------------- #
MEDIUM: list[GoldenCase] = [
    GoldenCase("moy-01", "Médical", "Répartition des patients par groupe sanguin.",
               "SELECT groupe_sanguin, COUNT(*) AS n FROM patients GROUP BY groupe_sanguin",
               difficulte="moyen"),
    GoldenCase("moy-02", "Médical", "Nombre de patients par sexe.",
               "SELECT sexe, COUNT(*) AS n FROM patients GROUP BY sexe", difficulte="moyen"),
    GoldenCase("moy-03", "Médical", "Nombre de traitements par type de traitement.",
               "SELECT type, COUNT(*) AS n FROM traitements GROUP BY type", difficulte="moyen"),
    GoldenCase("moy-04", "Médical", "Nombre de chirurgies par type de complication.",
               "SELECT complications, COUNT(*) AS n FROM chirurgies GROUP BY complications",
               difficulte="moyen"),
    GoldenCase("moy-05", "RH", "Nombre d'employés par métier.",
               "SELECT metier, COUNT(*) AS n FROM employes GROUP BY metier", difficulte="moyen"),
    GoldenCase("moy-06", "RH", "Nombre de contrats par type de contrat.",
               "SELECT type_contrat, COUNT(*) AS n FROM contrats GROUP BY type_contrat",
               difficulte="moyen"),
    GoldenCase("moy-07", "RH", "Nombre d'absences par type d'absence.",
               "SELECT type, COUNT(*) AS n FROM absences GROUP BY type", difficulte="moyen"),
    GoldenCase("moy-08", "Pharmacie", "Les 5 médicaments les plus chers à l'unité.",
               "SELECT nom, prix_unitaire_eur FROM medicaments "
               "ORDER BY prix_unitaire_eur DESC LIMIT 5", ordered=True, difficulte="moyen"),
    GoldenCase("moy-09", "Pharmacie", "Quantité totale en stock par classe de médicament.",
               "SELECT m.classe, SUM(s.quantite) AS q FROM stocks s "
               "JOIN medicaments m ON m.medicament_id = s.medicament_id GROUP BY m.classe",
               difficulte="moyen"),
    GoldenCase("moy-10", "Comptabilité", "Montant total encaissé par moyen de paiement.",
               "SELECT moyen, SUM(montant_eur) AS total FROM paiements GROUP BY moyen",
               difficulte="moyen"),
    GoldenCase("moy-11", "Comptabilité", "Nombre de factures par statut.",
               "SELECT statut, COUNT(*) AS n FROM factures GROUP BY statut", difficulte="moyen"),
    GoldenCase("moy-12", "Comptabilité", "Montant total facturé par mois d'émission en 2026.",
               "SELECT strftime('%Y-%m', date_emission) AS mois, SUM(montant_total_eur) AS total "
               "FROM factures WHERE date_emission >= '2026-01-01' AND date_emission < '2027-01-01' "
               "GROUP BY mois ORDER BY mois", ordered=True, difficulte="moyen"),
    GoldenCase("moy-13", "Matériel", "Nombre d'équipements par statut.",
               "SELECT statut, COUNT(*) AS n FROM equipements GROUP BY statut", difficulte="moyen"),
    GoldenCase("moy-14", "Matériel", "Coût total d'acquisition des équipements par catégorie.",
               "SELECT categorie, SUM(cout_acquisition_eur) AS total FROM equipements "
               "GROUP BY categorie", difficulte="moyen"),
    GoldenCase("moy-15", "Activité", "Nombre de consultations par service.",
               "SELECT se.nom AS service, COUNT(*) AS n FROM consultations c "
               "JOIN services se ON se.service_id = c.service_id GROUP BY se.nom",
               difficulte="moyen"),
    GoldenCase("moy-16", "Médical", "Nombre de cures de chimiothérapie par médicament.",
               "SELECT m.nom, COUNT(*) AS n FROM cures_chimio c "
               "JOIN medicaments m ON m.medicament_id = c.medicament_id GROUP BY m.nom",
               difficulte="moyen"),
    GoldenCase("moy-17", "Recherche", "Nombre d'inclusions par bras d'essai clinique.",
               "SELECT bras, COUNT(*) AS n FROM inclusions_essai GROUP BY bras",
               difficulte="moyen"),
    GoldenCase("moy-18", "Médical", "Les 5 effets indésirables les plus fréquents des cures.",
               "SELECT effets_indesirables, COUNT(*) AS n FROM cures_chimio "
               "GROUP BY effets_indesirables ORDER BY n DESC LIMIT 5", ordered=True,
               difficulte="moyen"),
    GoldenCase("moy-19", "Activité", "Nombre de séjours par type de séjour.",
               "SELECT type_sejour, COUNT(*) AS n FROM sejours GROUP BY type_sejour",
               difficulte="moyen"),
    GoldenCase("moy-20", "Matériel", "Nombre de maintenances par type.",
               "SELECT type, COUNT(*) AS n FROM maintenances GROUP BY type", difficulte="moyen"),
]

# --------------------------------------------------------------------------- #
# Cas DIFFICILES supplémentaires : multi-jointures, sous-requêtes, dates.      #
# --------------------------------------------------------------------------- #
HARD_EXTRA: list[GoldenCase] = [
    GoldenCase("dur-01", "RH", "Pour chaque service, le nombre d'employés médicaux.",
               "SELECT se.nom AS service, COUNT(*) AS n FROM employes e "
               "JOIN services se ON se.service_id = e.service_id "
               "WHERE e.categorie = 'Medical' GROUP BY se.nom", difficulte="difficile"),
    GoldenCase("dur-02", "Médical", "Top 5 des médecins référents par nombre de patients.",
               "SELECT e.nom, e.prenom, COUNT(*) AS n FROM patients p "
               "JOIN employes e ON e.employe_id = p.medecin_referent_id "
               "GROUP BY e.employe_id ORDER BY n DESC LIMIT 5", ordered=True,
               difficulte="difficile"),
    GoldenCase("dur-03", "Comptabilité", "Chiffre d'affaires encaissé par trimestre en 2026.",
               "SELECT 'T' || ((CAST(strftime('%m', date) AS INTEGER) + 2) / 3) AS trimestre, "
               "SUM(montant_eur) AS ca FROM paiements "
               "WHERE date >= '2026-01-01' AND date < '2027-01-01' "
               "GROUP BY trimestre ORDER BY trimestre", ordered=True, difficulte="difficile"),
    GoldenCase("dur-04", "Médical",
               "Combien de patients ont eu à la fois une chirurgie et de la radiothérapie ?",
               "SELECT COUNT(*) AS n FROM (SELECT patient_id FROM chirurgies "
               "INTERSECT SELECT patient_id FROM seances_radio)", difficulte="difficile"),
    GoldenCase("dur-05", "Pharmacie",
               "Quels médicaments n'ont jamais été utilisés dans une cure de chimiothérapie ?",
               "SELECT nom FROM medicaments WHERE medicament_id NOT IN "
               "(SELECT medicament_id FROM cures_chimio WHERE medicament_id IS NOT NULL)",
               difficulte="difficile"),
    GoldenCase("dur-06", "Activité", "Durée moyenne de séjour en jours par type de séjour.",
               "SELECT type_sejour, AVG(julianday(date_sortie) - julianday(date_entree)) AS duree "
               "FROM sejours GROUP BY type_sejour", difficulte="difficile"),
    GoldenCase("dur-07", "RH", "Top 3 des services par masse salariale (contrats en cours).",
               "SELECT se.nom AS service, SUM(c.salaire_brut_mensuel) AS masse "
               "FROM contrats c JOIN employes e ON e.employe_id = c.employe_id "
               "JOIN services se ON se.service_id = e.service_id "
               "WHERE c.date_fin IS NULL GROUP BY se.nom ORDER BY masse DESC LIMIT 3",
               ordered=True, difficulte="difficile"),
    GoldenCase("dur-08", "Médical", "Nombre de patients décédés par stade global du cancer.",
               "SELECT d.stade_global, COUNT(DISTINCT p.patient_id) AS n FROM patients p "
               "JOIN diagnostics d ON d.patient_id = p.patient_id "
               "WHERE p.statut_vital = 'Décédé' GROUP BY d.stade_global", difficulte="difficile"),
    GoldenCase("dur-09", "Médical",
               "Nombre moyen de cures de chimiothérapie par patient traité.",
               "SELECT AVG(n) AS moyenne FROM (SELECT COUNT(*) AS n FROM cures_chimio "
               "GROUP BY patient_id)", difficulte="difficile"),
    GoldenCase("dur-10", "Comptabilité", "Reste à charge moyen par statut de facture.",
               "SELECT statut, AVG(reste_a_charge_eur) AS rac_moyen FROM factures "
               "GROUP BY statut", difficulte="difficile"),
]


def _tag(cases: list[GoldenCase], niveau: str) -> list[GoldenCase]:
    """Ré-étiquette une liste de cas avec un niveau de difficulté.

    Parameters
    ----------
    cases : list[GoldenCase]
        Cas à ré-étiqueter (dataclass gelée → on recrée via ``replace``).
    niveau : str
        Difficulté à appliquer (« facile » / « difficile »).

    Returns
    -------
    list[GoldenCase]
        Nouveaux cas portant la difficulté voulue.
    """
    # ``GoldenCase`` est frozen : on ne mute pas, on recrée une copie taguée.
    return [dataclasses.replace(c, difficulte=niveau) for c in cases]


# Le grand jeu, ordonné du plus simple au plus dur (progression pédagogique).
BENCH: list[GoldenCase] = (
    _tag(GOLDEN, "facile") + MEDIUM + _tag(GOLDEN_HARD, "difficile") + HARD_EXTRA
)
