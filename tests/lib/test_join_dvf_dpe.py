"""Tests for pipeline.lib.join_dvf_dpe -- pure wiring of the DVF x DPE join
(scoping + per-commune matching + output rows), no I/O.

Seam: `match_all(dvf_rows, dpe_by_commune, seuil)` -- one output row per mutation,
a Counter over the 4 states (spec #23 §5), and the count of DPE removed by dedup.
The 4-pass logic itself is tested in test_match_dvf_dpe.py.
"""

from pipeline.lib.join_dvf_dpe import OUTPUT_COLUMNS, group_dpe_by_commune, match_all

_SEUIL = 15


def _mut(code_insee, adresse="", surface=None, type_local=None, date="2023-01-01"):
    return {
        "identifiant_document": "doc",
        "no_disposition": "1",
        "date_mutation": date,
        "nature_mutation": "Vente",
        "code_insee": code_insee,
        "commune": "BAYONNE",
        "code_postal": "64100",
        "adresse_brute": adresse,
        "adresse_normalisee": adresse,
        "type_local": type_local,
        "nombre_pieces_principales": "3",
        "surface": surface,
        "prix": 300_000.0,
        "lat": None,
        "lon": None,
    }


def _dpe(numero, code_insee_ban, adresse, surface, *, etiquette=None, ges=None,
         type_batiment=None, periode=None, date="2022-01-01"):
    return {
        "numero_dpe": numero,
        "date_etablissement_dpe": date,
        "etiquette_dpe": etiquette,
        "etiquette_ges": ges,
        "type_batiment": type_batiment,
        "periode_construction": periode,
        "adresse_normalisee": adresse,
        "surface_habitable_logement": surface,
        "code_insee_ban": code_insee_ban,
        "lat": None,
        "lon": None,
    }


class TestGroupDpeByCommune:
    def test_groups_by_code_insee_ban_and_counts_the_orphans(self):
        rows = [
            _dpe("A", "64102", "1 RUE A", 40.0),
            _dpe("B", "64102", "2 RUE B", 50.0),
            _dpe("C", "", "3 RUE C", 60.0),
        ]
        groups, sans_commune = group_dpe_by_commune(rows)
        assert set(groups) == {"64102"}
        assert len(groups["64102"]) == 2
        assert sans_commune == 1


class TestMatchAll:
    def test_one_row_per_mutation_and_counts_sum_to_total(self):
        dvf = [
            _mut("64102", "10 RUE DU MOULIN", surface=50.0),  # trouve
            _mut("64102", "INCONNUE", surface=50.0),  # non_trouve
            _mut("64102", "5 RUE DES FLEURS", surface=50.0, type_local="Appartement"),  # consensus
        ]
        dpe_by_commune, _ = group_dpe_by_commune(
            [
                _dpe("D1", "64102", "10 RUE DU MOULIN", 50.0, etiquette="C"),
                _dpe("D2", "64102", "5 RUE DES FLEURS", 50.0, etiquette="E"),
                _dpe("D3", "64102", "5 RUE DES FLEURS", 51.0, etiquette="E"),
            ]
        )
        rows, counts, dedup_removed = match_all(dvf, dpe_by_commune, _SEUIL)

        assert len(rows) == 3
        assert sum(counts.values()) == 3
        assert counts["trouve"] == 1
        assert counts["non_trouve"] == 1
        assert counts["resolu_consensus"] == 1
        assert dedup_removed == 0

    def test_every_row_has_the_full_output_schema(self):
        dvf = [_mut("64102", "10 RUE DU MOULIN", surface=50.0)]
        dpe_by_commune, _ = group_dpe_by_commune(
            [_dpe("D1", "64102", "10 RUE DU MOULIN", 50.0, etiquette="C", ges="D",
                  type_batiment="appartement", periode="1975-1977")]
        )
        (row,), _, _ = match_all(dvf, dpe_by_commune, _SEUIL)
        assert set(row) == set(OUTPUT_COLUMNS)
        assert row["match_status"] == "trouve"
        assert row["etiquette_dpe"] == "C"
        assert row["etiquette_ges"] == "D"
        assert row["type_batiment"] == "appartement"
        assert row["periode_construction"] == "1975-1977"
        assert row["filtre_type_applique"] is False

    def test_resolu_consensus_row_has_no_numero_dpe_but_a_label(self):
        dvf = [_mut("64102", "5 RUE DES FLEURS", surface=50.0)]
        dpe_by_commune, _ = group_dpe_by_commune(
            [
                _dpe("D1", "64102", "5 RUE DES FLEURS", 50.0, etiquette="D"),
                _dpe("D2", "64102", "5 RUE DES FLEURS", 51.0, etiquette="D"),
            ]
        )
        (row,), _, _ = match_all(dvf, dpe_by_commune, _SEUIL)
        assert row["match_status"] == "resolu_consensus"
        assert row["numero_dpe"] is None
        assert row["etiquette_dpe"] == "D"

    def test_dedup_removed_counts_collapsed_redundant_dpe(self):
        dvf = [_mut("64102", "10 RUE DU MOULIN", surface=44.0)]
        redundant = dict(
            surface=44.2, etiquette="D", ges="D", type_batiment="appartement", periode="2013-2021"
        )
        dpe_by_commune, _ = group_dpe_by_commune(
            [
                _dpe("D1", "64102", "10 RUE DU MOULIN", date="2022-01-01", **redundant),
                _dpe("D2", "64102", "10 RUE DU MOULIN", date="2024-01-01", **redundant),
                _dpe("D3", "64102", "10 RUE DU MOULIN", date="2023-01-01", **redundant),
            ]
        )
        rows, counts, dedup_removed = match_all(dvf, dpe_by_commune, _SEUIL)
        assert dedup_removed == 2
        assert counts["trouve"] == 1
        assert rows[0]["numero_dpe"] == "D2"
