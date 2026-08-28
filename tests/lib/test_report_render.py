"""Smoke test du rendu de la synthese PDF -- `pipeline/report/template.typ`.

La logique pure (chiffres) est couverte par `test_report.py`. Ici on verifie
seulement que le template Typst compile avec le contrat JSON documente dans
`pipeline/07_report.py` (`_build_data`) et que le PDF est reproductible bit a bit.

Hors CI : `typst` n'est pas dans le groupe installe par la CI (`report`,
non-defaut) -> `importorskip` saute proprement. Le premier rendu telecharge le
paquet `lilaq` depuis Typst Universe (puis cache) : ce test suppose un acces
reseau au moins une fois.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

typst = pytest.importorskip("typst")

TEMPLATE = Path(__file__).resolve().parents[2] / "pipeline" / "report" / "template.typ"


def _fixture() -> dict:
    """Un jeu minimal mais complet : chaque champ lu par le template est present,
    y compris une fenetre `sautee` et une serie DPE a effectifs nuls."""
    serie_appt = {
        "type": "Appartement",
        "couleur": "#1f6feb",
        "annee_debut": "2016",
        "n_debut": 800,
        "n_fin": 540,
        "points": [
            {"annee": "2016", "prix": 2800.0, "n": 800},
            {"annee": "2020", "prix": 3700.0, "n": 700},
            {"annee": "2025", "prix": 4000.0, "n": 540},
        ],
        "evolutions": [
            {
                "libelle": "1 an",
                "prix_debut": 4100.0,
                "prix_fin": 4000.0,
                "variation_pct": -2.4,
                "variation_txt": "−2.4 %",
            },
            {
                "libelle": "depuis 2016",
                "prix_debut": 2800.0,
                "prix_fin": 4000.0,
                "variation_pct": 42.9,
                "variation_txt": "+42.9 %",
            },
        ],
        "sautees": [{"libelle": "5 ans", "raison": "annee de depart absente"}],
    }
    return {
        "meta": {
            "annee_min": "2016",
            "annee_max": "2025",
            "annee_ref": "2025",
            "post_reforme": "juillet 2021",
            "villes": ["BAYONNE", "ANGLET"],
        },
        "appariement": {"total": 27190, "certains": 14374, "taux": 52.9},
        "communes": [
            {"nom_affiche": "Bayonne", "series": [serie_appt]},
            {"nom_affiche": "Anglet", "series": [serie_appt]},
        ],
        "dpe": {
            "par_commune": [
                {
                    "nom_affiche": "Bayonne",
                    "series": [
                        {
                            "type": "Appartement",
                            "couleur": "#1f6feb",
                            "pm2": [0, 3000, 8000, 9000, 7000, 11000, 12000],
                            "n": [0, 12, 153, 488, 189, 44, 8],
                        },
                        {
                            "type": "Maison",
                            "couleur": "#d29922",
                            "pm2": [0, 0, 7500, 8800, 6000, 10000, 9000],
                            "n": [0, 0, 84, 69, 65, 19, 6],
                        },
                    ],
                }
            ],
            "exemples_ecarts": [
                "Bayonne / Appartement — classe F : −8 % vs classe D (en-dessous, n=44)",
            ],
        },
    }


def _render(out: Path, data: dict) -> bytes:
    typst.compile(
        str(TEMPLATE),
        output=str(out),
        sys_inputs={"data": json.dumps(data, ensure_ascii=False)},
        ignore_system_fonts=True,
        timestamp=0,
    )
    return out.read_bytes()


def test_template_compiles_to_pdf(tmp_path):
    pdf = _render(tmp_path / "s.pdf", _fixture())
    assert pdf[:5] == b"%PDF-"
    assert len(pdf) > 5000


def test_render_is_reproducible(tmp_path):
    data = _fixture()
    assert _render(tmp_path / "a.pdf", data) == _render(tmp_path / "b.pdf", data)


def test_template_compiles_without_dpe_examples(tmp_path):
    data = _fixture()
    data["dpe"]["exemples_ecarts"] = []
    pdf = _render(tmp_path / "s.pdf", data)
    assert pdf[:5] == b"%PDF-"
