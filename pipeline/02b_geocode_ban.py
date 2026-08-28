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

import sys
from pathlib import Path

# Execution en script direct (`python pipeline/02b_geocode_ban.py` depuis la racine, comme
# documente dans le WORKFLOW de CLAUDE.md) : la racine du repo n'est pas automatiquement
# sur sys.path (contrairement a pytest, ou pyproject.toml fixe pythonpath=["."]).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.lib.ban_client import BanUrllibClient, geocode_rows  # noqa: E402
from pipeline.lib.clean_dvf import build_geocoding_query  # noqa: E402
from pipeline.lib.dvf_schema import DVF_CLEAN_COLUMN_NAMES, DVF_GEOCODED_COLUMNS  # noqa: E402
from pipeline.lib.geocode_ban import GeocodeCache  # noqa: E402
from pipeline.lib.parquet_io import read_parquet_rows, write_parquet_rows  # noqa: E402

INPUT_PATH = Path(__file__).resolve().parent.parent / "data" / "processed" / "dvf_clean.parquet"
OUTPUT_PATH = Path(__file__).resolve().parent.parent / "data" / "processed" / "dvf_geocoded.parquet"
# Voir "Choix documente : emplacement du cache de geocodage BAN" en tete de fichier --
# meme chemin que pipeline/03_clean_dpe.py, pour un cache partage DVF/DPE.
GEOCODE_CACHE_PATH = (
    Path(__file__).resolve().parent.parent / "data" / "processed" / "ban_geocode_cache.jsonl"
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
    rows = read_parquet_rows(INPUT_PATH, DVF_CLEAN_COLUMN_NAMES)
    rows_in = len(rows)
    print(f"[geocode_ban] {rows_in} mutations DVF nettoyees a geocoder")

    print(f"[geocode_ban] Geocodage via API BAN (cache partage DVF/DPE : {GEOCODE_CACHE_PATH})")
    client = BanUrllibClient()
    cache = GeocodeCache(GEOCODE_CACHE_PATH)
    stats = geocode_rows(rows, build_geocoding_query, client, cache)

    print(f"[geocode_ban] Ecriture de {OUTPUT_PATH}")
    write_parquet_rows(rows, DVF_GEOCODED_COLUMNS, OUTPUT_PATH, str_columns=["date_mutation"])

    attempted = stats.found + stats.not_found + stats.error
    success_rate = (stats.found / attempted * 100) if attempted else 0.0
    success_rate_of_total = (stats.found / rows_in * 100) if rows_in else 0.0

    print("\n=== Resume geocodage BAN DVF (T7 / #8) ===")
    print(f"  Mutations en entree : {rows_in}")
    print(f"    - sans adresse exploitable (non tente) : {stats.no_address}")
    print(f"    - trouve                                : {stats.found}")
    print(f"    - non trouve (API BAN, aucun resultat)  : {stats.not_found}")
    print(f"    - erreur reseau persistante (a re-tenter au prochain run) : {stats.error}")
    print(
        f"    - taux de succes / tentatives ({attempted} adresses interrogees) : "
        f"{success_rate:.1f}%"
    )
    print(f"    - taux de succes / mutations totales : {success_rate_of_total:.1f}%")

    if rows_in and stats.found == 0:
        print(
            "ATTENTION : 0 mutation geocodee avec succes -- verifier la connectivite/le "
            "format des adresses.",
            file=sys.stderr,
        )


if __name__ == "__main__":
    main()
