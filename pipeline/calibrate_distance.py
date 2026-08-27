"""T9 -- calibre le seuil de distance de la passe 2 de l'appariement DVF x DPE (ADR 0003).

Principe : sur les adresses ou DVF et DPE ont exactement la meme adresse normalisee
(les paires qui passent deja la passe 1 "texte exact"), on mesure la distance entre le
point geocode cote DVF et le point geocode cote DPE. Cette distribution est le "bruit
de geocodage" entre les deux pipelines pour une meme adresse reelle.

Resultat observe (voir le resume ajoute au bas de
docs/adr/0003-algorithme-appariement-dvf-dpe.md) : la distribution est degeneree --
~96 % des paires sont a exactement 0 m (l'API BAN renvoie le meme point pour la meme
adresse normalisee), et le reste est une queue d'echecs de geocodage a l'echelle du
kilometre (repli sur le centroide commune / mauvaise commune), sans bande de "jitter"
intermediaire. Le seuil ne se calibre donc pas sur un ecart-type : il fixe la marge
toleree pour un texte proche mais non identique (suffixe BIS/TER, numero manquant) que
l'API BAN interpole vers un point legerement decale.

Analyse ponctuelle, pas une etape du pipeline : rejouable a la main apres un
re-geocodage, sans effet de bord sur data/processed/.

Usage :
    uv run python pipeline/calibrate_distance.py
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.lib.match_distance import (  # noqa: E402
    DISTANCE_THRESHOLD_M,
    distance_distribution,
    haversine_m,
)

DATA_PROCESSED_DIR = Path(__file__).resolve().parent.parent / "data" / "processed"
DVF_PATH = DATA_PROCESSED_DIR / "dvf_geocoded.parquet"
DPE_PATH = DATA_PROCESSED_DIR / "dpe_clean.parquet"

# Histogramme imprime : (label, borne superieure incluse), une seule source de
# verite -- label et borne dans le meme tuple, impossible de les desynchroniser.
# Une distance tombe dans la premiere tranche dont elle ne depasse pas la borne.
# La derniere isole les echecs de geocodage (repli centroide commune) du bruit
# qu'on cherche a mesurer.
_GEOCODE_FAILURE_M = 200.0
_HISTOGRAM_BUCKETS: tuple[tuple[str, float], ...] = (
    ("exactement 0 m", 0.0),
    ("(0, 5] m", 5.0),
    ("(5, 15] m", 15.0),
    ("(15, 30] m", 30.0),
    ("(30, 100] m", 100.0),
    ("(100, 200] m", _GEOCODE_FAILURE_M),
    ("> 200 m (echec geocodage)", math.inf),
)

# Une adresse normalisee identique des deux cotes, chacune geocodee (lat/lon non
# nuls). DISTINCT sur le quintuplet : chaque ligne est une paire reelle
# (geocode DVF, geocode DPE) pour une adresse partagee.
_EXACT_MATCH_PAIRS_QUERY = """
    SELECT DISTINCT
        dvf.adresse_normalisee AS adresse,
        dvf.lat AS dvf_lat, dvf.lon AS dvf_lon,
        dpe.lat AS dpe_lat, dpe.lon AS dpe_lon
    FROM read_parquet(?) dvf
    JOIN read_parquet(?) dpe USING (adresse_normalisee)
    WHERE dvf.lat IS NOT NULL AND dvf.lon IS NOT NULL
      AND dpe.lat IS NOT NULL AND dpe.lon IS NOT NULL
      AND dvf.adresse_normalisee <> ''
"""


def load_exact_match_pairs(con: duckdb.DuckDBPyConnection) -> list[tuple]:
    return con.execute(_EXACT_MATCH_PAIRS_QUERY, [str(DVF_PATH), str(DPE_PATH)]).fetchall()


def bucket_counts(distances: list[float]) -> list[tuple[str, int]]:
    """Histogramme cumulable : (label, effectif) par tranche de _HISTOGRAM_BUCKETS.

    Chaque distance va dans la premiere tranche dont elle ne depasse pas la borne
    (la derniere borne est +inf, donc chaque distance tombe quelque part).
    """
    counts = [0] * len(_HISTOGRAM_BUCKETS)
    for d in distances:
        for i, (_, upper) in enumerate(_HISTOGRAM_BUCKETS):
            if d <= upper:
                counts[i] += 1
                break
    return [(label, count) for (label, _), count in zip(_HISTOGRAM_BUCKETS, counts, strict=True)]


def main() -> None:
    for path in (DVF_PATH, DPE_PATH):
        if not path.exists():
            print(f"ERREUR : fichier introuvable : {path}", file=sys.stderr)
            print("  Lancer d'abord 02b_geocode_ban.py et 03_clean_dpe.py.", file=sys.stderr)
            sys.exit(1)

    con = duckdb.connect()
    pairs = load_exact_match_pairs(con)

    distinct_addresses = len({p[0] for p in pairs})
    distances = [haversine_m(p[1], p[2], p[3], p[4]) for p in pairs]
    dist = distance_distribution(distances)

    print("=== Calibration seuil distance passe 2 (T9 / ADR 0003) ===")
    print(
        f"  Adresses normalisees partagees DVF<->DPE (geocodees des 2 cotes) : {distinct_addresses}"
    )
    print(f"  Paires (geocode DVF, geocode DPE) mesurees                       : {dist['count']}")
    if dist["count"] == 0:
        print(
            "ATTENTION : aucune paire -- verifier que les deux parquets sont geocodes "
            "et que la normalisation d'adresse est coherente entre DVF et DPE.",
            file=sys.stderr,
        )
        sys.exit(1)

    total = dist["count"]
    print("\n  Distribution des distances (metres) :")
    for label in ("mean", "p50", "p90", "p95", "p99", "max"):
        print(f"    {label:<7}: {dist[label]:.1f}")

    print("\n  Histogramme :")
    cum = 0
    for label, count in bucket_counts(distances):
        cum += count
        print(f"    {label:<32} {count:>6}   (cumul {cum / total:.2%})")

    within = sum(1 for d in distances if d <= DISTANCE_THRESHOLD_M)
    failures = sum(1 for d in distances if d > _GEOCODE_FAILURE_M)
    print(
        f"\n  Seuil fige : match_distance.DISTANCE_THRESHOLD_M = {DISTANCE_THRESHOLD_M} m\n"
        f"    couvre {within}/{total} paires ({within / total:.2%})\n"
        f"    {failures} paires ({failures / total:.2%}) sont des echecs de geocodage "
        f"(> {_GEOCODE_FAILURE_M:.0f} m) -> correctement classees 'non trouve' par la passe 2"
    )


if __name__ == "__main__":
    main()
