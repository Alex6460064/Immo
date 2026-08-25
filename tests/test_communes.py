"""Tests for config/communes.py — le pipeline entier depend de cette liste,
donc sa forme et son contenu sont verrouilles par des tests avant tout usage."""

from config.communes import COMMUNES, get_codes_insee, get_communes


def test_seize_communes_ciblees():
    assert len(COMMUNES) == 16


def test_chaque_commune_a_un_code_insee_et_un_departement():
    for commune in COMMUNES:
        assert set(commune.keys()) == {"nom", "code_insee", "departement"}
        assert commune["departement"] in {"64", "40"}
        assert len(commune["code_insee"]) == 5


def test_exception_dept_40_limitee_a_tarnos_et_ondres():
    """Voir ADR 0001 : Tarnos et Ondres (dept. 40) sont une exception documentee,
    pas une regle silencieuse — toutes les autres communes sont dept. 64."""
    communes_40 = {c["nom"] for c in COMMUNES if c["departement"] == "40"}
    assert communes_40 == {"Tarnos", "Ondres"}


def test_get_communes_retourne_toutes_les_communes_par_defaut():
    assert get_communes() == COMMUNES


def test_get_communes_filtre_par_departement():
    communes_64 = get_communes(departement="64")
    assert len(communes_64) == 14
    assert all(c["departement"] == "64" for c in communes_64)

    communes_40 = get_communes(departement="40")
    assert {c["nom"] for c in communes_40} == {"Tarnos", "Ondres"}


def test_get_codes_insee_retourne_la_liste_des_codes():
    codes = get_codes_insee()
    assert len(codes) == 16
    assert "64024" in codes  # Anglet
    assert "40312" in codes  # Tarnos
