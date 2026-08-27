"""Tests pour pipeline.lib.ban_client -- client HTTP urllib + wrapper retry
partages par les etapes de geocodage DVF (02b) et DPE (03) (#22).

Le client reel (urllib) n'est pas teste ici (I/O reseau) ; on teste `geocode_with_retry`
avec un client/cache stub, comme la seam geocode_ban.
"""

import json
import urllib.error

import pytest

from pipeline.lib import ban_client
from pipeline.lib.ban_client import geocode_with_retry


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
    monkeypatch.setattr(
        ban_client, "geocode_address", lambda *_a: {"lat": 1.0, "lon": 2.0}
    )
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
