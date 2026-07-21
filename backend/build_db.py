"""Génère une base SQLite riche et cohérente pour un hôpital.

Institut fictif : « Hôpital Deraison ».

Domaines couverts :
  - Médical      : patients, séjours, diagnostics (CIM-10 + TNM), traitements,
                   cures de chimiothérapie, séances de radiothérapie, chirurgies,
                   consultations, examens d'imagerie, biopsies, résultats de labo
  - Essais       : essais cliniques + inclusions
  - RH           : services, employés, contrats, absences, formations
  - Comptabilité : actes (tarifs CCAM-like), factures, lignes de facture, paiements
  - Achats       : fournisseurs, commandes, lignes de commande
  - Matériel     : équipements lourds + maintenances
  - Pharmacie    : médicaments, stocks, mouvements de stock

Tout est déterministe (seed figée) → base reproductible.

Usage :  python -m backend.build_db   [--out data/institut.db]
"""

from __future__ import annotations

import argparse
import datetime as dt
import logging
import random
import sqlite3
from pathlib import Path

from faker import Faker

# Logger de module : on proscrit `print` (cf. CODING.md §6). Le point d'entrée
# `__main__` configure un handler console pour que le script reste bavard en CLI.
logger = logging.getLogger(__name__)

SEED = 42
fake = Faker("fr_FR")
Faker.seed(SEED)
random.seed(SEED)

TODAY = dt.date(2026, 7, 18)

# --------------------------------------------------------------------------- #
# Référentiels métier                                                         #
# --------------------------------------------------------------------------- #

SERVICES = [
    ("Oncologie médicale", "ONC", 4, "Bâtiment A - Niveau 2"),
    ("Radiothérapie", "RTH", 3, "Bâtiment B - Niveau -1"),
    ("Chirurgie oncologique", "CHIR", 3, "Bâtiment A - Niveau 3"),
    ("Hématologie", "HEM", 2, "Bâtiment A - Niveau 4"),
    ("Imagerie médicale", "IMG", 2, "Bâtiment B - Niveau 0"),
    ("Anatomopathologie", "ANAPATH", 1, "Bâtiment C - Niveau 1"),
    ("Pharmacie hospitalière", "PHAR", 1, "Bâtiment C - Niveau -1"),
    ("Soins palliatifs", "PALL", 2, "Bâtiment A - Niveau 1"),
    ("Réanimation", "REA", 2, "Bâtiment A - Niveau 0"),
    ("Consultations externes", "CONS", 3, "Bâtiment A - Niveau 1"),
    ("Recherche clinique", "RECH", 1, "Bâtiment C - Niveau 2"),
    ("Administration & Finance", "ADM", 1, "Bâtiment D - Niveau 1"),
]

# (localisation, code CIM-10, libellé)
CANCERS = [
    ("Sein", "C50", "Tumeur maligne du sein"),
    ("Poumon", "C34", "Tumeur maligne des bronches et du poumon"),
    ("Côlon", "C18", "Tumeur maligne du côlon"),
    ("Prostate", "C61", "Tumeur maligne de la prostate"),
    ("Rectum", "C20", "Tumeur maligne du rectum"),
    ("Pancréas", "C25", "Tumeur maligne du pancréas"),
    ("Ovaire", "C56", "Tumeur maligne de l'ovaire"),
    ("Estomac", "C16", "Tumeur maligne de l'estomac"),
    ("Foie", "C22", "Tumeur maligne du foie"),
    ("Vessie", "C67", "Tumeur maligne de la vessie"),
    ("Rein", "C64", "Tumeur maligne du rein"),
    ("Mélanome", "C43", "Mélanome malin de la peau"),
    ("Leucémie aiguë", "C92", "Leucémie myéloïde"),
    ("Lymphome", "C85", "Lymphome non hodgkinien"),
    ("Col de l'utérus", "C53", "Tumeur maligne du col de l'utérus"),
    ("Thyroïde", "C73", "Tumeur maligne de la thyroïde"),
    ("Œsophage", "C15", "Tumeur maligne de l'œsophage"),
    ("Cerveau", "C71", "Tumeur maligne de l'encéphale"),
]

# Médicaments d'oncologie : (nom, DCI, classe, forme, prix_unitaire_eur)
MEDICAMENTS = [
    ("Cisplatine", "cisplatine", "Cytotoxique - sel de platine", "Solution injectable", 42.5),
    ("Carboplatine", "carboplatine", "Cytotoxique - sel de platine", "Solution injectable", 55.0),
    ("Oxaliplatine", "oxaliplatine", "Cytotoxique - sel de platine", "Solution injectable", 120.0),
    ("Paclitaxel", "paclitaxel", "Cytotoxique - taxane", "Solution injectable", 89.0),
    ("Docetaxel", "docetaxel", "Cytotoxique - taxane", "Solution injectable", 210.0),
    ("Doxorubicine", "doxorubicine", "Cytotoxique - anthracycline", "Solution injectable", 38.0),
    (
        "5-Fluorouracile",
        "fluorouracile",
        "Cytotoxique - antimétabolite",
        "Solution injectable",
        12.0,
    ),
    ("Gemcitabine", "gemcitabine", "Cytotoxique - antimétabolite", "Solution injectable", 95.0),
    (
        "Cyclophosphamide",
        "cyclophosphamide",
        "Cytotoxique - alkylant",
        "Poudre pour solution",
        28.0,
    ),
    ("Trastuzumab", "trastuzumab", "Thérapie ciblée - anti-HER2", "Solution injectable", 680.0),
    ("Bevacizumab", "bevacizumab", "Thérapie ciblée - anti-VEGF", "Solution injectable", 540.0),
    ("Rituximab", "rituximab", "Thérapie ciblée - anti-CD20", "Solution injectable", 720.0),
    ("Pembrolizumab", "pembrolizumab", "Immunothérapie - anti-PD1", "Solution injectable", 2400.0),
    ("Nivolumab", "nivolumab", "Immunothérapie - anti-PD1", "Solution injectable", 1350.0),
    ("Imatinib", "imatinib", "Thérapie ciblée - inhibiteur tyrosine kinase", "Comprimé", 75.0),
    ("Tamoxifène", "tamoxifène", "Hormonothérapie", "Comprimé", 0.8),
    ("Létrozole", "létrozole", "Hormonothérapie - anti-aromatase", "Comprimé", 1.2),
    ("Ondansétron", "ondansétron", "Antiémétique", "Comprimé", 0.5),
    ("Morphine", "morphine", "Antalgique - opioïde", "Solution injectable", 2.5),
    ("Filgrastim", "filgrastim", "Facteur de croissance (G-CSF)", "Solution injectable", 110.0),
]

