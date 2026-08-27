"""Nettoie les DPE ADEME bruts (data/raw/dpe_pays_basque.jsonl, T5/#6) : filtre
post-reforme (juillet 2021+), normalise l'adresse (meme fonction que DVF, T2/#3),
geocode via la seam BAN + cache disque partagee avec DVF (T3/#4), et ecrit le
resultat en Parquet dans data/processed/. Voir issue #9 (T8) pour les criteres
d'acceptation.

--- Choix documente : emplacement du cache de geocodage BAN ---
Ce script ecrit/lit le cache de geocodage a data/processed/ban_geocode_cache.jsonl.
L'etape de geocodage DVF (T7 / 02b_geocode_ban.py) n'existe pas encore au moment ou
ce script est ecrit (ticket separe, developpe potentiellement en parallele) -- ce
chemin est donc un choix explicite fait ici, PAS encore confirme avec T7. Le cache est
adresse -> {"lat", "lon"} | None (voir pipeline/lib/geocode_ban.py), independant du
jeu de donnees source (DVF ou DPE) : n'importe quelle etape de geocodage pointant vers
le meme fichier partage ses entrees. Quand T7 sera implemente, verifier qu'il pointe
vers CE MEME chemin (ou adapter ce script en consequence) pour beneficier du partage
de cache entre DVF et DPE -- sinon les deux etapes re-interrogeront l'API BAN pour les
adresses en commun.

--- Choix documente : requete de geocodage BAN vs adresse_normalisee ---
Voir la docstring de pipeline/lib/clean_dpe.py (build_geocoding_query) : la requete
envoyee a l'API BAN est adresse_brut + code_postal_brut + nom_commune_brut (jamais les
champs *_ban precalcules par ADEME), distincte de adresse_normalisee qui sert de cle de
comparaison textuelle DVF<->DPE (premiere passe de l'algorithme de jointure, ADR 0003).

Idempotent : si data/processed/dpe_clean.parquet existe deja et n'est pas vide, le
script ne refait rien (supprimer le fichier pour forcer un re-run complet). Le
geocodage lui-meme est mis en cache par adresse (pas seulement par run complet) : un
re-run apres suppression du parquet mais avec un cache BAN deja chaud ne refait aucun
appel reseau pour les adresses deja vues.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import duckdb

# Execution en script direct (`python pipeline/03_clean_dpe.py` depuis la racine, comme
# documente dans le WORKFLOW de CLAUDE.md) : la racine du repo n'est pas automatiquement
# sur sys.path (contrairement a pytest, ou pyproject.toml fixe pythonpath=["."]).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.lib.ban_client import BanUrllibClient, geocode_with_retry  # noqa: E402
from pipeline.lib.clean_dpe import process_records  # noqa: E402
from pipeline.lib.geocode_ban import GeocodeCache  # noqa: E402
from pipeline.lib.parquet_io import write_parquet_rows  # noqa: E402

RAW_PATH = Path(__file__).resolve().parent.parent / "data" / "raw" / "dpe_pays_basque.jsonl"
OUTPUT_PATH = Path(__file__).resolve().parent.parent / "data" / "processed" / "dpe_clean.parquet"
# Voir "Choix documente : emplacement du cache de geocodage BAN" en tete de fichier.
GEOCODE_CACHE_PATH = (
    Path(__file__).resolve().parent.parent / "data" / "processed" / "ban_geocode_cache.jsonl"
)

_CLEAN_COLUMNS = {
    "numero_dpe": "VARCHAR",
    "date_etablissement_dpe": "VARCHAR",
    "etiquette_dpe": "VARCHAR",
    "etiquette_ges": "VARCHAR",
    "type_batiment": "VARCHAR",
    "periode_construction": "VARCHAR",
    "surface_habitable_logement": "DOUBLE",
    "adresse_brut": "VARCHAR",
    "adresse_normalisee": "VARCHAR",
    "adresse_geocodage": "VARCHAR",
    "code_insee_ban": "VARCHAR",
    "nom_commune_ban": "VARCHAR",
    "code_postal_ban": "VARCHAR",
    "lat": "DOUBLE",
    "lon": "DOUBLE",
}


def geocode_clean_rows(clean_rows: list[dict], client, cache: GeocodeCache) -> dict[str, int]:
    """Geocode en place chaque ligne de `clean_rows` (ajoute les cles 'lat'/'lon').

    Retourne les compteurs {"no_address", "found", "not_found", "error"}.
    """
    stats = {"no_address": 0, "found": 0, "not_found": 0, "error": 0}
    for row in clean_rows:
        query = row["adresse_geocodage"]
        if not query:
            row["lat"] = None
            row["lon"] = None
            stats["no_address"] += 1
            continue

        status, coords = geocode_with_retry(client, query, cache)
        stats[status] += 1
        row["lat"] = coords["lat"] if coords else None
        row["lon"] = coords["lon"] if coords else None
    return stats


def _output_columns_current(path: Path) -> bool:
    """Colonnes du parquet de sortie == `_CLEAN_COLUMNS` ? Un parquet d'un schema
    anterieur (ex. sans `periode_construction`, ajoutee en #23) ferait planter
    04_join sur une colonne absente -- on ne saute alors PAS le nettoyage."""
    path_literal = str(path).replace("\\", "/").replace("'", "''")
    con = duckdb.connect()
    present = {row[0] for row in con.execute(f"DESCRIBE SELECT * FROM '{path_literal}'").fetchall()}
    return set(_CLEAN_COLUMNS) <= present


def main() -> None:
    if not RAW_PATH.exists():
        print(f"ERREUR : fichier brut introuvable : {RAW_PATH}", file=sys.stderr)
        print("  Lancer d'abord : python pipeline/download_dpe.py", file=sys.stderr)
        sys.exit(1)

    if OUTPUT_PATH.exists() and OUTPUT_PATH.stat().st_size > 0:
        if _output_columns_current(OUTPUT_PATH):
            print(
                f"[clean_dpe] Fichier deja present ({OUTPUT_PATH}) -- nettoyage saute "
                "(idempotent). Supprimer le fichier pour forcer un re-run complet."
            )
            return
        print(
            f"[clean_dpe] {OUTPUT_PATH} a un schema anterieur (colonnes manquantes) -- "
            "re-nettoyage complet pour le mettre a jour."
        )

    print(f"[clean_dpe] Lecture de {RAW_PATH}")
    records: list[dict] = []
    with RAW_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    rows_in = len(records)
    print(f"[clean_dpe] {rows_in} lignes DPE brutes lues")

    clean_rows, exclusions = process_records(records)
    rows_out = len(clean_rows)
    print(
        f"[clean_dpe] Filtre post-reforme (>= 2021-07-01) : {rows_out} retenues, "
        f"{rows_in - rows_out} exclues"
    )

    print(f"[clean_dpe] Geocodage via API BAN (cache : {GEOCODE_CACHE_PATH})")
    client = BanUrllibClient()
    cache = GeocodeCache(GEOCODE_CACHE_PATH)
    geocode_stats = geocode_clean_rows(clean_rows, client, cache)

    print(f"[clean_dpe] Ecriture de {OUTPUT_PATH}")
    write_parquet_rows(clean_rows, _CLEAN_COLUMNS, OUTPUT_PATH)

    attempted = geocode_stats["found"] + geocode_stats["not_found"] + geocode_stats["error"]
    success_rate = (geocode_stats["found"] / attempted * 100) if attempted else 0.0
    success_rate_of_output = (geocode_stats["found"] / rows_out * 100) if rows_out else 0.0

    print("\n=== Resume nettoyage DPE (T8 / #9) ===")
    print(f"  Lignes en entree (brut)      : {rows_in}")
    print(f"  Lignes en sortie (post-2021-07-01, parquet) : {rows_out}")
    print("  Lignes exclues et pourquoi :")
    print(f"    - pre-reforme (< 2021-07-01)      : {exclusions['pre_reform']}")
    print(f"    - date manquante                  : {exclusions['missing_date']}")
    print(f"    - date invalide (format inattendu): {exclusions['invalid_date']}")
    print("  Geocodage (parmi les lignes retenues) :")
    print(f"    - sans adresse exploitable (non tente) : {geocode_stats['no_address']}")
    print(f"    - trouve                                : {geocode_stats['found']}")
    print(f"    - non trouve (API BAN, aucun resultat)  : {geocode_stats['not_found']}")
    print(
        f"    - erreur reseau persistante (a re-tenter au prochain run) : {geocode_stats['error']}"
    )
    print(
        f"    - taux de succes / tentatives ({attempted} adresses interrogees) : "
        f"{success_rate:.1f}%"
    )
    print(f"    - taux de succes / lignes de sortie totales : {success_rate_of_output:.1f}%")

    if rows_out == 0:
        print(
            "ATTENTION : 0 ligne DPE retenue apres filtre post-reforme -- verifier le "
            "fichier source / la logique de filtrage.",
            file=sys.stderr,
        )


if __name__ == "__main__":
    main()
