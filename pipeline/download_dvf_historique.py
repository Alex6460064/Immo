"""Telecharge le DVF brut DGFiP historique (millesimes 2016-2020) depuis le miroir
cquest et le filtre sur les communes ciblees.

Voir pipeline/lib/download_dvf_historique.py pour la justification de la source
(miroir communautaire cquest, hors fenetre glissante officielle de data.gouv.fr --
verifie en direct, voir Rechercheavant2021.md) et docs/adr/0005-source-historique-dvf-2016-2020.md
pour la decision.

Meme logique de filtrage/idempotence/nommage que pipeline/download_dvf.py (2021+) :
seules les lignes des communes ciblees (config/communes.py) sont ecrites sur disque,
dans le meme fichier data/raw/dvf_brut_{year}.parquet -- 02_clean_dvf.py absorbe donc
2016-2020 par son glob existant sans aucune modification.

Difference avec le flux officiel : fichiers .txt non compresses (pas de .zip a
extraire) et alias de colonne applique (`Code service CH` -> `Identifiant de
document`, voir pipeline/lib/download_dvf_historique.py) pour matcher le schema
attendu en aval.

Idempotent : un millesime deja telecharge et filtre (fichier present dans
data/raw/) n'est pas retelecharge -- voir should_download().

Usage :
    uv run python pipeline/download_dvf_historique.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.communes import get_codes_insee  # noqa: E402

# _download_with_resume/_write_parquet_literal/summarize_cached_year (prefixe "_" pour
# les deux premiers) sont reutilisees telles quelles depuis pipeline/download_dvf.py --
# ce script ne modifie jamais ce fichier (voir issue #16, "pas de modification"), donc
# la reutilisation passe par import plutot que par extraction vers un module partage.
from pipeline.download_dvf import (  # noqa: E402
    _YEAR_SUMMARY_QUERY,
    _download_with_resume,
    _write_parquet_literal,
    summarize_cached_year,
)
from pipeline.lib.download_dvf_historique import (  # noqa: E402
    alias_historical_columns,
    historical_url_for_year,
    historical_years,
    output_path_for_year,
    require_downstream_columns,
    should_download,
    validate_historical_header,
)

DATA_RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"


def download_and_filter_year(year: int, codes_insee: list[str], data_dir: Path) -> dict:
    """Telecharge le millesime historique `year`, filtre aux communes ciblees, ecrit le parquet.

    Retourne {"year", "rows", "min_date", "max_date"} sur les mutations retenues.
    """
    output_path = output_path_for_year(year, data_dir)
    codes_list = ", ".join(f"'{c}'" for c in codes_insee)
    url = historical_url_for_year(year)

    with tempfile.TemporaryDirectory(prefix=f"dvf_hist_{year}_") as tmp:
        txt_path = Path(tmp) / f"valeursfoncieres-{year}.txt"

        print(f"[{year}] telechargement depuis {url}")
        size = _download_with_resume(url, txt_path)
        print(f"[{year}] {size:,} octets telecharges")

        # Le miroir cquest n'a aucune garantie de disponibilite (ADR 0005) : on
        # verifie que le fichier est bien un DVF pipe-delimite avant de le donner a
        # DuckDB -- sinon echec explicite plutot qu'une binder error opaque.
        with txt_path.open("r", encoding="latin-1") as f:
            validate_historical_header(f.readline())

        con = duckdb.connect()
        txt_path_posix = str(txt_path).replace("\\", "/")

        # Colonnes reelles du fichier source (pas supposees) : alias_historical_columns
        # applique le mapping teste unitairement (pipeline/lib/download_dvf_historique.py)
        # sur le schema constate, plutot que de re-ecrire la correspondance en dur ici.
        raw_columns = [
            row[0]
            for row in con.execute(
                f"DESCRIBE SELECT * FROM read_csv('{txt_path_posix}', delim='|', "
                "header=true, all_varchar=true)"
            ).fetchall()
        ]
        aliased_columns = alias_historical_columns(raw_columns)
        # Drift de schema du miroir (noms de colonnes, delimiteur) -> echec ici,
        # pas un parquet aval vide.
        require_downstream_columns(aliased_columns)
        select_list = ", ".join(
            f'"{raw}" AS "{aliased}"' if raw != aliased else f'"{raw}"'
            for raw, aliased in zip(raw_columns, aliased_columns, strict=True)
        )

        # "Code commune" n'est pas zero-pad sur 3 chiffres dans le brut DGFiP (voir
        # pipeline/download_dvf.py) -- meme correction necessaire ici.
        select_sql = f"""
            SELECT {select_list}
            FROM read_csv('{txt_path_posix}', delim='|', header=true, all_varchar=true)
            WHERE "Code departement" || LPAD("Code commune", 3, '0') IN ({codes_list})
        """
        _write_parquet_literal(con, select_sql, output_path)
        row = con.execute(_YEAR_SUMMARY_QUERY, [str(output_path)]).fetchone()

    return {"year": year, "rows": row[0], "min_date": row[1], "max_date": row[2]}


def main() -> None:
    DATA_RAW_DIR.mkdir(parents=True, exist_ok=True)
    codes_insee = get_codes_insee()
    years = historical_years()

    print(f"Communes ciblees ({len(codes_insee)}) : {', '.join(codes_insee)}")
    print(f"Millesimes historiques cibles (edition cquest avril 2021) : {years}")

    summaries = []
    for year in years:
        if should_download(year, DATA_RAW_DIR):
            summary = download_and_filter_year(year, codes_insee, DATA_RAW_DIR)
        else:
            output_path = output_path_for_year(year, DATA_RAW_DIR)
            print(f"[{year}] deja en cache ({output_path}), telechargement saute")
            summary = summarize_cached_year(year, DATA_RAW_DIR)
        summaries.append(summary)
        print(
            f"[{year}] {summary['rows']} mutations retenues, "
            f"{summary['min_date']} -> {summary['max_date']}"
        )

    total_rows = sum(s["rows"] for s in summaries)
    non_empty = [s for s in summaries if s["rows"]]
    overall_min = min((s["min_date"] for s in non_empty), default=None)
    overall_max = max((s["max_date"] for s in non_empty), default=None)

    print("\n=== Resume telechargement DVF brut historique (communes ciblees, dept. 64 + 40) ===")
    for s in summaries:
        print(f"  {s['year']} : {s['rows']:>6} mutations")
    print(f"  TOTAL : {total_rows} mutations")
    print(
        f"  Plage d'annees reelle detectee (Date mutation, pas de valeur figee a l'avance) : "
        f"{overall_min} -> {overall_max}"
    )
    print(f"  Fichiers en cache : {DATA_RAW_DIR}")

    if total_rows == 0:
        print(
            "ATTENTION : 0 mutation retenue sur l'ensemble des millesimes -- "
            "verifier le filtrage (codes INSEE) ou le format source.",
            file=sys.stderr,
        )


if __name__ == "__main__":
    main()
