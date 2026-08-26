"""Geocode cleaned DVF mutations (data/processed/dvf_clean.parquet, T6/#7) via the
BAN seam + disk cache (T3/#4), attaching lat/lon. See issue #8 (T7) for acceptance
criteria.

--- Choix documente : emplacement du cache de geocodage BAN ---
Ce script partage le cache BAN avec le geocodage DPE (T8, pipeline/03_clean_dpe.py) :
data/processed/ban_geocode_cache.jsonl. Choix fait initialement par T8 (voir son
commentaire de fermeture sur #9) -- reutilise ici a l'identique pour que les deux
etapes de geocodage (DVF et DPE) partagent leurs entrees de cache et ne re-interrogent
jamais l'API BAN deux fois pour la meme adresse normalisee.

--- Choix documente : requete de geocodage BAN vs adresse_normalisee ---
Voir la docstring de pipeline/lib/clean_dvf.py (build_geocoding_query) : la requete
envoyee a l'API BAN est adresse_brute + code_postal + commune (memes raisons que DPE
-- une adresse de rue seule est souvent ambigue entre communes), distincte de
adresse_normalisee qui sert de cle de comparaison textuelle DVF<->DPE (premiere passe
de l'algorithme de jointure, ADR 0003).

Idempotent : si data/processed/dvf_geocoded.parquet existe deja et n'est pas vide, le
script ne refait rien (supprimer le fichier pour forcer un re-run complet). Le
geocodage lui-meme est mis en cache par adresse (pas seulement par run complet) : un
re-run apres suppression du parquet mais avec un cache BAN deja chaud ne refait aucun
appel reseau pour les adresses deja vues.
"""

from __future__ import annotations

import json
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlencode

import duckdb

# Execution en script direct (`python pipeline/02b_geocode_ban.py` depuis la racine, comme
# documente dans le WORKFLOW de CLAUDE.md) : la racine du repo n'est pas automatiquement
# sur sys.path (contrairement a pytest, ou pyproject.toml fixe pythonpath=["."]).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.lib.clean_dvf import build_geocoding_query  # noqa: E402
from pipeline.lib.geocode_ban import GeocodeCache, geocode_address  # noqa: E402

INPUT_PATH = Path(__file__).resolve().parent.parent / "data" / "processed" / "dvf_clean.parquet"
OUTPUT_PATH = (
    Path(__file__).resolve().parent.parent / "data" / "processed" / "dvf_geocoded.parquet"
)
# Voir "Choix documente : emplacement du cache de geocodage BAN" en tete de fichier --
# meme chemin que pipeline/03_clean_dpe.py, pour un cache partage DVF/DPE.
GEOCODE_CACHE_PATH = (
    Path(__file__).resolve().parent.parent / "data" / "processed" / "ban_geocode_cache.jsonl"
)

BAN_USER_AGENT = "dvf-dpe-pays-basque/0.1 (portfolio project; contact via GitHub Alex6460064/Immo)"
REQUEST_TIMEOUT_S = 20
MAX_GEOCODE_RETRIES = 3
RETRY_DELAY_S = 2

_INPUT_COLUMNS = [
    "identifiant_document",
    "no_disposition",
    "date_mutation",
    "nature_mutation",
    "code_insee",
    "commune",
    "code_postal",
    "adresse_brute",
    "adresse_normalisee",
    "type_local",
    "nombre_pieces_principales",
    "surface",
    "prix",
]

_OUTPUT_COLUMNS = {
    "identifiant_document": "VARCHAR",
    "no_disposition": "VARCHAR",
    "date_mutation": "VARCHAR",
    "nature_mutation": "VARCHAR",
    "code_insee": "VARCHAR",
    "commune": "VARCHAR",
    "code_postal": "VARCHAR",
    "adresse_brute": "VARCHAR",
    "adresse_normalisee": "VARCHAR",
    "type_local": "VARCHAR",
    "nombre_pieces_principales": "VARCHAR",
    "surface": "DOUBLE",
    "prix": "DOUBLE",
    "lat": "DOUBLE",
    "lon": "DOUBLE",
}


class BanUrllibClient:
    """Client HTTP minimal (stdlib urllib) respectant le contrat `.get(url, params) ->
    response` avec `response.json() -> dict`, attendu par pipeline.lib.geocode_ban.
    Identique a la classe du meme nom dans pipeline/03_clean_dpe.py."""

    class _Response:
        def __init__(self, body: bytes):
            self._body = body

        def json(self) -> dict:
            return json.loads(self._body)

    def get(self, url: str, params: dict | None = None) -> BanUrllibClient._Response:
        full_url = f"{url}?{urlencode(params)}" if params else url
        request = urllib.request.Request(full_url, headers={"User-Agent": BAN_USER_AGENT})
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_S) as response:
            return BanUrllibClient._Response(response.read())


def _geocode_with_retry(client, address: str, cache: GeocodeCache) -> tuple[str, dict | None]:
    """Geocode une adresse avec retry sur erreur reseau transitoire.

    Retourne (statut, coords) avec statut dans {"found", "not_found", "error"} --
    voir pipeline/03_clean_dpe.py pour le detail de la distinction not_found/error.
    """
    if address in cache:
        cached = cache.get(address)
        return ("found", cached) if cached is not None else ("not_found", None)

    last_error: Exception | None = None
    for attempt in range(1, MAX_GEOCODE_RETRIES + 1):
        try:
            result = geocode_address(client, address, cache)
            return ("found", result) if result is not None else ("not_found", None)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            last_error = exc
            print(
                f"  [retry {attempt}/{MAX_GEOCODE_RETRIES}] geocodage '{address}' : {exc}",
                file=sys.stderr,
            )
            time.sleep(RETRY_DELAY_S)
    print(
        f"  ABANDON geocodage (echec reseau persistant, non mis en cache) : {address} "
        f"({last_error})",
        file=sys.stderr,
    )
    return ("error", None)


