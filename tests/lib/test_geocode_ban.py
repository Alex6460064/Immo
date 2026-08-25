"""Tests pour pipeline/lib/geocode_ban.py — le geocodage BAN est mis en cache sur disque
pour ne jamais re-interroger inutilement une API publique soumise a rate limiting.
Aucun appel reseau reel ici : le client HTTP est un stub injecte."""

import json

import pytest

from pipeline.lib.geocode_ban import GeocodeCache, geocode_address, load_cache, save_cache


class FakeResponse:
    """Reponse HTTP minimale : seule .json() est utilisee par geocode_address."""

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


class FakeClient:
    """Stub respectant le contrat `.get(url, params=...) -> objet avec .json()`.
    Enregistre les appels pour verifier qu'aucun appel n'est fait sur un cache hit."""

    def __init__(self, payload):
        self._payload = payload
        self.calls = []

    def get(self, url, params=None):
        self.calls.append((url, params))
        return FakeResponse(self._payload)


FOUND_PAYLOAD = {
    "features": [
        {
            "geometry": {"coordinates": [-1.5586, 43.4832]},
            "properties": {"label": "12 Rue de la Bidassoa 64100 Bayonne"},
        }
    ]
}

NOT_FOUND_PAYLOAD = {"features": []}


@pytest.fixture
def cache_path(tmp_path):
    return tmp_path / "geocode_cache.jsonl"


def test_cache_miss_appelle_le_client_et_retourne_lat_lon(cache_path):
    client = FakeClient(FOUND_PAYLOAD)
    cache = GeocodeCache(cache_path)

    result = geocode_address(client, "12 Rue de la Bidassoa 64100 Bayonne", cache)

    assert result == {"lat": 43.4832, "lon": -1.5586}
    assert len(client.calls) == 1


def test_cache_hit_n_appelle_pas_le_client(cache_path):
    client = FakeClient(FOUND_PAYLOAD)
    cache = GeocodeCache(cache_path)
    address = "12 Rue de la Bidassoa 64100 Bayonne"

    first = geocode_address(client, address, cache)
    assert len(client.calls) == 1

    second = geocode_address(client, address, cache)
    assert len(client.calls) == 1  # pas de nouvel appel
    assert second == first == {"lat": 43.4832, "lon": -1.5586}


def test_cache_miss_sans_resultat_retourne_none(cache_path):
    client = FakeClient(NOT_FOUND_PAYLOAD)
    cache = GeocodeCache(cache_path)

    result = geocode_address(client, "adresse inexistante xyzzy", cache)

    assert result is None
    assert len(client.calls) == 1


def test_not_found_est_mis_en_cache_et_evite_un_nouvel_appel(cache_path):
    client = FakeClient(NOT_FOUND_PAYLOAD)
    cache = GeocodeCache(cache_path)
    address = "adresse inexistante xyzzy"

    first = geocode_address(client, address, cache)
    second = geocode_address(client, address, cache)

    assert first is None
    assert second is None
    assert len(client.calls) == 1


def test_le_cache_normalise_l_adresse_pour_la_cle(cache_path):
    """Deux adresses qui different seulement par la casse/espaces doivent
    correspondre a la meme entree de cache."""
    client = FakeClient(FOUND_PAYLOAD)
    cache = GeocodeCache(cache_path)

    geocode_address(client, "  12 Rue de la Bidassoa 64100 Bayonne  ", cache)
    geocode_address(client, "12 RUE DE LA BIDASSOA 64100 BAYONNE", cache)

    assert len(client.calls) == 1


def test_le_cache_persiste_sur_disque_entre_deux_instances(cache_path):
    client = FakeClient(FOUND_PAYLOAD)
    cache1 = GeocodeCache(cache_path)
    address = "12 Rue de la Bidassoa 64100 Bayonne"

    geocode_address(client, address, cache1)
    assert cache_path.exists()

    # Nouvelle instance, meme fichier : doit relire du disque sans appeler le client.
    cache2 = GeocodeCache(cache_path)
    fresh_client = FakeClient(FOUND_PAYLOAD)
    result = geocode_address(fresh_client, address, cache2)

    assert result == {"lat": 43.4832, "lon": -1.5586}
    assert len(fresh_client.calls) == 0


def test_geocode_address_appelle_l_endpoint_attendu(cache_path):
    client = FakeClient(FOUND_PAYLOAD)
    cache = GeocodeCache(cache_path)

    geocode_address(client, "12 Rue de la Bidassoa 64100 Bayonne", cache)

    url, params = client.calls[0]
    assert url == "https://api-adresse.data.gouv.fr/search/"
    assert params["q"] == "12 Rue de la Bidassoa 64100 Bayonne"
    assert params["limit"] == 1


def test_load_cache_sur_fichier_absent_retourne_cache_vide(cache_path):
    entries = load_cache(cache_path)
    assert entries == {}


def test_save_cache_puis_load_cache_round_trip(cache_path):
    entries = {
        "12 rue de la bidassoa 64100 bayonne": {"lat": 43.4832, "lon": -1.5586},
        "adresse inexistante xyzzy": None,
    }

    save_cache(cache_path, entries)
    reloaded = load_cache(cache_path)

    assert reloaded == entries


def test_save_cache_ecrit_un_jsonl_valide_ligne_par_ligne(cache_path):
    entries = {"a": {"lat": 1.0, "lon": 2.0}, "b": None}
    save_cache(cache_path, entries)

    lines = cache_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    for line in lines:
        row = json.loads(line)
        assert "address" in row and "result" in row


def test_save_cache_ne_laisse_pas_de_fichier_tmp_apres_une_ecriture_reussie(cache_path):
    save_cache(cache_path, {"a": {"lat": 1.0, "lon": 2.0}})

    tmp_path = cache_path.with_suffix(cache_path.suffix + ".tmp")
    assert not tmp_path.exists()
    assert cache_path.exists()


def test_save_cache_preserve_le_cache_existant_si_l_ecriture_est_interrompue(
    cache_path, monkeypatch
):
    """Simule un crash entre l'ecriture du fichier temporaire et le bascule
    atomique (os.replace) : le cache existant doit rester intact et lisible,
    pas tronque/corrompu."""
    save_cache(cache_path, {"a": {"lat": 1.0, "lon": 2.0}})
    original_content = cache_path.read_text(encoding="utf-8")

    def boom(*args, **kwargs):
        raise OSError("simulated crash during atomic replace")

    monkeypatch.setattr("pipeline.lib.geocode_ban.os.replace", boom)

    with pytest.raises(OSError):
        save_cache(cache_path, {"a": {"lat": 1.0, "lon": 2.0}, "b": None})

    # Le cache d'origine n'a pas ete touche : toujours present et intact.
    assert cache_path.read_text(encoding="utf-8") == original_content
    assert load_cache(cache_path) == {"a": {"lat": 1.0, "lon": 2.0}}