# Équipements lourds : (nom, catégorie, marque, coût_eur, service_code)
EQUIPEMENTS = [
    ("Accélérateur linéaire TrueBeam", "Radiothérapie", "Varian", 3200000, "RTH"),
    ("Accélérateur linéaire Halcyon", "Radiothérapie", "Varian", 2800000, "RTH"),
    ("Scanner CT 128 barrettes", "Imagerie", "Siemens", 850000, "IMG"),
    ("IRM 3 Tesla", "Imagerie", "GE Healthcare", 1600000, "IMG"),
    ("TEP-scan (PET-CT)", "Imagerie", "Siemens", 2100000, "IMG"),
    ("Mammographe numérique", "Imagerie", "Hologic", 320000, "IMG"),
    ("Échographe haut de gamme", "Imagerie", "Philips", 145000, "IMG"),
    ("Automate d'anatomopathologie", "Laboratoire", "Leica", 210000, "ANAPATH"),
    ("Isolateur pharmacie (URC)", "Pharmacie", "Comecer", 180000, "PHAR"),
    ("Curiethérapie HDR", "Radiothérapie", "Elekta", 950000, "RTH"),
    ("Cytométre de flux", "Laboratoire", "BD Biosciences", 260000, "HEM"),
    ("Respirateur de réanimation", "Réanimation", "Dräger", 45000, "REA"),
]

FOURNISSEURS = [
    ("PharmaDis SA", "Médicaments", "Lyon"),
    ("MediSupply France", "Consommables médicaux", "Paris"),
    ("OncoLab Distribution", "Réactifs de laboratoire", "Strasbourg"),
    ("Varian Medical Systems", "Équipement radiothérapie", "Buc"),
    ("Siemens Healthineers", "Imagerie médicale", "Saint-Denis"),
    ("BioReactifs Plus", "Réactifs anatomopathologie", "Toulouse"),
    ("HospiClean Services", "Hygiène & stérilisation", "Nantes"),
    ("NutriSanté Pro", "Nutrition clinique", "Bordeaux"),
]

ACTES = [
    ("CONS-ONC", "Consultation oncologie médicale", 56.0),
    ("CONS-RTH", "Consultation radiothérapie", 56.0),
    ("CHIMIO-J", "Séance de chimiothérapie (hôpital de jour)", 420.0),
    ("RTH-SEANCE", "Séance de radiothérapie", 190.0),
    ("SCAN-TAP", "Scanner thoraco-abdomino-pelvien", 230.0),
    ("IRM", "Imagerie par résonance magnétique", 340.0),
    ("TEP", "Tomographie par émission de positons", 950.0),
    ("MAMMO", "Mammographie bilatérale", 66.0),
    ("BIOPSIE", "Biopsie sous contrôle radiologique", 180.0),
    ("CHIR-EXER", "Exérèse tumorale chirurgicale", 1250.0),
    ("ANAPATH", "Examen anatomopathologique", 85.0),
    ("BILAN-BIO", "Bilan biologique complet", 48.0),
    ("HOSPIT-J", "Journée d'hospitalisation complète", 890.0),
    ("RCP", "Réunion de concertation pluridisciplinaire", 0.0),
]

METIERS_MED = [
    "Oncologue",
    "Radiothérapeute",
    "Chirurgien",
    "Hématologue",
    "Radiologue",
    "Anatomopathologiste",
    "Médecin réanimateur",
]
METIERS_PARAMED = [
    "Infirmier(e)",
    "Manipulateur radio",
    "Aide-soignant(e)",
    "Pharmacien(ne)",
    "Préparateur pharmacie",
    "Technicien labo",
    "Psychologue",
    "Diététicien(ne)",
    "Kinésithérapeute",
]
METIERS_ADMIN = [
    "Secrétaire médicale",
    "Gestionnaire admin",
    "Comptable",
    "Attaché de recherche clinique",
    "Cadre de santé",
    "Directeur",
]

GRADES_STAGE = ["I", "II", "III", "IV"]


def d(base: dt.date, lo: int, hi: int) -> str:
    """Date ISO = base décalée d'un nombre de jours aléatoire dans [lo, hi]."""
    return (base + dt.timedelta(days=random.randint(lo, hi))).isoformat()


# --------------------------------------------------------------------------- #
# Schéma                                                                      #
# --------------------------------------------------------------------------- #

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE services (
    service_id       INTEGER PRIMARY KEY,
    nom              TEXT NOT NULL,
    code             TEXT NOT NULL UNIQUE,
    nb_medecins_cible INTEGER,
    localisation     TEXT
);

CREATE TABLE employes (
    employe_id   INTEGER PRIMARY KEY,
    matricule    TEXT UNIQUE,
    nom          TEXT NOT NULL,
    prenom       TEXT NOT NULL,
    sexe         TEXT,
    date_naissance TEXT,
    metier       TEXT NOT NULL,
    categorie    TEXT NOT NULL,           -- Medical / Paramedical / Administratif
    service_id   INTEGER REFERENCES services(service_id),
    email        TEXT,
    telephone    TEXT
);

