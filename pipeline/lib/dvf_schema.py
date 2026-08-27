"""Schema partage des parquets DVF du pipeline (#22).

Ces listes de colonnes etaient copiees a l'identique dans 02b_geocode_ban.py,
04_join.py (via join_dvf_dpe.py) et 04b_join_iris.py -- une seule source ici.

Le parquet `dvf_clean.parquet` (sortie de 02_clean_dvf.py) porte `date_mutation`
en type DATE ; 02b la serialise en texte ISO, donc `dvf_geocoded.parquet` et tout
l'aval la voient en VARCHAR. Seuls les *noms* de colonnes de `dvf_clean` servent
ici (lecture par 02b), d'ou `DVF_CLEAN_COLUMN_NAMES` sans types.
"""

from __future__ import annotations

# dvf_geocoded.parquet : sortie de 02b_geocode_ban, entree de 04_join et 04b_join_iris.
DVF_GEOCODED_COLUMNS: dict[str, str] = {
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

# Colonnes de dvf_clean.parquet lues par 02b (identiques a dvf_geocoded sans lat/lon).
DVF_CLEAN_COLUMN_NAMES: tuple[str, ...] = tuple(
    c for c in DVF_GEOCODED_COLUMNS if c not in ("lat", "lon")
)
