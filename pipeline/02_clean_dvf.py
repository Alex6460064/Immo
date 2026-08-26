"""Nettoie le DVF brut DGFiP (data/raw/dvf_brut_*.parquet) et ecrit un parquet propre.

Etapes :
1. Relit tous les millesimes DVF brut deja telecharges (pipeline/download_dvf.py) et
   refiltre sur les 16 communes ciblees (config/communes.py) -- defense en profondeur,
   le telechargement filtre deja par code INSEE, mais le filtrage est refait ici pour
   respecter les criteres d'acceptation de ce ticket independamment de l'etape amont.
2. Compose l'adresse a partir des colonnes DGFiP ("No voie", "B/T/Q", "Type de voie",
   "Voie") et la normalise via normalize_address (T2) -- voir pipeline/lib/clean_dvf.py.
3. Parse "Valeur fonciere" (decimal virgule francais) et "Surface reelle bati" (choix
   documente dans pipeline/lib/clean_dvf.py -- pas la surface Carrez).
4. Classe chaque ligne kept / excluded_zero_price / excluded_zero_surface -- les
   lignes exclues sont comptees et loggees, jamais silencieusement supprimees
   (CLAUDE.md). Une mutation DVF peut correspondre a plusieurs lignes brutes
   (une par disposition/lot) : ce script ne deduplique/agrege pas, il nettoie a la
   granularite de la ligne brute -- voir pipeline/lib/clean_dvf.py.

Ne charge jamais pandas/numpy (non installes, voir pyproject.toml -- create_function
de DuckDB necessite numpy, donc le nettoyage ligne a ligne se fait en Python pur via
fetchall()/executemany(), pas via UDF DuckDB).

Idempotent : rejouable independamment, ecrase le parquet de sortie a chaque execution
(pas de fusion incrementale -- le nettoyage est deterministe sur les memes bruts).

Usage :
    uv run python pipeline/02_clean_dvf.py
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

import duckdb

# Execution en script direct (`python pipeline/02_clean_dvf.py` depuis la racine, voir
# WORKFLOW de CLAUDE.md) : la racine du repo n'est pas automatiquement sur sys.path.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.communes import get_codes_insee  # noqa: E402
from pipeline.lib.clean_dvf import (  # noqa: E402
    EXCLUDED_ZERO_PRICE,
    EXCLUDED_ZERO_SURFACE,
    KEPT,
    classify_row,
    compose_address,
    parse_french_decimal,
)
from pipeline.lib.normalize_address import normalize_address  # noqa: E402

DATA_RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"
DATA_PROCESSED_DIR = Path(__file__).resolve().parent.parent / "data" / "processed"
RAW_GLOB = str(DATA_RAW_DIR / "dvf_brut_*.parquet").replace("\\", "/")
OUTPUT_PATH = DATA_PROCESSED_DIR / "dvf_clean.parquet"

# "Code commune" n'est PAS zero-pad sur 3 chiffres dans le brut DGFiP (ex. Anglet
# '24', pas '024') -- voir pipeline/download_dvf.py. Sans LPAD, la concatenation ne
# matche jamais les codes INSEE < 100 de config/communes.py.
_RAW_SELECT_QUERY = """
    SELECT
        "Identifiant de document",
        "No disposition",
        CAST(strptime("Date mutation", '%d/%m/%Y') AS DATE),
        "Nature mutation",
        "Valeur fonciere",
        "No voie",
        "B/T/Q",
        "Type de voie",
        "Voie",
        "Code postal",
        "Commune",
        "Code departement" || LPAD("Code commune", 3, '0') AS code_insee,
        "Type local",
        "Nombre pieces principales",
        "Surface reelle bati"
    FROM read_parquet(?)
    WHERE "Code departement" || LPAD("Code commune", 3, '0') IN ({codes_list})
