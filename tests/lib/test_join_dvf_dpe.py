"""Tests for pipeline.lib.join_dvf_dpe -- pure wiring of the DVF x DPE join
(scoping + per-commune matching + output rows + report), no I/O.

Seam: `match_all(dvf_rows, dpe_rows, seuil) -> (out_rows, MatchReport)` -- one
output row per mutation, plus a `MatchReport` carrying every count printed by
`pipeline/04_join.py`. The 4-pass logic itself is tested in test_match_dvf_dpe.py;
the per-commune scoping in `TestGroupDpeByCommune`.
"""

from pipeline.lib.join_dvf_dpe import (
    OUTPUT_COLUMNS,
    MatchReport,
    group_dpe_by_commune,
    match_all,
)

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


def _dpe(
    numero,
    code_insee_ban,
    adresse,
    surface,
    *,
    etiquette=None,
    ges=None,
    type_batiment=None,
    periode=None,
    date="2022-01-01",
):
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
        dpe = [
            _dpe("D1", "64102", "10 RUE DU MOULIN", 50.0, etiquette="C"),
            _dpe("D2", "64102", "5 RUE DES FLEURS", 50.0, etiquette="E"),
            _dpe("D3", "64102", "5 RUE DES FLEURS", 51.0, etiquette="E"),
        ]
        rows, report = match_all(dvf, dpe, _SEUIL)

        assert isinstance(report, MatchReport)
        assert len(rows) == 3
        assert report.total == 3
        assert sum(report.status_counts.values()) == 3
        assert report.status_counts["trouve"] == 1
        assert report.status_counts["non_trouve"] == 1
        assert report.status_counts["resolu_consensus"] == 1
        assert report.dedup_removed == 0

    def test_every_row_has_the_full_output_schema(self):
        dvf = [_mut("64102", "10 RUE DU MOULIN", surface=50.0)]
        dpe = [
            _dpe(
                "D1",
                "64102",
                "10 RUE DU MOULIN",
                50.0,
                etiquette="C",
                ges="D",
                type_batiment="appartement",
                periode="1975-1977",
            )
        ]
        (rows, _report) = match_all(dvf, dpe, _SEUIL)
        row = rows[0]
        assert set(row) == set(OUTPUT_COLUMNS)
        assert row["match_status"] == "trouve"
        assert row["etiquette_dpe"] == "C"
        assert row["etiquette_ges"] == "D"
        assert row["type_batiment"] == "appartement"
        assert row["periode_construction"] == "1975-1977"
        assert row["filtre_type_applique"] is False

    def test_resolu_consensus_row_has_no_numero_dpe_but_a_label(self):
        dvf = [_mut("64102", "5 RUE DES FLEURS", surface=50.0)]
        dpe = [
            _dpe("D1", "64102", "5 RUE DES FLEURS", 50.0, etiquette="D"),
            _dpe("D2", "64102", "5 RUE DES FLEURS", 51.0, etiquette="D"),
        ]
        (rows, _report) = match_all(dvf, dpe, _SEUIL)
        row = rows[0]
        assert row["match_status"] == "resolu_consensus"
        assert row["numero_dpe"] is None
        assert row["etiquette_dpe"] == "D"

    def test_dedup_removed_counts_collapsed_redundant_dpe(self):
        dvf = [_mut("64102", "10 RUE DU MOULIN", surface=44.0)]
        redundant = dict(
            surface=44.2, etiquette="D", ges="D", type_batiment="appartement", periode="2013-2021"
        )
        dpe = [
            _dpe("D1", "64102", "10 RUE DU MOULIN", date="2022-01-01", **redundant),
            _dpe("D2", "64102", "10 RUE DU MOULIN", date="2024-01-01", **redundant),
            _dpe("D3", "64102", "10 RUE DU MOULIN", date="2023-01-01", **redundant),
        ]
        rows, report = match_all(dvf, dpe, _SEUIL)
        assert report.dedup_removed == 2
        assert report.status_counts["trouve"] == 1
        assert rows[0]["numero_dpe"] == "D2"