CREATE TABLE contrats (
    contrat_id     INTEGER PRIMARY KEY,
    employe_id     INTEGER NOT NULL REFERENCES employes(employe_id),
    type_contrat   TEXT NOT NULL,         -- CDI / CDD / Interim / Vacation
    date_debut     TEXT NOT NULL,
    date_fin       TEXT,                  -- NULL = en cours
    temps_travail  REAL,                  -- ETP (0.5, 0.8, 1.0)
    salaire_brut_mensuel REAL
);

CREATE TABLE absences (
    absence_id   INTEGER PRIMARY KEY,
    employe_id   INTEGER NOT NULL REFERENCES employes(employe_id),
    type         TEXT NOT NULL,           -- Congés payés / Maladie / Formation / RTT
    date_debut   TEXT NOT NULL,
    date_fin     TEXT NOT NULL,
    nb_jours     INTEGER
);

CREATE TABLE formations (
    formation_id INTEGER PRIMARY KEY,
    employe_id   INTEGER NOT NULL REFERENCES employes(employe_id),
    intitule     TEXT NOT NULL,
    organisme    TEXT,
    date         TEXT,
    duree_heures INTEGER,
    cout_eur     REAL
);

CREATE TABLE patients (
    patient_id     INTEGER PRIMARY KEY,
    num_dossier    TEXT UNIQUE,
    nom            TEXT NOT NULL,
    prenom         TEXT NOT NULL,
    sexe           TEXT,
    date_naissance TEXT,
    groupe_sanguin TEXT,
    ville          TEXT,
    code_postal    TEXT,
    telephone      TEXT,
    date_premiere_venue TEXT,
    medecin_referent_id INTEGER REFERENCES employes(employe_id),
    statut_vital   TEXT                   -- Vivant / Décédé / En rémission
);

CREATE TABLE diagnostics (
    diagnostic_id  INTEGER PRIMARY KEY,
    patient_id     INTEGER NOT NULL REFERENCES patients(patient_id),
    localisation   TEXT NOT NULL,
    code_cim10     TEXT NOT NULL,
    libelle        TEXT,
    date_diagnostic TEXT NOT NULL,
    stade_tnm      TEXT,                  -- ex: T2N1M0
    stade_global   TEXT,                  -- I / II / III / IV
    grade_histologique TEXT,
    medecin_id     INTEGER REFERENCES employes(employe_id)
);

CREATE TABLE essais_cliniques (
    essai_id     INTEGER PRIMARY KEY,
    code         TEXT UNIQUE,
    titre        TEXT NOT NULL,
    phase        TEXT,                    -- I / II / III
    promoteur    TEXT,
    localisation_cible TEXT,
    date_ouverture TEXT,
    date_cloture TEXT,
    nb_places    INTEGER,
    statut       TEXT                     -- Ouvert / Clos / Suspendu
);

CREATE TABLE inclusions_essai (
    inclusion_id INTEGER PRIMARY KEY,
    essai_id     INTEGER NOT NULL REFERENCES essais_cliniques(essai_id),
    patient_id   INTEGER NOT NULL REFERENCES patients(patient_id),
    date_inclusion TEXT,
    bras         TEXT,                    -- Bras A (traitement) / Bras B (contrôle)
    statut       TEXT                     -- En cours / Sorti / Terminé
);

CREATE TABLE sejours (
    sejour_id    INTEGER PRIMARY KEY,
    patient_id   INTEGER NOT NULL REFERENCES patients(patient_id),
    service_id   INTEGER NOT NULL REFERENCES services(service_id),
    type_sejour  TEXT,                    -- Hospitalisation / Hôpital de jour / Ambulatoire
    date_entree  TEXT NOT NULL,
    date_sortie  TEXT,
    motif        TEXT
);

CREATE TABLE consultations (
    consultation_id INTEGER PRIMARY KEY,
    patient_id   INTEGER NOT NULL REFERENCES patients(patient_id),
    medecin_id   INTEGER REFERENCES employes(employe_id),
    service_id   INTEGER REFERENCES services(service_id),
    date         TEXT NOT NULL,
    motif        TEXT,
    compte_rendu TEXT
);

CREATE TABLE traitements (
    traitement_id INTEGER PRIMARY KEY,
    patient_id   INTEGER NOT NULL REFERENCES patients(patient_id),
    diagnostic_id INTEGER REFERENCES diagnostics(diagnostic_id),
    type         TEXT NOT NULL,           -- Chimio/Radio/Chirurgie/Immuno/Hormono
    protocole    TEXT,
    date_debut   TEXT,
    date_fin     TEXT,
    intention    TEXT,                    -- Curative / Palliative / Néoadjuvante / Adjuvante
    medecin_id   INTEGER REFERENCES employes(employe_id)
);

CREATE TABLE cures_chimio (
    cure_id      INTEGER PRIMARY KEY,
    traitement_id INTEGER NOT NULL REFERENCES traitements(traitement_id),
    patient_id   INTEGER NOT NULL REFERENCES patients(patient_id),
    numero_cure  INTEGER,
    date         TEXT NOT NULL,
    medicament_id INTEGER REFERENCES medicaments(medicament_id),
    dose_mg      REAL,
    surface_corporelle REAL,
    effets_indesirables TEXT
);

CREATE TABLE seances_radio (
    seance_id    INTEGER PRIMARY KEY,
    traitement_id INTEGER NOT NULL REFERENCES traitements(traitement_id),
    patient_id   INTEGER NOT NULL REFERENCES patients(patient_id),
    equipement_id INTEGER REFERENCES equipements(equipement_id),
    date         TEXT NOT NULL,
    dose_gray    REAL,
    zone_traitee TEXT,
    numero_seance INTEGER
);

CREATE TABLE chirurgies (
    chirurgie_id INTEGER PRIMARY KEY,
    patient_id   INTEGER NOT NULL REFERENCES patients(patient_id),
    traitement_id INTEGER REFERENCES traitements(traitement_id),
    chirurgien_id INTEGER REFERENCES employes(employe_id),
    date         TEXT NOT NULL,
    intitule     TEXT,
    duree_minutes INTEGER,
    bloc         TEXT,
    complications TEXT
);

