"""Geocoded-distance helpers for the DVF x DPE join (ADR 0003, passe 2).

Pure functions only -- no I/O, no network. `haversine_m` measures the
great-circle distance between two BAN-geocoded points; the T9 calibration
script (pipeline/calibrate_distance.py) uses it to measure how far apart DVF
and DPE geocode the *same* postal address, then picks DISTANCE_THRESHOLD_M.
"""

from __future__ import annotations

import math
import statistics

_PERCENTILES = (50, 75, 90, 95, 99)

# Seuil de la passe 2 de l'appariement DVF x DPE (ADR 0003) : un unique DPE
# candidat a <= ce seuil du point DVF geocode est tenu pour la meme adresse.
#
# Calibre par pipeline/calibrate_distance.py sur 5 733 paires d'adresses
# normalisees identiques entre DVF et DPE, chacune geocodee des deux cotes
# (execution du 2026-08-27, resume au bas de docs/adr/0003) :
#   - 95,9 % des paires sont a EXACTEMENT 0 m (l'API BAN renvoie le meme point
#     pour la meme adresse normalisee) ;
#   - 3 paires seulement entre 0 et 100 m (max 60 m) ;
#   - 4,1 % au-dela de 200 m : echecs de geocodage (repli centroide commune),
#     pas du bruit -> hors de tout seuil raisonnable, classes 'non trouve'.
# Il n'existe donc pas de bande de jitter a couvrir. 15 m fixe la marge pour un
# texte proche mais non identique (suffixe BIS/TER, numero manquant) que l'API
# BAN interpole vers un point voisin : ~1 pas d'interpolation de numero de voirie
# en tissu urbain dense (BAB), sans atteindre la parcelle mitoyenne. Toute la
# plage 10-30 m donne le meme comportement reel sur l'echantillon (95,87 %).
DISTANCE_THRESHOLD_M = 15

# IUGG mean Earth radius (meters). The two pipelines both geocode addresses in
# a ~30 km coastal strip, so a spherical model is well within the calibration's
# own noise -- an ellipsoidal (Vincenty) distance would be false precision here.
_EARTH_RADIUS_M = 6371008.8


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in meters between two WGS84 lat/lon points."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)

    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * _EARTH_RADIUS_M * math.asin(math.sqrt(a))


def distance_distribution(distances: list[float]) -> dict[str, float | None]:
    """Summarize a list of distances (meters): count, mean, min, max, and the
    50/75/90/95/99th percentiles (linear interpolation on rank).

    Empty input -> count 0 and every stat None. A single value -> that value for
    every stat (statistics.quantiles needs at least two points).
    """
    count = len(distances)
    keys = ["mean", "min", "max", *(f"p{p}" for p in _PERCENTILES)]

    if count == 0:
        return {"count": 0, **{k: None for k in keys}}
    if count == 1:
        return {"count": 1, **{k: distances[0] for k in keys}}

    cuts = statistics.quantiles(distances, n=100, method="inclusive")
    result: dict[str, float | None] = {
        "count": count,
        "mean": statistics.fmean(distances),
        "min": min(distances),
        "max": max(distances),
    }
    for p in _PERCENTILES:
        result[f"p{p}"] = cuts[p - 1]
    return result