class TestMatchAllIsOrderIndependent:
    """#32 : l'appariement ne doit pas dependre de l'ordre physique du parquet
    `dpe_clean`. `COPY` DuckDB ne fige pas l'ordre des lignes ; deux lignes de
    meme `numero_dpe` + meme date d'etablissement mais geocodees differemment
    (cas reel de l'export ADEME) ne doivent pas faire basculer un resultat
    selon leur ordre d'apparition."""

    _REF_LAT, _REF_LON = 43.4832, -1.5586

    def _geo(self, row, lat, lon):
        return {**row, "lat": lat, "lon": lon}

    def test_result_invariant_under_dpe_row_permutation(self):
        mut = self._geo(
            _mut("64102", "10 RUE DU MOULIN", surface=44.0), self._REF_LAT, self._REF_LON
        )
        sig = dict(etiquette="D", ges="D", type_batiment="appartement", periode="2013-2021")
        near = self._geo(
            _dpe("SAME", "64102", "12 RUE VOISINE", 44.2, **sig),
            self._REF_LAT + 0.00005, self._REF_LON,
        )
        far = self._geo(
            _dpe("SAME", "64102", "12 RUE VOISINE", 44.2, **sig),
            self._REF_LAT + 0.002, self._REF_LON,
        )

        outcomes = set()
        for order in ([near, far], [far, near]):
            rows, _report = match_all([mut], order, _SEUIL)
            outcomes.add((rows[0]["match_status"], rows[0]["numero_dpe"]))
        assert len(outcomes) == 1


class TestMatchReport:
    def test_methode_counts_only_counts_certain_label_rows(self):
        dvf = [
            _mut("64102", "10 RUE DU MOULIN", surface=50.0),  # trouve / texte_exact
            _mut("64102", "5 RUE DES FLEURS", surface=50.0),  # resolu_consensus / consensus
            _mut("64102", "INCONNUE", surface=50.0),  # non_trouve / None
            _mut("64102", "9 RUE MIXTE", surface=50.0),  # ambigu / None
        ]
        dpe = [
            _dpe("M1", "64102", "10 RUE DU MOULIN", 50.0, etiquette="C"),
            _dpe("F1", "64102", "5 RUE DES FLEURS", 50.0, etiquette="D"),
            _dpe("F2", "64102", "5 RUE DES FLEURS", 51.0, etiquette="D"),
            _dpe("X1", "64102", "9 RUE MIXTE", 50.0, etiquette="E"),
            _dpe("X2", "64102", "9 RUE MIXTE", 51.0, etiquette="F"),
        ]
        _rows, report = match_all(dvf, dpe, _SEUIL)
        assert report.methode_counts == {"texte_exact": 1, "consensus_etiquette": 1}

    def test_filtre_type_count_counts_mutations_where_filter_c_pruned(self):
        dvf = [_mut("64102", "7 RUE A", surface=50.0, type_local="Appartement")]
        dpe = [
            _dpe("D1", "64102", "7 RUE A", 50.0, etiquette="C", type_batiment="appartement"),
            _dpe("D2", "64102", "7 RUE A", 50.0, etiquette="C", type_batiment="maison"),
        ]
        rows, report = match_all(dvf, dpe, _SEUIL)
        assert rows[0]["filtre_type_applique"] is True
        assert report.filtre_type_count == 1

    def test_pre_reforme_count_only_certain_label_before_cutoff(self):
        dvf = [
            _mut("64102", "10 RUE DU MOULIN", surface=50.0, date="2020-03-01"),  # pre-reforme
            _mut("64102", "12 RUE DU MOULIN", surface=50.0, date="2023-03-01"),  # post-reforme
            _mut("64102", "INCONNUE", surface=50.0, date="2019-01-01"),  # pre mais non_trouve
        ]
        dpe = [
            _dpe("A1", "64102", "10 RUE DU MOULIN", 50.0, etiquette="C"),
            _dpe("A2", "64102", "12 RUE DU MOULIN", 50.0, etiquette="C"),
        ]
        _rows, report = match_all(dvf, dpe, _SEUIL)
        assert report.pre_reforme_count == 1

    def test_dpe_sans_commune_flows_into_report(self):
        dvf = [_mut("64102", "10 RUE DU MOULIN", surface=50.0)]
        dpe = [
            _dpe("A1", "64102", "10 RUE DU MOULIN", 50.0, etiquette="C"),
            _dpe("A2", "", "3 RUE ORPHELINE", 60.0),
        ]
        _rows, report = match_all(dvf, dpe, _SEUIL)
        assert report.dpe_sans_commune == 1

    def test_report_dicts_are_plain_dicts_not_counters(self):
        _rows, report = match_all([_mut("64102", "X", surface=1.0)], [], _SEUIL)
        assert type(report.status_counts) is dict
        assert type(report.methode_counts) is dict
