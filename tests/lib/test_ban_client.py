"""Tests pour pipeline.lib.ban_client -- client HTTP urllib + wrapper retry
partages par les etapes de geocodage DVF (02b) et DPE (03) (#22).

Le client reel (urllib) n'est pas teste ici (I/O reseau) ; on teste `geocode_with_retry`
avec un client/cache stub, comme la seam geocode_ban.
"""

import json
import urllib.error

import pytest

from pipeline.lib import ban_client
from pipeline.lib.ban_client import GeocodeStats, geocode_rows, geocode_with_retry
from pipeline.lib.clean_dvf import build_geocoding_query


class _Cache(dict):
    """Contrat minimal de GeocodeCache : `in` + `.get(addr)`."""

    def get(self, address, default=None):
        return dict.get(self, address, default)


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(ban_client.time, "sleep", lambda _s: None)


def test_cache_hit_found_skips_client():
    cache = _Cache({"12 rue X": {"lat": 43.0, "lon": -1.0}})

    def boom(*_a, **_k):
        raise AssertionError("client ne doit pas etre appele sur un hit de cache")

    status, coords = geocode_with_retry(boom, "12 rue X", cache)
    assert status == "found"
    assert coords == {"lat": 43.0, "lon": -1.0}


def test_cache_hit_none_is_not_found():
    cache = _Cache({"12 rue X": None})
    status, coords = geocode_with_retry(object(), "12 rue X", cache)
    assert status == "not_found"
    assert coords is None


def test_success_on_first_call(monkeypatch):
    cache = _Cache()
    monkeypatch.setattr(ban_client, "geocode_address", lambda *_a: {"lat": 1.0, "lon": 2.0})
    status, coords = geocode_with_retry(object(), "addr", cache)
    assert status == "found"
    assert coords == {"lat": 1.0, "lon": 2.0}


def test_api_returned_no_result_is_not_found(monkeypatch):
    cache = _Cache()
    monkeypatch.setattr(ban_client, "geocode_address", lambda *_a: None)
    status, coords = geocode_with_retry(object(), "addr", cache)
    assert status == "not_found"
    assert coords is None


def test_retries_then_succeeds(monkeypatch):
    calls = {"n": 0}

    def flaky(*_a):
        calls["n"] += 1
        if calls["n"] < 3:
            raise urllib.error.URLError("temporarily down")
        return {"lat": 1.0, "lon": 2.0}

    monkeypatch.setattr(ban_client, "geocode_address", flaky)
    status, coords = geocode_with_retry(object(), "addr", _Cache())
    assert status == "found"
    assert calls["n"] == 3


def test_persistent_network_failure_is_error(monkeypatch):
    def always_fails(*_a):
        raise TimeoutError("still down")

    monkeypatch.setattr(ban_client, "geocode_address", always_fails)
    status, coords = geocode_with_retry(object(), "addr", _Cache())
    assert status == "error"
    assert coords is None


def test_json_decode_error_is_retried(monkeypatch):
    def bad_json(*_a):
        raise json.JSONDecodeError("boom", "", 0)

    monkeypatch.setattr(ban_client, "geocode_address", bad_json)
    status, _ = geocode_with_retry(object(), "addr", _Cache())
    assert status == "error"


class TestGeocodeRows:
    """geocode_rows : boucle de geocodage partagee par 02b_geocode_ban et
    03_clean_dpe -- geocode en place (ajoute row['lat']/row['lon']), agrege les
    comptages dans un GeocodeStats. La seule difference entre les deux etapes,
    d'ou vient la chaine d'adresse, est un adaptateur `address_of` injecte."""

    def test_adresse_none_compte_no_address_sans_geocoder(self):
        rows = [{"id": 1}]

        def client_interdit(*_a, **_k):
            raise AssertionError("le client ne doit pas etre appele sans adresse")

        stats = geocode_rows(rows, lambda _r: None, client_interdit, _Cache())

        assert stats == GeocodeStats(no_address=1, found=0, not_found=0, error=0)
        assert rows[0]["lat"] is None
        assert rows[0]["lon"] is None

    def test_adresse_vide_compte_no_address(self):
        rows = [{"id": 1}]
        stats = geocode_rows(rows, lambda _r: "", object(), _Cache())
        assert stats.no_address == 1

    def test_trouve_ecrit_lat_lon_en_place(self):
        cache = _Cache({"12 rue X": {"lat": 43.0, "lon": -1.0}})
        rows = [{"adr": "12 rue X"}]

        stats = geocode_rows(rows, lambda r: r["adr"], object(), cache)

        assert stats == GeocodeStats(no_address=0, found=1, not_found=0, error=0)
        assert rows[0]["lat"] == 43.0
        assert rows[0]["lon"] == -1.0

    def test_non_trouve_compte_not_found_et_lat_lon_none(self):
        cache = _Cache({"nowhere": None})
        rows = [{"adr": "nowhere"}]

        stats = geocode_rows(rows, lambda r: r["adr"], object(), cache)

        assert stats == GeocodeStats(no_address=0, found=0, not_found=1, error=0)
        assert rows[0]["lat"] is None
        assert rows[0]["lon"] is None

    def test_erreur_reseau_persistante_compte_error(self, monkeypatch):
        def always_fails(*_a):
            raise TimeoutError("down")

        monkeypatch.setattr(ban_client, "geocode_address", always_fails)
        rows = [{"adr": "12 rue X"}]

        stats = geocode_rows(rows, lambda r: r["adr"], object(), _Cache())

        assert stats == GeocodeStats(no_address=0, found=0, not_found=0, error=1)
        assert rows[0]["lat"] is None

    def test_batch_mixte_agrege_les_comptages(self):
        cache = _Cache({"found": {"lat": 1.0, "lon": 2.0}, "missing": None})
        rows = [{"adr": "found"}, {"adr": "missing"}, {"adr": None}, {"adr": "found"}]

        stats = geocode_rows(rows, lambda r: r["adr"], object(), cache)

        assert stats == GeocodeStats(no_address=1, found=2, not_found=1, error=0)

    def test_adaptateur_dvf_build_geocoding_query(self):
        """Forme 02b : l'adresse est derivee de plusieurs colonnes DVF."""
        row = {"adresse_brute": "12 rue X", "code_postal": "64100", "commune": "Bayonne"}
        query = build_geocoding_query(row)
        cache = _Cache({query: {"lat": 1.0, "lon": 2.0}})

        stats = geocode_rows([dict(row)], build_geocoding_query, object(), cache)

        assert stats.found == 1

    def test_adaptateur_dpe_lit_la_colonne_precalculee(self):
        """Forme 03 : l'adresse est deja dans row['adresse_geocodage']."""
        cache = _Cache({"12 rue X 64100 Bayonne": {"lat": 1.0, "lon": 2.0}})
        rows = [{"adresse_geocodage": "12 rue X 64100 Bayonne"}]

        stats = geocode_rows(rows, lambda r: r.get("adresse_geocodage"), object(), cache)

        assert stats.found == 1
        assert rows[0]["lat"] == 1.0

    def test_adaptateur_dpe_clef_absente_compte_no_address(self):
        rows = [{"autre": "x"}]
        stats = geocode_rows(rows, lambda r: r.get("adresse_geocodage"), object(), _Cache())
        assert stats.no_address == 1
