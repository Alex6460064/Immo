"""Telecharge le DVF brut DGFiP (data.gouv.fr) et le filtre sur les communes ciblees.

Voir pipeline/lib/download_dvf.py pour la justification du dataset/URL source
(verifiee en direct via l'API data.gouv.fr, pas depuis la memoire du modele).

Le dataset officiel ne propose pas de decoupage par departement : chaque ressource
telechargee est un fichier "France entiere" pour un millesime donne. Ce script
telecharge donc necessairement un fichier national par millesime, mais n'ecrit sur
disque (data/raw/) que les lignes des communes ciblees (config/communes.py) --
jamais la France entiere, jamais un departement entier (voir ADR 0001 : le filtrage
se fait par code INSEE de commune).

Idempotent : un millesime deja telecharge et filtre (fichier present dans
data/raw/) n'est pas retelecharge -- voir should_download().

Usage :
    uv run python pipeline/download_dvf.py
"""

from __future__ import annotations

import json
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

import duckdb

# Execution en script direct (`python pipeline/download_dvf.py` depuis la racine, comme documente
# dans le WORKFLOW de CLAUDE.md) : la racine du repo n'est pas automatiquement sur sys.path
# (contrairement a pytest, ou pyproject.toml fixe pythonpath=["."]). Ajout local a ce script.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.communes import get_codes_insee  # noqa: E402
from pipeline.lib.download_dvf import (  # noqa: E402
    DATASET_API_URL,
    output_path_for_year,
    select_dvf_resources,
    should_download,
)

DATA_RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"
USER_AGENT = "dvf-dpe-pays-basque/0.1 (portfolio project, github.com/Alex6460064/Immo)"
MAX_DOWNLOAD_ATTEMPTS = 5
RETRY_DELAY_SECONDS = 5
CHUNK_SIZE = 1 << 20  # 1 MiB

_YEAR_SUMMARY_QUERY = """
    SELECT
        COUNT(*) AS rows,
        MIN(strptime("Date mutation", '%d/%m/%Y')) AS min_date,
        MAX(strptime("Date mutation", '%d/%m/%Y')) AS max_date
    FROM read_parquet(?)
"""


