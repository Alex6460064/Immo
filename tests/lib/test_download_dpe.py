"""Tests pour pipeline/lib/download_dpe.py -- filtre qs, pagination via curseur `next`, et
resume par commune. Aucun appel reseau reel ici : le client HTTP est un stub injecte
(le contrat est identique a celui utilise pour pipeline/lib/geocode_ban.py)."""

import pytest

from pipeline.lib.download_dpe import (
    DPE_LINES_URL,
    build_initial_url,
    build_qs_filter,
    fetch_all_lines,
    summarize_by_commune,
)


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


class FakeClient:
    """Stub respectant le contrat `.get(url) -> objet avec .json()`.
    Sert les payloads fournis dans l'ordre des appels et enregistre les URLs demandees."""

    def __init__(self, payloads):
        self._payloads = list(payloads)
        self.urls = []

    def get(self, url):
        self.urls.append(url)
        return FakeResponse(self._payloads.pop(0))


def test_build_qs_filter_joint_les_codes_avec_or():
    assert build_qs_filter(["64024", "64122"]) == "code_insee_ban:64024 OR code_insee_ban:64122"


def test_build_qs_filter_un_seul_code():
    assert build_qs_filter(["64122"]) == "code_insee_ban:64122"


def test_build_qs_filter_liste_vide_leve_value_error():
    with pytest.raises(ValueError):
        build_qs_filter([])


def test_build_initial_url_contient_le_filtre_et_la_taille_de_page():
    url = build_initial_url(["64122"], page_size=500)
    assert url.startswith(f"{DPE_LINES_URL}?")
    assert "qs=code_insee_ban%3A64122" in url
    assert "size=500" in url


def test_build_initial_url_applique_select_fields_par_defaut():
    url = build_initial_url(["64122"])
    assert "select=" in url
    assert "etiquette_dpe" in url


def test_build_initial_url_select_fields_vide_desactive_la_restriction():
    url = build_initial_url(["64122"], select_fields=[])
    assert "select=" not in url


def test_fetch_all_lines_suit_le_curseur_next_jusqu_a_epuisement():
    page1 = {
        "total": 3,
        "results": [{"code_insee_ban": "64122"}, {"code_insee_ban": "64122"}],
        "next": "https://data.ademe.fr/next-page-url",
    }
    page2 = {"total": 3, "results": [{"code_insee_ban": "64122"}], "next": None}
    client = FakeClient([page1, page2])

    records = fetch_all_lines(client, ["64122"], page_size=2)

    assert len(records) == 3
    assert client.urls[1] == "https://data.ademe.fr/next-page-url"


def test_fetch_all_lines_une_seule_page_si_next_absent():
    page1 = {"total": 1, "results": [{"code_insee_ban": "64122"}]}  # pas de cle "next"
    client = FakeClient([page1])

    records = fetch_all_lines(client, ["64122"])

    assert len(records) == 1
    assert len(client.urls) == 1


def test_summarize_by_commune_compte_par_code_insee():
    records = [
        {"code_insee_ban": "64122"},
        {"code_insee_ban": "64122"},
        {"code_insee_ban": "64024"},
    ]

    assert summarize_by_commune(records) == {"64122": 2, "64024": 1}


def test_summarize_by_commune_valeur_manquante_comptee_sous_none():
    records = [{"code_insee_ban": "64122"}, {}]

    result = summarize_by_commune(records)

    assert result["64122"] == 1
    assert result[None] == 1
