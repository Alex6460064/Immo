"""Tests pour pipeline/lib/download_dvf.py -- logique pure (parsing API data.gouv.fr,
decision d'idempotence), aucun appel reseau reel ici."""

from pipeline.lib.download_dvf import (
    output_path_for_year,
    parse_resource_year,
    select_dvf_resources,
    should_download,
)


def test_parse_resource_year_extrait_le_millesime():
    assert parse_resource_year("Valeurs foncieres 2025") == 2025
    assert parse_resource_year("Valeurs foncieres 2021") == 2021


def test_parse_resource_year_retourne_none_si_pas_d_annee():
    assert parse_resource_year("Foire aux questions") is None
    assert parse_resource_year("Conditions generales d'utilisation") is None


def test_select_dvf_resources_ignore_les_documents_annexes():
    resources = [
        {"title": "Valeurs foncieres 2025", "format": "txt.zip", "url": "https://x/2025.zip"},
        {"title": "Foire aux questions", "format": "pdf", "url": "https://x/faq.pdf"},
        {
            "title": "Notice descriptive des fichiers de valeurs foncieres",
            "format": "pdf",
            "url": "https://x/notice.pdf",
        },
    ]

    selected = select_dvf_resources(resources)

    assert selected == [
        {"year": 2025, "url": "https://x/2025.zip", "title": "Valeurs foncieres 2025"}
    ]


def test_select_dvf_resources_ignore_une_ressource_sans_url():
    resources = [{"title": "Valeurs foncieres 2025", "format": "txt.zip", "url": None}]

    assert select_dvf_resources(resources) == []


def test_select_dvf_resources_trie_par_annee_croissante():
    resources = [
        {"title": "Valeurs foncieres 2023", "format": "txt.zip", "url": "https://x/2023.zip"},
        {"title": "Valeurs foncieres 2021", "format": "txt.zip", "url": "https://x/2021.zip"},
        {"title": "Valeurs foncieres 2022", "format": "txt.zip", "url": "https://x/2022.zip"},
    ]

    years = [r["year"] for r in select_dvf_resources(resources)]

    assert years == [2021, 2022, 2023]


def test_output_path_for_year_est_deterministe(tmp_path):
    path = output_path_for_year(2025, tmp_path)

    assert path == tmp_path / "dvf_brut_2025.parquet"


def test_should_download_true_si_fichier_absent(tmp_path):
    assert should_download(2025, tmp_path) is True


def test_should_download_false_si_fichier_deja_present(tmp_path):
    output_path_for_year(2025, tmp_path).write_text("deja telecharge et filtre")

    assert should_download(2025, tmp_path) is False


def test_should_download_est_independant_par_millesime(tmp_path):
    output_path_for_year(2024, tmp_path).write_text("deja telecharge et filtre")

    assert should_download(2024, tmp_path) is False
    assert should_download(2025, tmp_path) is True
