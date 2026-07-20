"""widen_db.py — Fabrique une variante « gros schéma » de la base hôpital.

Pourquoi ? Pour démontrer, chiffres à l'appui, le point central de PROS_CONS :
**un schéma qui tient dans le prompt vs un schéma qui n'y tient plus**.

  - LIGHT = la base actuelle ``data/institut.db`` (30 tables, DDL ~7 500 car.,
    tient entièrement dans le prompt d'un modèle de code local).
  - HEAVY = les MÊMES tables, MÊMES colonnes-clés et MÊMES données, mais chaque
    table est gonflée de ~130 colonnes de **décor** (champs admin/RGPD/legacy
    réalistes, laissés à NULL). Le DDL explose (~150k car.) et ne tient plus
    confortablement dans le contexte d'un petit LLM.

Effet attendu — l'**inversion du classement** : QwenCoder, qui colle le schéma
complet dans le prompt, décroche et ralentit sur HEAVY ; Vanna (RAG), qui ne
récupère que les morceaux pertinents, tient. Le RAG passe alors devant.

Seule la TAILLE du schéma vu par le LLM change : les colonnes de décor sont NULL
(leurs valeurs n'importent pas), et toutes les colonnes/données d'origine sont
conservées → le SQL de référence du benchmark s'exécute encore à l'identique.

Usage :
    python -m backend.widen_db                              # 130 décoys/table
    python -m backend.widen_db --per-table 150 --out data/institut_wide.db
"""

from __future__ import annotations

import argparse
import logging
import shutil
import sqlite3
from pathlib import Path

from . import db

# Logger de module : on proscrit `print` (cf. CODING.md §6). Le point d'entrée
# `__main__` configure un handler console pour rester bavard en CLI.
logger = logging.getLogger(__name__)

# Base HEAVY par défaut, à côté de la base LIGHT d'origine.
WIDE_DB_PATH = db.DB_PATH.parent / "institut_wide.db"

# Familles de colonnes de décor : des champs qu'on trouve VRAIMENT dans les
# systèmes hospitaliers/administratifs (audit, RGPD, reprises de données legacy,
# annotations de secrétariat…). Réalistes exprès : le LLM ne doit pas pouvoir les
# écarter d'un coup d'œil ; elles noient le schéma utile comme dans la vraie vie.
_DECOY_TEMPLATES: list[tuple[str, str]] = [
    ("date_derniere_modification", "TEXT"),
    ("date_creation_enregistrement", "TEXT"),
    ("date_archivage", "TEXT"),
    ("date_derniere_synchro", "TEXT"),
    ("utilisateur_creation", "TEXT"),
    ("utilisateur_modification", "TEXT"),
    ("service_saisie", "TEXT"),
    ("poste_de_travail", "TEXT"),
    ("flag_archive", "INTEGER"),
    ("flag_anonymise", "INTEGER"),
    ("flag_consentement_rgpd", "INTEGER"),
    ("flag_doublon_potentiel", "INTEGER"),
    ("flag_a_verifier", "INTEGER"),
    ("champ_libre", "TEXT"),
    ("commentaire_interne", "TEXT"),
    ("note_administrative", "TEXT"),
    ("observation_secretariat", "TEXT"),
    ("code_interne", "TEXT"),
    ("reference_externe", "TEXT"),
    ("identifiant_legacy", "TEXT"),
    ("numero_dossier_papier", "TEXT"),
    ("code_facturation_interne", "TEXT"),
    ("categorie_analytique", "TEXT"),
    ("libelle_complementaire", "TEXT"),
    ("statut_synchronisation", "TEXT"),
    ("indicateur_qualite_donnee", "REAL"),
    ("score_completude", "REAL"),
    ("taux_remplissage", "REAL"),
    ("version_schema_source", "INTEGER"),
    ("checksum_ligne", "TEXT"),
]