def geocode_rows(rows: list[dict], client, cache: GeocodeCache) -> dict[str, int]:
    """Geocode en place chaque ligne de `rows` (ajoute les cles 'lat'/'lon').

    Retourne les compteurs {"no_address", "found", "not_found", "error"}.
    """
    stats = {"no_address": 0, "found": 0, "not_found": 0, "error": 0}
    for row in rows:
        query = build_geocoding_query(row)
        if not query:
            row["lat"] = None
            row["lon"] = None
            stats["no_address"] += 1
            continue

        status, coords = _geocode_with_retry(client, query, cache)
        stats[status] += 1
        row["lat"] = coords["lat"] if coords else None
        row["lon"] = coords["lon"] if coords else None
    return stats


def load_clean_rows(input_path: Path) -> list[dict]:
    """Lit data/processed/dvf_clean.parquet en liste de dict."""
    con = duckdb.connect()
    result = con.execute(
        f"SELECT {', '.join(_INPUT_COLUMNS)} FROM read_parquet(?)", [str(input_path)]
    )
    columns = [d[0] for d in result.description]
    return [dict(zip(columns, row, strict=True)) for row in result.fetchall()]


def write_parquet(rows: list[dict], output_path: Path) -> None:
    """Ecrit `rows` en Parquet via DuckDB, en passant par un JSONL temporaire (duckdb ne
    sait pas scanner directement une liste de dict Python -- meme approche que
    pipeline/03_clean_dpe.py, pas de nouvelle dependance pandas/pyarrow)."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="dvf_geocoded_") as tmp:
        tmp_path = Path(tmp) / "dvf_geocoded.jsonl"
        with tmp_path.open("w", encoding="utf-8") as f:
            for row in rows:
                serializable = dict(row)
                if serializable.get("date_mutation") is not None:
                    serializable["date_mutation"] = str(serializable["date_mutation"])
                f.write(json.dumps(serializable, ensure_ascii=False))
                f.write("\n")

        columns_literal = ", ".join(f"'{name}': '{typ}'" for name, typ in _OUTPUT_COLUMNS.items())
        tmp_path_posix = str(tmp_path).replace("\\", "/")
        output_path_literal = str(output_path).replace("\\", "/").replace("'", "''")

        con = duckdb.connect()
        con.execute(
            f"""
            COPY (
                SELECT {", ".join(_OUTPUT_COLUMNS)}
                FROM read_json_auto('{tmp_path_posix}', columns={{{columns_literal}}})
            ) TO '{output_path_literal}' (FORMAT PARQUET)
            """
        )


def main() -> None:
    if not INPUT_PATH.exists():
        print(f"ERREUR : fichier introuvable : {INPUT_PATH}", file=sys.stderr)
        print("  Lancer d'abord : python pipeline/02_clean_dvf.py", file=sys.stderr)
        sys.exit(1)

    if OUTPUT_PATH.exists() and OUTPUT_PATH.stat().st_size > 0:
        print(
            f"[geocode_ban] Fichier deja present ({OUTPUT_PATH}) -- geocodage saute "
            "(idempotent). Supprimer le fichier pour forcer un re-run complet."
        )
        return

    print(f"[geocode_ban] Lecture de {INPUT_PATH}")
    rows = load_clean_rows(INPUT_PATH)
    rows_in = len(rows)
    print(f"[geocode_ban] {rows_in} mutations DVF nettoyees a geocoder")

    print(f"[geocode_ban] Geocodage via API BAN (cache partage DVF/DPE : {GEOCODE_CACHE_PATH})")
    client = BanUrllibClient()
    cache = GeocodeCache(GEOCODE_CACHE_PATH)
    stats = geocode_rows(rows, client, cache)

    print(f"[geocode_ban] Ecriture de {OUTPUT_PATH}")
    write_parquet(rows, OUTPUT_PATH)

    attempted = stats["found"] + stats["not_found"] + stats["error"]
    success_rate = (stats["found"] / attempted * 100) if attempted else 0.0
    success_rate_of_total = (stats["found"] / rows_in * 100) if rows_in else 0.0

    print("\n=== Resume geocodage BAN DVF (T7 / #8) ===")
    print(f"  Mutations en entree : {rows_in}")
    print(f"    - sans adresse exploitable (non tente) : {stats['no_address']}")
    print(f"    - trouve                                : {stats['found']}")
    print(f"    - non trouve (API BAN, aucun resultat)  : {stats['not_found']}")
    print(
        f"    - erreur reseau persistante (a re-tenter au prochain run) : {stats['error']}"
    )
    print(
        f"    - taux de succes / tentatives ({attempted} adresses interrogees) : "
        f"{success_rate:.1f}%"
    )
    print(f"    - taux de succes / mutations totales : {success_rate_of_total:.1f}%")

    if rows_in and stats["found"] == 0:
        print(
            "ATTENTION : 0 mutation geocodee avec succes -- verifier la connectivite/le "
            "format des adresses.",
            file=sys.stderr,
        )


if __name__ == "__main__":
    main()