CREATE TABLE examens_imagerie (
    examen_id    INTEGER PRIMARY KEY,
    patient_id   INTEGER NOT NULL REFERENCES patients(patient_id),
    equipement_id INTEGER REFERENCES equipements(equipement_id),
    type         TEXT,                    -- Scanner / IRM / TEP / Mammographie / Échographie
    date         TEXT NOT NULL,
    region       TEXT,
    resultat     TEXT,                    -- Progression/Stabilité/Réponse partielle/complète
    radiologue_id INTEGER REFERENCES employes(employe_id)
);

CREATE TABLE biopsies (
    biopsie_id   INTEGER PRIMARY KEY,
    patient_id   INTEGER NOT NULL REFERENCES patients(patient_id),
    date         TEXT NOT NULL,
    organe       TEXT,
    type_histologique TEXT,
    resultat     TEXT,                    -- Bénin / Malin
    pathologiste_id INTEGER REFERENCES employes(employe_id)
);

CREATE TABLE resultats_labo (
    resultat_id  INTEGER PRIMARY KEY,
    patient_id   INTEGER NOT NULL REFERENCES patients(patient_id),
    date         TEXT NOT NULL,
    analyte      TEXT,                    -- Hémoglobine/Leucocytes/Plaquettes/Créat/CRP/Marqueur
    valeur       REAL,
    unite        TEXT,
    hors_norme   INTEGER                  -- 0/1
);

CREATE TABLE medicaments (
    medicament_id INTEGER PRIMARY KEY,
    nom          TEXT NOT NULL,
    dci          TEXT,
    classe       TEXT,
    forme        TEXT,
    prix_unitaire_eur REAL
);

CREATE TABLE stocks (
    stock_id     INTEGER PRIMARY KEY,
    medicament_id INTEGER NOT NULL REFERENCES medicaments(medicament_id),
    quantite     INTEGER,
    seuil_alerte INTEGER,
    date_peremption TEXT,
    numero_lot   TEXT
);

CREATE TABLE mouvements_stock (
    mouvement_id INTEGER PRIMARY KEY,
    medicament_id INTEGER NOT NULL REFERENCES medicaments(medicament_id),
    date         TEXT NOT NULL,
    type         TEXT,                    -- Entrée / Sortie
    quantite     INTEGER,
    motif        TEXT
);

CREATE TABLE equipements (
    equipement_id INTEGER PRIMARY KEY,
    nom          TEXT NOT NULL,
    categorie    TEXT,
    marque       TEXT,
    cout_acquisition_eur REAL,
    date_acquisition TEXT,
    service_id   INTEGER REFERENCES services(service_id),
    statut       TEXT                     -- Opérationnel / En maintenance / Hors service
);

CREATE TABLE maintenances (
    maintenance_id INTEGER PRIMARY KEY,
    equipement_id INTEGER NOT NULL REFERENCES equipements(equipement_id),
    date         TEXT NOT NULL,
    type         TEXT,                    -- Préventive / Corrective
    cout_eur     REAL,
    duree_heures REAL,
    prestataire  TEXT
);

CREATE TABLE fournisseurs (
    fournisseur_id INTEGER PRIMARY KEY,
    nom          TEXT NOT NULL,
    categorie    TEXT,
    ville        TEXT
);

CREATE TABLE commandes (
    commande_id  INTEGER PRIMARY KEY,
    fournisseur_id INTEGER NOT NULL REFERENCES fournisseurs(fournisseur_id),
    service_id   INTEGER REFERENCES services(service_id),
    date_commande TEXT NOT NULL,
    date_livraison TEXT,
    statut       TEXT,                    -- Commandée / Livrée / Annulée
    montant_total_eur REAL
);

CREATE TABLE lignes_commande (
    ligne_id     INTEGER PRIMARY KEY,
    commande_id  INTEGER NOT NULL REFERENCES commandes(commande_id),
    designation  TEXT,
    quantite     INTEGER,
    prix_unitaire_eur REAL,
    montant_eur  REAL
);

CREATE TABLE actes (
    acte_id      INTEGER PRIMARY KEY,
    code         TEXT UNIQUE,
    libelle      TEXT NOT NULL,
    tarif_eur    REAL
);

CREATE TABLE factures (
    facture_id   INTEGER PRIMARY KEY,
    patient_id   INTEGER NOT NULL REFERENCES patients(patient_id),
    date_emission TEXT NOT NULL,
    montant_total_eur REAL,
    part_secu_eur REAL,
    part_mutuelle_eur REAL,
    reste_a_charge_eur REAL,
    statut       TEXT                     -- Payée / En attente / Partielle / Impayée
);

CREATE TABLE lignes_facture (
    ligne_id     INTEGER PRIMARY KEY,
    facture_id   INTEGER NOT NULL REFERENCES factures(facture_id),
    acte_id      INTEGER REFERENCES actes(acte_id),
    quantite     INTEGER,
    montant_eur  REAL
);

