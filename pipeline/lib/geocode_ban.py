"""Geocodage d'adresses via l'API BAN (api-adresse.data.gouv.fr), avec cache disque.

Ce module est une "seam" testable : le client HTTP est injecte (jamais importe ici en
dur), et le cache est une classe separee, testable independamment de tout appel reseau.
Reutilise tel quel par les etapes de geocodage DVF et DPE du pipeline.

Contrat du client HTTP injecte
-------------------------------
`client` doit exposer une methode :

    client.get(url: str, params: dict) -> response

ou `response` expose une methode `.json() -> dict` qui retourne le corps JSON decode.
C'est exactement l'interface de `requests.Session`/`requests` (ou de tout objet stub
equivalent dans les tests). Aucune autre methode n'est requise.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

BAN_SEARCH_URL = "https://api-adresse.data.gouv.fr/search/"


def _normalize_address(address: str) -> str:
    """Cle de cache stable : espaces normalises, casse insensible.

    Volontairement simple (pas de logique metier ici) — la normalisation
    "riche" (abbreviations, accents, etc.) appartient a normalize_address.py (T2),
    pas a ce module dont le seul role est le geocodage + cache.
    """
    return " ".join(address.strip().split()).lower()


class GeocodeCache:
    """Cache adresse normalisee -> {"lat", "lon"} | None, persiste en JSONL.

    None signifie explicitement "recherche effectuee, aucun resultat trouve" —
    distinct d'une cle absente (jamais recherchee) — pour eviter de re-interroger
    l'API sur des echecs deja connus.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._entries: dict[str, dict | None] = load_cache(self.path)

    def get(self, address: str, default=...):
        key = _normalize_address(address)
        if key not in self._entries:
            if default is ...:
                raise KeyError(key)
            return default
        return self._entries[key]

    def __contains__(self, address: str) -> bool:
        return _normalize_address(address) in self._entries

    def set(self, address: str, value: dict | None) -> None:
        key = _normalize_address(address)
        self._entries[key] = value
        save_cache(self.path, self._entries)


def load_cache(path: str | Path) -> dict[str, dict | None]:
    """Charge le cache JSONL depuis disque. Fichier absent -> cache vide."""
    path = Path(path)
    if not path.exists():
        return {}

    entries: dict[str, dict | None] = {}
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            entries[row["address"]] = row["result"]
    return entries


def save_cache(path: str | Path, entries: dict[str, dict | None]) -> None:
    """Ecrit l'integralite du cache sur disque, une entree JSON par ligne.

    Ecriture atomique : le contenu est d'abord ecrit dans un fichier temporaire
    puis bascule sur la cible via os.replace (atomique sur POSIX et Windows).
    Sans ca, un crash/kill en cours d'ecriture (Ctrl+C pendant un batch de
    geocodage, OOM, etc.) laisserait le cache tronque ou avec une ligne
    malformee, et load_cache leverait json.JSONDecodeError au run suivant —
    perte de tout le cache accumule, pas seulement de la derniere entree.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as f:
        for address, result in entries.items():
            f.write(json.dumps({"address": address, "result": result}, ensure_ascii=False))
            f.write("\n")
    os.replace(tmp_path, path)


def geocode_address(client, address: str, cache: GeocodeCache) -> dict | None:
    """Geocode une adresse via l'API BAN, avec cache disque en amont.

    Retourne {"lat": float, "lon": float} si un resultat est trouve, sinon None.
    Un None est mis en cache au meme titre qu'un resultat trouve, pour ne pas
    re-interroger l'API sur un echec deja constate.

    `client` : voir le contrat documente en tete de module.
    `cache`  : instance de GeocodeCache, lue avant tout appel API.
    """
    if address in cache:
        return cache.get(address)

    response = client.get(BAN_SEARCH_URL, params={"q": address, "limit": 1})
    payload = response.json()

    features = payload.get("features") or []
    if not features:
        cache.set(address, None)
        return None

    lon, lat = features[0]["geometry"]["coordinates"]
    result = {"lat": lat, "lon": lon}
    cache.set(address, result)
    return result