"""

_OUTPUT_COLUMNS = [
    ("identifiant_document", "VARCHAR"),
    ("no_disposition", "VARCHAR"),
    ("date_mutation", "DATE"),
    ("nature_mutation", "VARCHAR"),
    ("code_insee", "VARCHAR"),
    ("commune", "VARCHAR"),
    ("code_postal", "VARCHAR"),
    ("adresse_brute", "VARCHAR"),
    ("adresse_normalisee", "VARCHAR"),
    ("type_local", "VARCHAR"),
    ("nombre_pieces_principales", "VARCHAR"),
    ("surface", "DOUBLE"),
    ("prix", "DOUBLE"),
]


def load_raw_rows(con: duckdb.DuckDBPyConnection, codes_insee: list[str]) -> list[tuple]:
    """Charge les lignes DVF brutes des communes ciblees depuis data/raw/."""
    codes_list = ", ".join(f"'{c}'" for c in codes_insee)
    query = _RAW_SELECT_QUERY.format(codes_list=codes_list)
    return con.execute(query, [RAW_GLOB]).fetchall()


def clean_rows(raw_rows: list[tuple]) -> tuple[list[tuple], dict[str, int]]:
    """Compose/normalise l'adresse, parse prix/surface, classe chaque ligne brute.

    Retourne (lignes retenues au format table de sortie, compteur par classification).
    Les lignes exclues ne sont pas retournees mais sont comptees -- voir le resume
    imprime par main() pour qu'elles restent visibles (jamais silencieusement supprimees).
    """
    kept: list[tuple] = []
    counts: dict[str, int] = {KEPT: 0, EXCLUDED_ZERO_PRICE: 0, EXCLUDED_ZERO_SURFACE: 0}

    for row in raw_rows:
        (
            identifiant_document,
            no_disposition,
            date_mutation,
            nature_mutation,
            valeur_fonciere,
            no_voie,
            btq,
            type_voie,
            voie,
            code_postal,
            commune,
            code_insee,
            type_local,
            nombre_pieces_principales,
            surface_reelle_bati,
        ) = row

        prix = parse_french_decimal(valeur_fonciere)
        surface = parse_french_decimal(surface_reelle_bati)
        classification = classify_row(prix, surface)
        counts[classification] += 1

        if classification != KEPT:
            continue

        adresse_brute = compose_address(no_voie, btq, type_voie, voie)
        adresse_normalisee = normalize_address(adresse_brute)

        kept.append(
            (
                identifiant_document,
                no_disposition,
                date_mutation,
                nature_mutation,
                code_insee,
                commune,
                code_postal,
                adresse_brute,
                adresse_normalisee,
                type_local,
                nombre_pieces_principales,
                surface,
                prix,
            )
        )

    return kept, counts


def write_output(con: duckdb.DuckDBPyConnection, kept_rows: list[tuple], output_path: Path) -> None:
    """Ecrit les lignes retenues en parquet (ecrase toute sortie precedente)."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    columns_sql = ", ".join(f'"{name}" {dtype}' for name, dtype in _OUTPUT_COLUMNS)
    con.execute("CREATE OR REPLACE TABLE dvf_clean (" + columns_sql + ")")

    placeholders = ", ".join("?" for _ in _OUTPUT_COLUMNS)
    con.executemany(f"INSERT INTO dvf_clean VALUES ({placeholders})", kept_rows)

    literal = str(output_path).replace("\\", "/").replace("'", "''")
    con.execute(f"COPY dvf_clean TO '{literal}' (FORMAT PARQUET)")


def main() -> None:
    codes_insee = get_codes_insee()
    print(f"Communes ciblees ({len(codes_insee)}) : {', '.join(codes_insee)}")

    if not any(DATA_RAW_DIR.glob("dvf_brut_*.parquet")):
        print(
            f"ERREUR : aucun fichier dvf_brut_*.parquet dans {DATA_RAW_DIR} -- "
            "lancer pipeline/download_dvf.py d'abord.",
            file=sys.stderr,
        )
        sys.exit(1)

    con = duckdb.connect()
    raw_rows = load_raw_rows(con, codes_insee)
    rows_in = len(raw_rows)
    print(f"Lignes DVF brutes chargees (communes ciblees, tous millesimes) : {rows_in}")

    kept_rows, counts = clean_rows(raw_rows)
    write_output(con, kept_rows, OUTPUT_PATH)

    rows_out = counts[KEPT]
    rows_excluded = rows_in - rows_out

    print("\n=== Resume nettoyage DVF (data/processed/dvf_clean.parquet) ===")
    print(f"  Lignes en entree      : {rows_in}")
    print(f"  Lignes en sortie      : {rows_out}")
    print(f"  Lignes exclues        : {rows_excluded}")
    print(f"    dont prix nul/manquant     : {counts[EXCLUDED_ZERO_PRICE]}")
    print(
        f"    dont surface nulle/manquante (apres exclusion prix) : "
        f"{counts[EXCLUDED_ZERO_SURFACE]}"
    )
    if rows_in:
        print(f"  Taux de conservation  : {rows_out / rows_in:.1%}")

    if kept_rows:
        by_commune = Counter(row[5] for row in kept_rows)  # index 5 = commune
        print("\n  Repartition des lignes retenues par commune :")
        for commune, count in sorted(by_commune.items(), key=lambda kv: -kv[1]):
            print(f"    {commune:<25} {count:>6}")

    print(f"\n  Fichier ecrit : {OUTPUT_PATH}")

    if rows_out == 0:
        print(
            "ATTENTION : 0 ligne retenue -- verifier le filtrage ou le format source.",
            file=sys.stderr,
        )


if __name__ == "__main__":
    main()