CREATE TABLE paiements (
    paiement_id  INTEGER PRIMARY KEY,
    facture_id   INTEGER NOT NULL REFERENCES factures(facture_id),
    date         TEXT NOT NULL,
    montant_eur  REAL,
    moyen        TEXT                     -- Sécurité sociale / Mutuelle / CB / Chèque / Espèces
);
"""


# --------------------------------------------------------------------------- #
# Génération des données                                                      #
# --------------------------------------------------------------------------- #


def build(out_path: Path) -> None:
    """Génère la base SQLite complète à ``out_path`` (schéma + données).

    Parameters
    ----------
    out_path : pathlib.Path
        Chemin du fichier SQLite à créer (écrasé s'il existe).
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.exists():
        out_path.unlink()

    con = sqlite3.connect(out_path)
    con.executescript(SCHEMA)
    cur = con.cursor()

    # ---- services -------------------------------------------------------- #
    for i, (nom, code, nb, loc) in enumerate(SERVICES, 1):
        cur.execute("INSERT INTO services VALUES (?,?,?,?,?)", (i, nom, code, nb, loc))
    service_by_code = {code: i for i, (_, code, _, _) in enumerate(SERVICES, 1)}

    # ---- actes ----------------------------------------------------------- #
    for i, (code, lib, tarif) in enumerate(ACTES, 1):
        cur.execute("INSERT INTO actes VALUES (?,?,?,?)", (i, code, lib, tarif))

    # ---- médicaments + stocks ------------------------------------------- #
    for i, (nom, dci, classe, forme, prix) in enumerate(MEDICAMENTS, 1):
        cur.execute(
            "INSERT INTO medicaments VALUES (?,?,?,?,?,?)", (i, nom, dci, classe, forme, prix)
        )
        qte = random.randint(5, 400)
        seuil = random.randint(20, 60)
        cur.execute(
            "INSERT INTO stocks VALUES (?,?,?,?,?,?)",
            (i, i, qte, seuil, d(TODAY, 60, 720), f"LOT{random.randint(10000, 99999)}"),
        )
    n_med = len(MEDICAMENTS)

    # mouvements de stock
    mid = 1
    for med_id in range(1, n_med + 1):
        for _ in range(random.randint(4, 12)):
            typ = random.choice(["Entrée", "Sortie", "Sortie", "Sortie"])
            cur.execute(
                "INSERT INTO mouvements_stock VALUES (?,?,?,?,?,?)",
                (
                    mid,
                    med_id,
                    d(TODAY, -365, 0),
                    typ,
                    random.randint(1, 50),
                    "Réappro fournisseur" if typ == "Entrée" else "Préparation cure",
                ),
            )
            mid += 1

    # ---- fournisseurs ---------------------------------------------------- #
    for i, (nom, cat, ville) in enumerate(FOURNISSEURS, 1):
        cur.execute("INSERT INTO fournisseurs VALUES (?,?,?,?)", (i, nom, cat, ville))
    n_four = len(FOURNISSEURS)

    # ---- équipements + maintenances ------------------------------------- #
    for i, (nom, cat, marque, cout, scode) in enumerate(EQUIPEMENTS, 1):
        cur.execute(
            "INSERT INTO equipements VALUES (?,?,?,?,?,?,?,?)",
            (
                i,
                nom,
                cat,
                marque,
                cout,
                d(TODAY, -3650, -180),
                service_by_code[scode],
                random.choice(["Opérationnel"] * 8 + ["En maintenance", "Hors service"]),
            ),
        )
    n_equip = len(EQUIPEMENTS)

    mtid = 1
    for eq_id in range(1, n_equip + 1):
        for _ in range(random.randint(2, 8)):
            typ = random.choice(["Préventive", "Préventive", "Corrective"])
            cur.execute(
                "INSERT INTO maintenances VALUES (?,?,?,?,?,?,?)",
                (
                    mtid,
                    eq_id,
                    d(TODAY, -900, 0),
                    typ,
                    round(random.uniform(500, 45000), 2),
                    round(random.uniform(1, 24), 1),
                    random.choice(["Constructeur", "SAV interne", "Prestataire agréé"]),
                ),
            )
            mtid += 1

    # ---- employés (+ contrats, absences, formations) -------------------- #
    employes = []  # (id, service_id, categorie)
    medecins_by_service = {}
    eid = 1
    # médecins par service médical
    med_services = ["ONC", "RTH", "CHIR", "HEM", "IMG", "ANAPATH", "REA", "CONS", "PALL"]
    for scode in med_services:
        sid = service_by_code[scode]
        medecins_by_service[sid] = []
        for _ in range(random.randint(4, 9)):
            sexe = random.choice(["M", "F"])
            nom = fake.last_name()
            prenom = fake.first_name_male() if sexe == "M" else fake.first_name_female()
            metier = {
                "ONC": "Oncologue",
                "RTH": "Radiothérapeute",
                "CHIR": "Chirurgien",
                "HEM": "Hématologue",
                "IMG": "Radiologue",
                "ANAPATH": "Anatomopathologiste",
                "REA": "Médecin réanimateur",
                "CONS": random.choice(METIERS_MED),
                "PALL": "Oncologue",
            }[scode]
            cur.execute(
                "INSERT INTO employes VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    eid,
                    f"MED{eid:04d}",
                    nom,
                    prenom,
                    sexe,
                    fake.date_of_birth(minimum_age=32, maximum_age=64).isoformat(),
                    metier,
                    "Medical",
                    sid,
                    f"{prenom.lower()}.{nom.lower()}@hopital-deraison.fr",
                    fake.phone_number(),
                ),
            )
            employes.append((eid, sid, "Medical"))
            medecins_by_service[sid].append(eid)
            eid += 1

    # paramédicaux & administratifs répartis
    for _ in range(80):
        cat = random.choice(["Paramedical"] * 3 + ["Administratif"])
        metier = random.choice(METIERS_PARAMED if cat == "Paramedical" else METIERS_ADMIN)
        sid = random.randint(1, len(SERVICES))
        sexe = random.choice(["M", "F"])
        nom = fake.last_name()
        prenom = fake.first_name_male() if sexe == "M" else fake.first_name_female()
        cur.execute(
            "INSERT INTO employes VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                eid,
                f"EMP{eid:04d}",
                nom,
                prenom,
                sexe,
                fake.date_of_birth(minimum_age=22, maximum_age=63).isoformat(),
                metier,
                cat,
                sid,
                f"{prenom.lower()}.{nom.lower()}@hopital-deraison.fr",
                fake.phone_number(),
            ),
        )
        employes.append((eid, sid, cat))
        eid += 1
    # (eid-1 = nombre total d'employés ; non stocké car non réutilisé)

    all_medecins = [e for e, s, c in employes if c == "Medical"]

    # contrats
    cid = 1
    for e, _sid, cat in employes:
        typ = random.choice(["CDI"] * 6 + ["CDD", "CDD", "Vacation", "Interim"])
        etp = random.choice([1.0, 1.0, 1.0, 0.8, 0.5])
        base = {
            "Medical": (5500, 12000),
            "Paramedical": (2100, 3400),
            "Administratif": (2300, 5200),
        }[cat]
        salaire = round(random.uniform(*base) * etp, 2)
        date_fin = None if typ == "CDI" else d(TODAY, 30, 400)
        cur.execute(
            "INSERT INTO contrats VALUES (?,?,?,?,?,?,?)",
            (cid, e, typ, d(TODAY, -2500, -30), date_fin, etp, salaire),
        )
        cid += 1

    # absences
    aid = 1
    for e, _, _ in employes:
        for _ in range(random.randint(0, 4)):
            nb = random.randint(1, 15)
            deb = TODAY + dt.timedelta(days=random.randint(-330, 60))
            cur.execute(
                "INSERT INTO absences VALUES (?,?,?,?,?,?)",
                (
                    aid,
                    e,
                    random.choice(["Congés payés", "Maladie", "Formation", "RTT"]),
                    deb.isoformat(),
                    (deb + dt.timedelta(days=nb)).isoformat(),
                    nb,
                ),
            )
            aid += 1

    # formations
    fid = 1
    fmt_titres = [
        "Prise en charge de la douleur",
        "Nouveaux protocoles d'immunothérapie",
        "Radioprotection",
        "Hygiène hospitalière",
        "Gestion des cytotoxiques",
        "Communication soignant-patient",
        "Bonnes pratiques cliniques (BPC)",
    ]
    for e, _, _ in employes:
        for _ in range(random.randint(0, 3)):
            cur.execute(
                "INSERT INTO formations VALUES (?,?,?,?,?,?,?)",
                (
                    fid,
                    e,
                    random.choice(fmt_titres),
                    random.choice(["ANFH", "Institut interne", "Université", "SFRO"]),
                    d(TODAY, -700, 0),
                    random.choice([7, 14, 21, 35]),
                    round(random.uniform(0, 2500), 2),
                ),
            )
            fid += 1

    # ---- essais cliniques ----------------------------------------------- #
    essai_titres = [
        ("Immunothérapie néoadjuvante dans le cancer du sein triple négatif", "II", "Sein"),
        ("Association chimio-immunothérapie du cancer bronchique", "III", "Poumon"),
        ("Thérapie ciblée dans le mélanome métastatique BRAF+", "II", "Mélanome"),
        ("Anti-VEGF dans le cancer colorectal avancé", "III", "Côlon"),
        ("CAR-T cells dans le lymphome réfractaire", "I", "Lymphome"),
        ("Hormonothérapie prolongée du cancer de la prostate", "III", "Prostate"),
        ("Radiothérapie stéréotaxique du cancer du pancréas", "II", "Pancréas"),
    ]
    for i, (titre, phase, loc) in enumerate(essai_titres, 1):
        ouv = TODAY + dt.timedelta(days=random.randint(-800, -100))
        clos = None
        statut = random.choice(["Ouvert", "Ouvert", "Clos", "Suspendu"])
        if statut == "Clos":
            clos = (ouv + dt.timedelta(days=random.randint(200, 700))).isoformat()
        cur.execute(
            "INSERT INTO essais_cliniques VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                i,
                f"ECD-{2024 + i % 3}-{i:03d}",
                titre,
                phase,
                random.choice(["Institut national du cancer", "Roche", "MSD", "AstraZeneca"]),
                loc,
                ouv.isoformat(),
                clos,
                random.randint(20, 120),
                statut,
            ),
        )
    essai_loc = {i: loc for i, (_, _, loc) in enumerate(essai_titres, 1)}

    # ---- patients + parcours de soins ----------------------------------- #
    N_PATIENTS = 600
    pid = did = tid = cure_id = sr_id = chir_id = 1
    ex_id = bio_id = lab_id = sej_id = cons_id = 1
    fact_id = lf_id = pay_id = incl_id = 1

    for pid in range(1, N_PATIENTS + 1):
        sexe = random.choice(["M", "F"])
        nom = fake.last_name()
        prenom = fake.first_name_male() if sexe == "M" else fake.first_name_female()
        naiss = fake.date_of_birth(minimum_age=28, maximum_age=88)
        premiere = TODAY + dt.timedelta(days=random.randint(-1400, -20))
        referent = random.choice(all_medecins)
        statut_vital = random.choices(["Vivant", "En rémission", "Décédé"], [0.6, 0.28, 0.12])[0]
        ville = fake.city()
        cur.execute(
            "INSERT INTO patients VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                pid,
                f"DOS{pid:06d}",
                nom,
                prenom,
                sexe,
                naiss.isoformat(),
                random.choice(["A+", "A-", "B+", "B-", "O+", "O-", "AB+", "AB-"]),
                ville,
                fake.postcode(),
                fake.phone_number(),
                premiere.isoformat(),
                referent,
                statut_vital,
            ),
        )

        # diagnostic principal (respect du sexe pour cancers spécifiques)
        cand = [
            c
            for c in CANCERS
            if not (c[0] in ("Prostate",) and sexe == "F")
            and not (
                c[0] in ("Ovaire", "Col de l'utérus", "Sein")
                and sexe == "M"
                and random.random() > 0.01
            )
        ]
        loc, cim, lib = random.choice(cand)
        t = random.randint(1, 4)
        n = random.randint(0, 3)
        m = random.randint(0, 1)
        stade_global = random.choices(GRADES_STAGE, [0.25, 0.3, 0.28, 0.17])[0]
        med_diag = random.choice(all_medecins)
        date_diag = premiere + dt.timedelta(days=random.randint(0, 30))
        cur.execute(
            "INSERT INTO diagnostics VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                did,
                pid,
                loc,
                cim,
                lib,
                date_diag.isoformat(),
                f"T{t}N{n}M{m}",
                stade_global,
                random.choice(["Bas grade", "Grade intermédiaire", "Haut grade"]),
                med_diag,
            ),
        )
        this_diag = did
        did += 1

        # biopsie diagnostique
        cur.execute(
            "INSERT INTO biopsies VALUES (?,?,?,?,?,?,?)",
            (
                bio_id,
                pid,
                date_diag.isoformat(),
                loc,
                random.choice(
                    [
                        "Adénocarcinome",
                        "Carcinome épidermoïde",
                        "Carcinome canalaire",
                        "Sarcome",
                        "Carcinome à cellules claires",
                    ]
                ),
                "Malin",
                random.choice(medecins_by_service[service_by_code["ANAPATH"]]),
            ),
        )
        bio_id += 1

        # traitements selon le stade
        types_trt = []
        if stade_global in ("I", "II"):
            types_trt = random.sample(
                ["Chirurgie", "Radiothérapie", "Chimiothérapie"], k=random.randint(1, 2)
            )
        elif stade_global == "III":
            types_trt = ["Chimiothérapie", "Radiothérapie"] + random.sample(
                ["Chirurgie", "Immunothérapie"], k=1
            )
        else:
            types_trt = random.sample(
                ["Chimiothérapie", "Immunothérapie", "Hormonothérapie"], k=random.randint(1, 3)
            )

        for typ in types_trt:
            intention = random.choice(["Curative", "Adjuvante", "Néoadjuvante", "Palliative"])
            deb = date_diag + dt.timedelta(days=random.randint(10, 60))
            fin = deb + dt.timedelta(days=random.randint(30, 240))
            med = random.choice(all_medecins)
            cur.execute(
                "INSERT INTO traitements VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    tid,
                    pid,
                    this_diag,
                    typ,
                    "Protocole "
                    + random.choice(
                        ["FOLFOX", "AC-T", "FEC", "R-CHOP", "Carbo-Taxol", "FOLFIRINOX"]
                    ),
                    deb.isoformat(),
                    fin.isoformat(),
                    intention,
                    med,
                ),
            )
            this_trt = tid
            tid += 1

            if typ in ("Chimiothérapie", "Immunothérapie"):
                n_cures = random.randint(3, 8)
                for k in range(1, n_cures + 1):
                    med_id = random.randint(1, n_med)
                    sc = round(random.uniform(1.5, 2.1), 2)
                    cur.execute(
                        "INSERT INTO cures_chimio VALUES (?,?,?,?,?,?,?,?,?)",
                        (
                            cure_id,
                            this_trt,
                            pid,
                            k,
                            (deb + dt.timedelta(days=21 * (k - 1))).isoformat(),
                            med_id,
                            round(random.uniform(50, 900), 1),
                            sc,
                            random.choice(
                                [
                                    "Aucun",
                                    "Nausées",
                                    "Fatigue",
                                    "Neutropénie",
                                    "Alopécie",
                                    "Neuropathie",
                                    "Mucite",
                                ]
                            ),
                        ),
                    )
                    cure_id += 1

            if typ == "Radiothérapie":
                rt_equips = [i for i, e in enumerate(EQUIPEMENTS, 1) if e[1] == "Radiothérapie"]
                n_seances = random.randint(15, 33)
                for k in range(1, n_seances + 1):
                    cur.execute(
                        "INSERT INTO seances_radio VALUES (?,?,?,?,?,?,?,?)",
                        (
                            sr_id,
                            this_trt,
                            pid,
                            random.choice(rt_equips),
                            (deb + dt.timedelta(days=k)).isoformat(),
                            round(random.uniform(1.8, 2.5), 2),
                            loc,
                            k,
                        ),
                    )
                    sr_id += 1

            if typ == "Chirurgie":
                chir = random.choice(medecins_by_service[service_by_code["CHIR"]])
                cur.execute(
                    "INSERT INTO chirurgies VALUES (?,?,?,?,?,?,?,?,?)",
                    (
                        chir_id,
                        pid,
                        this_trt,
                        chir,
                        deb.isoformat(),
                        f"Exérèse tumorale ({loc})",
                        random.randint(45, 420),
                        f"Bloc {random.randint(1, 6)}",
                        random.choice(["Aucune", "Aucune", "Aucune", "Saignement", "Infection"]),
                    ),
                )
                chir_id += 1

        # examens d'imagerie de suivi
        img_equips = [i for i, e in enumerate(EQUIPEMENTS, 1) if e[1] == "Imagerie"]
        for _ in range(random.randint(1, 5)):
            cur.execute(
                "INSERT INTO examens_imagerie VALUES (?,?,?,?,?,?,?,?)",
                (
                    ex_id,
                    pid,
                    random.choice(img_equips),
                    random.choice(["Scanner", "IRM", "TEP", "Mammographie", "Échographie"]),
                    d(date_diag, 10, 500),
                    random.choice(["Poumon", "Abdomen", "Pelvis", "Cerveau", "Corps entier"]),
                    random.choice(
                        ["Réponse complète", "Réponse partielle", "Stabilité", "Progression"]
                    ),
                    random.choice(medecins_by_service[service_by_code["IMG"]]),
                ),
            )
            ex_id += 1

        # résultats de labo
        for _ in range(random.randint(2, 8)):
            analyte = random.choice(
                [
                    "Hémoglobine",
                    "Leucocytes",
                    "Plaquettes",
                    "Créatinine",
                    "CRP",
                    "Marqueur CA 15-3",
                    "Marqueur ACE",
                    "Marqueur PSA",
                ]
            )
            val = round(random.uniform(0.5, 350), 2)
            cur.execute(
                "INSERT INTO resultats_labo VALUES (?,?,?,?,?,?,?)",
                (
                    lab_id,
                    pid,
                    d(date_diag, 0, 500),
                    analyte,
                    val,
                    random.choice(["g/dL", "10^9/L", "mg/L", "µmol/L", "U/mL"]),
                    random.choice([0, 0, 0, 1]),
                ),
            )
            lab_id += 1

        # séjours
        for _ in range(random.randint(1, 4)):
            sid = random.randint(1, len(SERVICES))
            ent = premiere + dt.timedelta(days=random.randint(0, 500))
            typ = random.choice(["Hospitalisation", "Hôpital de jour", "Ambulatoire"])
            dur = random.randint(0, 12) if typ == "Hospitalisation" else 0
            cur.execute(
                "INSERT INTO sejours VALUES (?,?,?,?,?,?,?)",
                (
                    sej_id,
                    pid,
                    sid,
                    typ,
                    ent.isoformat(),
                    (ent + dt.timedelta(days=dur)).isoformat(),
                    random.choice(
                        [
                            "Cure de chimiothérapie",
                            "Bilan d'extension",
                            "Surveillance",
                            "Complication",
                            "Chirurgie programmée",
                        ]
                    ),
                ),
            )
            sej_id += 1

        # consultations
        for _ in range(random.randint(2, 9)):
            cur.execute(
                "INSERT INTO consultations VALUES (?,?,?,?,?,?,?)",
                (
                    cons_id,
                    pid,
                    random.choice(all_medecins),
                    random.randint(1, len(SERVICES)),
                    d(premiere, 0, 700),
                    random.choice(
                        [
                            "Consultation de suivi",
                            "Annonce diagnostique",
                            "Adaptation thérapeutique",
                            "Consultation douleur",
                            "Consultation post-opératoire",
                        ]
                    ),
                    random.choice(
                        [
                            "Évolution favorable",
                            "Stabilité clinique",
                            "À revoir dans 1 mois",
                            "Bon état général",
                        ]
                    ),
                ),
            )
            cons_id += 1

        # inclusion essai clinique éventuelle (si un essai correspond à la localisation)
        matching = [i for i, eloc in essai_loc.items() if eloc == loc]
        if matching and random.random() < 0.18:
            cur.execute(
                "INSERT INTO inclusions_essai VALUES (?,?,?,?,?,?)",
                (
                    incl_id,
                    random.choice(matching),
                    pid,
                    d(date_diag, 10, 120),
                    random.choice(["Bras A (traitement)", "Bras B (contrôle)"]),
                    random.choice(["En cours", "Sorti", "Terminé"]),
                ),
            )
            incl_id += 1

        # facturation
        n_fact = random.randint(1, 4)
        for _ in range(n_fact):
            emis = premiere + dt.timedelta(days=random.randint(5, 700))
            n_lignes = random.randint(1, 5)
            total = 0.0
            lignes = []
            for _ in range(n_lignes):
                acte_id = random.randint(1, len(ACTES))
                tarif = ACTES[acte_id - 1][2]
                q = random.randint(1, 6)
                montant = round(tarif * q, 2)
                total += montant
                lignes.append((acte_id, q, montant))
            secu = round(total * random.uniform(0.6, 0.8), 2)
            mut = round(total * random.uniform(0.1, 0.3), 2)
            rac = round(max(total - secu - mut, 0), 2)
            statut = random.choices(
                ["Payée", "En attente", "Partielle", "Impayée"], [0.6, 0.2, 0.12, 0.08]
            )[0]
            cur.execute(
                "INSERT INTO factures VALUES (?,?,?,?,?,?,?,?)",
                (fact_id, pid, emis.isoformat(), round(total, 2), secu, mut, rac, statut),
            )
            for acte_id, q, montant in lignes:
                cur.execute(
                    "INSERT INTO lignes_facture VALUES (?,?,?,?,?)",
                    (lf_id, fact_id, acte_id, q, montant),
                )
                lf_id += 1
            if statut in ("Payée", "Partielle"):
                paye = total if statut == "Payée" else round(total * random.uniform(0.3, 0.7), 2)
                cur.execute(
                    "INSERT INTO paiements VALUES (?,?,?,?,?)",
                    (
                        pay_id,
                        fact_id,
                        d(emis, 5, 90),
                        round(paye, 2),
                        random.choice(["Sécurité sociale", "Mutuelle", "CB", "Chèque"]),
                    ),
                )
                pay_id += 1
            fact_id += 1

    # ---- commandes fournisseurs ----------------------------------------- #
    com_id = lc_id = 1
    for _ in range(150):
        four = random.randint(1, n_four)
        date_com = TODAY + dt.timedelta(days=random.randint(-400, -1))
        statut = random.choices(["Livrée", "Commandée", "Annulée"], [0.7, 0.2, 0.1])[0]
        livr = (
            (date_com + dt.timedelta(days=random.randint(2, 30))).isoformat()
            if statut == "Livrée"
            else None
        )
        n_lignes = random.randint(1, 5)
        total = 0.0
        lignes = []
        for _ in range(n_lignes):
            q = random.randint(1, 100)
            pu = round(random.uniform(5, 3500), 2)
            montant = round(q * pu, 2)
            total += montant
            lignes.append((f"Réf-{random.randint(1000, 9999)}", q, pu, montant))
        cur.execute(
            "INSERT INTO commandes VALUES (?,?,?,?,?,?,?)",
            (
                com_id,
                four,
                random.randint(1, len(SERVICES)),
                date_com.isoformat(),
                livr,
                statut,
                round(total, 2),
            ),
        )
        for des, q, pu, montant in lignes:
            cur.execute(
                "INSERT INTO lignes_commande VALUES (?,?,?,?,?,?)",
                (lc_id, com_id, des, q, pu, montant),
            )
            lc_id += 1
        com_id += 1

    con.commit()

    # ---- récap ----------------------------------------------------------- #
    tables = [
        r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    ]
    # On agrège le récapitulatif dans un seul message multi-lignes plutôt que
    # d'émettre un log par table : plus lisible en sortie CLI.
    lines = [f"Base créée : {out_path}"]
    total_rows = 0
    for t in tables:
        n = cur.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        total_rows += n
        lines.append(f"  {t:<20} {n:>7} lignes")
    lines.append(f"  {'TOTAL':<20} {total_rows:>7} lignes  ({len(tables)} tables)")
    logger.info("\n".join(lines))
    con.close()


def main() -> int:
    """Parse CLI arguments and run the database build."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/institut.db")
    args = ap.parse_args()
    build(Path(args.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