def _decoy_columns(n: int, existing: set[str]) -> list[tuple[str, str]]:
    """Fabrique ``n`` colonnes de décor uniques (nom, type SQL).

    On cycle sur :data:`_DECOY_TEMPLATES` en suffixant le nom par le numéro de
    tour (``_2``, ``_3``…) pour garantir l'unicité tout en gardant des noms
    plausibles (ex. ``date_archivage_3``). On saute tout nom déjà présent dans
    la table pour ne jamais entrer en collision avec une colonne d'origine.

    Parameters
    ----------
    n : int
        Nombre de colonnes de décor voulues.
    existing : set[str]
        Noms des colonnes déjà présentes dans la table (à ne pas réutiliser).

    Returns
    -------
    list[tuple[str, str]]
        Liste de ``(nom_colonne, type_sql)`` de longueur ``n``.
    """
    out: list[tuple[str, str]] = []
    taken = set(existing)
    cycle = 0
    # On empile des tours de la palette de templates jusqu'à atteindre ``n``.
    while len(out) < n:
        for base, sqltype in _DECOY_TEMPLATES:
            name = base if cycle == 0 else f"{base}_{cycle + 1}"
            if name not in taken:
                out.append((name, sqltype))
                taken.add(name)
                if len(out) >= n:
                    break
        cycle += 1
    return out


def widen_db(
    src: Path | str = db.DB_PATH,
    dst: Path | str = WIDE_DB_PATH,
    per_table: int = 130,
) -> Path:
    """Copie la base LIGHT et gonfle chaque table de colonnes de décor NULL.

    Parameters
    ----------
    src : pathlib.Path | str
        Base d'origine (LIGHT) à copier — inchangée.
    dst : pathlib.Path | str
        Base HEAVY à produire (écrasée si elle existe).
    per_table : int
        Nombre de colonnes de décor ajoutées à CHAQUE table utilisateur.

    Returns
    -------
    pathlib.Path
        Le chemin de la base HEAVY produite.
    """
    src_path, dst_path = Path(src), Path(dst)
    # Copie binaire : on part d'une réplique exacte, données comprises, puis on
    # n'ajoute QUE des colonnes (jamais de suppression) → les refs restent valides.
    shutil.copyfile(src_path, dst_path)

    con = sqlite3.connect(dst_path)
    try:
        tables = [
            r[0]
            for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        ]
        total_added = 0
        for table in tables:
            existing = {r[1] for r in con.execute(f"PRAGMA table_info('{table}')")}
            for name, sqltype in _decoy_columns(per_table, existing):
                # ADD COLUMN sans DEFAULT : purement métadonnée (instantané), la
                # colonne vaut NULL partout. Ce qui compte, c'est la TAILLE du DDL
                # que verra le LLM, pas les valeurs.
                con.execute(f'ALTER TABLE "{table}" ADD COLUMN "{name}" {sqltype}')
                total_added += 1
            logger.info("Table %-24s +%d colonnes de décor", table, per_table)
        con.commit()
    finally:
        con.close()

    # Mesure de contrôle : la taille du DDL est l'enjeu de la démo LIGHT vs HEAVY.
    ddl_chars = len(db.schema_ddl(dst_path))
    logger.info(
        "Base HEAVY écrite : %s — %d tables, +%d colonnes, DDL ≈ %d caractères",
        dst_path,
        len(tables),
        total_added,
        ddl_chars,
    )
    return dst_path


def main() -> int:
    """Point d'entrée CLI : produit la base HEAVY et journalise ses dimensions.

    Returns
    -------
    int
        Code de sortie (0).
    """
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(
        description="Fabrique une variante « gros schéma » (HEAVY) de la base hôpital."
    )
    parser.add_argument("--src", default=str(db.DB_PATH), help="Base LIGHT source.")
    parser.add_argument("--out", default=str(WIDE_DB_PATH), help="Base HEAVY à produire.")
    parser.add_argument(
        "--per-table", type=int, default=130, help="Colonnes de décor ajoutées par table."
    )
    args = parser.parse_args()
    widen_db(args.src, args.out, per_table=args.per_table)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