def fetch_dataset_metadata(url: str = DATASET_API_URL) -> dict:
    """Interroge l'API data.gouv.fr pour la liste des ressources du dataset DVF brut."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def _download_with_resume(url: str, dest: Path) -> int:
    """Telecharge `url` vers `dest`, avec reprise (HTTP Range) en cas de coupure.

    La connexion vers static.data.gouv.fr observee pendant le developpement de ce
    script coupe parfois apres plusieurs dizaines de Mo sur un fichier de ~70 Mo :
    on reprend depuis la taille deja ecrite plutot que de repartir de zero a chaque
    tentative, jusqu'a MAX_DOWNLOAD_ATTEMPTS.
    """
    for attempt in range(1, MAX_DOWNLOAD_ATTEMPTS + 1):
        existing = dest.stat().st_size if dest.exists() else 0
        headers = {"User-Agent": USER_AGENT}
        if existing:
            headers["Range"] = f"bytes={existing}-"
        request = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                resumed = existing and response.status == 206
                mode = "ab" if resumed else "wb"
                with dest.open(mode) as f:
                    while True:
                        chunk = response.read(CHUNK_SIZE)
                        if not chunk:
                            break
                        f.write(chunk)
            return dest.stat().st_size
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            if attempt == MAX_DOWNLOAD_ATTEMPTS:
                raise RuntimeError(
                    f"Echec du telechargement de {url} apres {attempt} tentatives"
                ) from exc
            print(
                f"  [retry {attempt}/{MAX_DOWNLOAD_ATTEMPTS}] {exc} "
                f"-- reprise dans {RETRY_DELAY_SECONDS}s",
                file=sys.stderr,
            )
            time.sleep(RETRY_DELAY_SECONDS)
    raise AssertionError("unreachable")  # pragma: no cover


def _write_parquet_literal(
    con: duckdb.DuckDBPyConnection, select_sql: str, output_path: Path
) -> None:
    """COPY ... TO necessite un chemin litteral (pas de parametre lie pour la cible)."""
    literal = str(output_path).replace("\\", "/").replace("'", "''")
    con.execute(f"COPY ({select_sql}) TO '{literal}' (FORMAT PARQUET)")


def download_and_filter_year(year: int, url: str, codes_insee: list[str], data_dir: Path) -> dict:
    """Telecharge le millesime `year`, filtre aux communes ciblees, ecrit le parquet.

    Retourne {"year", "rows", "min_date", "max_date"} sur les mutations retenues.
    """
    output_path = output_path_for_year(year, data_dir)
    codes_list = ", ".join(f"'{c}'" for c in codes_insee)

    with tempfile.TemporaryDirectory(prefix=f"dvf_{year}_") as tmp:
        tmp_dir = Path(tmp)
        zip_path = tmp_dir / f"valeursfoncieres-{year}.txt.zip"

        print(f"[{year}] telechargement depuis {url}")
        size = _download_with_resume(url, zip_path)
        print(f"[{year}] {size:,} octets telecharges, extraction")

        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
            if len(names) != 1:
                raise RuntimeError(
                    f"[{year}] archive inattendue : {len(names)} fichier(s) au lieu de 1 "
                    f"({names}) -- format du dataset probablement change, a verifier"
                )
            zf.extractall(tmp_dir)
            txt_path = tmp_dir / names[0]

        con = duckdb.connect()
        txt_path_posix = str(txt_path).replace("\\", "/")
        # "Code commune" n'est PAS zero-pad sur 3 chiffres dans le fichier brut DGFiP
        # (ex. Anglet '24', pas '024') -- verifie en direct sur le millesime 2021.
        # Sans LPAD, la concatenation departement+commune ne matche jamais les codes
        # INSEE < 100 de config/communes.py, et la commune disparait silencieusement.
        select_sql = f"""
            SELECT *
            FROM read_csv('{txt_path_posix}', delim='|', header=true, all_varchar=true)
            WHERE "Code departement" || LPAD("Code commune", 3, '0') IN ({codes_list})
        """
        _write_parquet_literal(con, select_sql, output_path)
        row = con.execute(_YEAR_SUMMARY_QUERY, [str(output_path)]).fetchone()

    return {"year": year, "rows": row[0], "min_date": row[1], "max_date": row[2]}


def summarize_cached_year(year: int, data_dir: Path) -> dict:
    """Relit un parquet deja en cache pour le resume final (pas de nouveau telechargement)."""
    output_path = output_path_for_year(year, data_dir)
    con = duckdb.connect()
    row = con.execute(_YEAR_SUMMARY_QUERY, [str(output_path)]).fetchone()
    return {"year": year, "rows": row[0], "min_date": row[1], "max_date": row[2]}


def main() -> None:
    DATA_RAW_DIR.mkdir(parents=True, exist_ok=True)
    codes_insee = get_codes_insee()

    print(f"Communes ciblees ({len(codes_insee)}) : {', '.join(codes_insee)}")
    print(f"Interrogation de l'API data.gouv.fr : {DATASET_API_URL}")
    dataset = fetch_dataset_metadata()
    resources = select_dvf_resources(dataset.get("resources", []))
    if not resources:
        print("ERREUR : aucune ressource DVF (txt.zip) trouvee sur le dataset.", file=sys.stderr)
        sys.exit(1)

    years_found = [r["year"] for r in resources]
    print(f"Millesimes disponibles sur data.gouv.fr (detectes a l'execution) : {years_found}")

    summaries = []
    for resource in resources:
        year = resource["year"]
        if should_download(year, DATA_RAW_DIR):
            summary = download_and_filter_year(year, resource["url"], codes_insee, DATA_RAW_DIR)
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

    print("\n=== Resume telechargement DVF brut (communes ciblees, dept. 64 + 40) ===")
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
