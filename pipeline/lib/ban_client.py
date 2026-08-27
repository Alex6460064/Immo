"""Client HTTP urllib pour l'API BAN + wrapper retry, partages par les etapes de
geocodage DVF (02b_geocode_ban.py) et DPE (03_clean_dpe.py) (#22).

`BanUrllibClient` et `geocode_with_retry` etaient copies a l'identique dans les deux
scripts. Le contrat du client (`.get(url, params) -> response` avec `.json()`) est
celui documente dans pipeline/lib/geocode_ban.py.

`USER_AGENT` est l'identite HTTP sortante commune du projet ; 04b_join_iris.py (WFS
IGN, pas BAN) la reutilise aussi. Les scripts `download_*` gardent leur propre
constante : chaine legerement differente, hors perimetre #22.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from urllib.parse import urlencode

from pipeline.lib.geocode_ban import GeocodeCache, geocode_address

USER_AGENT = "dvf-dpe-pays-basque/0.1 (portfolio project; contact via GitHub Alex6460064/Immo)"
BAN_REQUEST_TIMEOUT_S = 20
MAX_GEOCODE_RETRIES = 3
RETRY_DELAY_S = 2


class BanUrllibClient:
    """Client HTTP minimal (stdlib urllib) respectant le contrat `.get(url, params) ->
    response` avec `response.json() -> dict`, attendu par pipeline.lib.geocode_ban."""

    class _Response:
        def __init__(self, body: bytes):
            self._body = body

        def json(self) -> dict:
            return json.loads(self._body)

    def get(self, url: str, params: dict | None = None) -> BanUrllibClient._Response:
        full_url = f"{url}?{urlencode(params)}" if params else url
        request = urllib.request.Request(full_url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(request, timeout=BAN_REQUEST_TIMEOUT_S) as response:
            return BanUrllibClient._Response(response.read())


def geocode_with_retry(client, address: str, cache: GeocodeCache) -> tuple[str, dict | None]:
    """Geocode une adresse avec retry sur erreur reseau transitoire.

    Retourne (statut, coords) avec statut dans {"found", "not_found", "error"}.
    Distinction importante pour les resumes d'etape : "not_found" (l'API BAN a
    repondu, aucun resultat -- mis en cache par geocode_address, ne sera pas
    re-tente) est different de "error" (echec reseau persistant -- PAS mis en
    cache, sera re-tente au prochain run).
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
