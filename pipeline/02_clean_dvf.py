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
from pipeline.lib.clean_dvf import process_rows  # noqa: E402

DATA_RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"
DATA_PROCESSED_DIR = Path(__file__).resolve().parent.parent / "data" / "processed"
RAW_GLOB = str(DATA_RAW_DIR / "dvf_brut_*.parquet").replace("\\", "/")
OUTPUT_PATH = DATA_PROCESSED_DIR / "dvf_clean.parquet"

# "Code commune" n'est PAS zero-pad sur 3 chiffres dans le brut DGFiP (ex. Anglet
# '24', pas '024') -- voir pipeline/download_dvf.py. Sans LPAD, la concatenation ne
# matche jamais les codes INSEE < 100 de config/communes.py.
_RAW_SELECT_QUERY = """
    SELECT
        "Identifiant de document" AS identifiant_document,
        "No disposition" AS no_disposition,
        CAST(strptime("Date mutation", '%d/%m/%Y') AS DATE) AS date_mutation,
        "Nature mutation" AS nature_mutation,
        "Valeur fonciere" AS valeur_fonciere,
        "No voie" AS no_voie,
        "B/T/Q" AS btq,
        "Type de voie" AS type_voie,
        "Voie" AS voie,
        "Code postal" AS code_postal,
        "Commune" AS commune,
        "Code departement" || LPAD("Code commune", 3, '0') AS code_insee,
        "Type local" AS type_local,
        "Nombre pieces principales" AS nombre_pieces_principales,
        "Surface reelle bati" AS surface_reelle_bati
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


def load_raw_rows(con: duckdb.DuckDBPyConnection, codes_insee: list[str]) -> list[dict]:
    """Charge les lignes DVF brutes des communes ciblees depuis data/raw/ (un dict
    par ligne, colonnes nommees -- voir les alias de `_RAW_SELECT_QUERY`)."""
    codes_list = ", ".join(f"'{c}'" for c in codes_insee)
    query = _RAW_SELECT_QUERY.format(codes_list=codes_list)
    result = con.execute(query, [RAW_GLOB])
    names = [d[0] for d in result.description]
    return [dict(zip(names, row, strict=True)) for row in result.fetchall()]


def write_output(con: duckdb.DuckDBPyConnection, kept_rows: list[dict], output_path: Path) -> None:
    """Ecrit les lignes retenues en parquet (ecrase toute sortie precedente).

    N'utilise PAS pipeline.lib.parquet_io.write_parquet_rows (contrairement a 02b/03,
    #22) : ce chemin ecrit via une table typee CREATE TABLE + executemany, en
    conservant `date_mutation` en type DATE natif dans dvf_clean.parquet. parquet_io
    serialise en JSONL et ramenerait la colonne en texte -- changement du format de
    sortie, hors scope de #22. Les dict de `process_rows` sont convertis en tuples
    dans l'ordre de `_OUTPUT_COLUMNS` pour l'executemany.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    columns_sql = ", ".join(f'"{name}" {dtype}' for name, dtype in _OUTPUT_COLUMNS)
    con.execute("CREATE OR REPLACE TABLE dvf_clean (" + columns_sql + ")")

    placeholders = ", ".join("?" for _ in _OUTPUT_COLUMNS)
    tuples = [tuple(row[name] for name, _ in _OUTPUT_COLUMNS) for row in kept_rows]
    con.executemany(f"INSERT INTO dvf_clean VALUES ({placeholders})", tuples)

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

    kept_rows, exclusions = process_rows(raw_rows)
    write_output(con, kept_rows, OUTPUT_PATH)

    rows_out = len(kept_rows)
    rows_excluded = rows_in - rows_out

    print("\n=== Resume nettoyage DVF (data/processed/dvf_clean.parquet) ===")
    print(f"  Lignes en entree      : {rows_in}")
    print(f"  Lignes en sortie      : {rows_out}")
    print(f"  Lignes exclues        : {rows_excluded}")
    print(f"    dont prix nul/manquant     : {exclusions.excluded_zero_price}")
    print(
        "    dont surface nulle/manquante (apres exclusion prix) : "
        f"{exclusions.excluded_zero_surface}"
    )
    if rows_in:
        print(f"  Taux de conservation  : {rows_out / rows_in:.1%}")

    if kept_rows:
        by_commune = Counter(row["commune"] for row in kept_rows)
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
