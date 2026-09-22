"""Le jeu de statuts porteurs d'une etiquette certaine est un PARAMETRE, pas une
constante figee (prefactor #34, prepare le 5e etat `resolu_jev` de #33).

Test differentiel inter-modules, sur le modele de celui qui verrouille
`classify_match` / `classify_match_indexed` : pour un meme jeu de statuts, les
trois consommateurs -- rapport d'appariement (`match_all`), vue Impact DPE
(`impact_dpe_slice`) et resumes du dashboard (`matching_rate`) -- doivent
compter exactement les memes mutations. Sans ce verrou, l'ajout d'un statut
diverge silencieusement entre les trois surfaces.

La fixture place toutes les mutations AVANT le cutoff post-reforme : cote
`MatchReport`, `pre_reforme_count` compte alors toutes les mutations a etiquette
certaine, quelle que soit la passe ayant conclu (`ambigu` / `non_trouve` n'ont
pas de `methode`, donc `methode_counts` ne conviendrait pas comme sonde).
"""

import pytest

from dashboard.data import MATCH_STATUSES, matching_rate
from pipeline.lib.clean_dpe import POST_REFORM_CUTOFF
from pipeline.lib.impact_dpe import impact_dpe_rows, impact_dpe_slice
from pipeline.lib.join_dvf_dpe import match_all
from pipeline.lib.match_dvf_dpe import IMPACT_DPE_STATUSES, normalize_statuses

_SEUIL = 15
_DATE_PRE_REFORME = "2019-01-01"


def _mut(no_disposition, adresse, *, type_local="Appartement", surface=50.0):
    return {
        "identifiant_document": "doc",
        "no_disposition": no_disposition,
        "date_mutation": _DATE_PRE_REFORME,
        "nature_mutation": "Vente",
        "code_insee": "64102",
        "commune": "ANGLET",
        "code_postal": "64600",
        "adresse_brute": adresse,
        "adresse_normalisee": adresse,
        "type_local": type_local,
        "nombre_pieces_principales": "3",
        "surface": surface,
        "prix": 300_000.0,
        "lat": None,
        "lon": None,
    }


def _dpe(numero, adresse, surface, etiquette):
    return {
        "numero_dpe": numero,
        "date_etablissement_dpe": "2022-01-01",
        "etiquette_dpe": etiquette,
        "etiquette_ges": None,
        "type_batiment": None,
        "periode_construction": None,
        "adresse_normalisee": adresse,
        "surface_habitable_logement": surface,
        "code_insee_ban": "64102",
        "lat": None,
        "lon": None,
    }


# Une mutation par etat d'appariement, toutes a 6 000 EUR/m2 (dans la bande
# ADR 0006) et mono-type habitation : chacune produit exactement un point.
_DVF = [
    _mut("000001", "10 RUE DU MOULIN"),  # trouve
    _mut("000002", "5 RUE DES FLEURS"),  # resolu_consensus (memes etiquettes)
    _mut("000003", "8 RUE DES LILAS"),  # ambigu (etiquettes divergentes)
    _mut("000004", "INCONNUE"),  # non_trouve
]
_DPE = [
    _dpe("D1", "10 RUE DU MOULIN", 50.0, "C"),
    _dpe("D2", "5 RUE DES FLEURS", 50.0, "E"),
    _dpe("D3", "5 RUE DES FLEURS", 51.0, "E"),
    _dpe("D4", "8 RUE DES LILAS", 50.0, "B"),
    _dpe("D5", "8 RUE DES LILAS", 51.0, "F"),
]

# Jeux de statuts eprouves : le defaut, ses sous-ensembles, l'ensemble complet,
# et un jeu contenant un statut inexistant dans la fixture -- c'est exactement la
# forme que prendra `resolu_jev` tant qu'aucune passe Jev n'a tourne.
_JEUX = [
    (),
    ("trouve",),
    IMPACT_DPE_STATUSES,
    ("trouve", "resolu_consensus", "ambigu"),
    ("trouve", "resolu_consensus", "non_trouve", "ambigu"),
]

# Le 5e etat de #33, tant qu'aucune passe Jev n'a tourne : connu du pipeline,
# pas encore du dashboard (c'est #38 qui l'ajoutera a `MATCH_STATUS_LABELS`).
_STATUT_INCONNU = "resolu_jev"


class TestJeuDeStatutsParametrable:
    def test_la_fixture_produit_bien_les_quatre_etats(self):
        _rows, report = match_all(_DVF, _DPE, _SEUIL)
        assert report.status_counts == {
            "trouve": 1,
            "resolu_consensus": 1,
            "ambigu": 1,
            "non_trouve": 1,
        }

    def test_les_trois_consommateurs_comptent_les_memes_mutations(self):
        for statuses in _JEUX:
            rows, report = match_all(_DVF, _DPE, _SEUIL, statuses=statuses)
            attendu = sum(report.status_counts.get(s, 0) for s in statuses)

            slice_ = impact_dpe_slice(rows, cutoff=POST_REFORM_CUTOFF, statuses=statuses)
            taux = matching_rate(report.status_counts, statuses=statuses)

            assert report.pre_reforme_count == attendu, statuses
            assert slice_.etiquette_certaine == attendu, statuses
            assert taux["etiquette_certaine"]["n"] == attendu, statuses

    def test_le_defaut_reste_le_jeu_actuel(self):
        rows, report = match_all(_DVF, _DPE, _SEUIL)
        rows_explicite, report_explicite = match_all(
            _DVF, _DPE, _SEUIL, statuses=IMPACT_DPE_STATUSES
        )
        assert rows == rows_explicite
        assert report == report_explicite

        sans = impact_dpe_slice(rows, cutoff=POST_REFORM_CUTOFF)
        avec = impact_dpe_slice(rows, cutoff=POST_REFORM_CUTOFF, statuses=IMPACT_DPE_STATUSES)
        assert sans == avec

        assert matching_rate(report.status_counts) == matching_rate(
            report.status_counts, statuses=IMPACT_DPE_STATUSES
        )


class TestStatutInconnuDuDashboard:
    """Un statut que le pipeline connait mais que le dashboard n'etiquette pas
    encore (`resolu_jev` avant #38). Cote pipeline il doit simplement ne rien
    compter ; cote dashboard il doit ECHOUER FORT plutot que de produire un taux
    incoherent -- `matching_rate` calcule son total sur `MATCH_STATUSES`, donc un
    statut hors de ce jeu entrerait au numerateur sans entrer au denominateur
    (revue #34)."""

    def test_le_pipeline_tolere_un_statut_absent_des_donnees(self):
        rows, report = match_all(_DVF, _DPE, _SEUIL, statuses=("trouve", _STATUT_INCONNU))
        assert report.pre_reforme_count == report.status_counts["trouve"]
        slice_ = impact_dpe_slice(
            rows, cutoff=POST_REFORM_CUTOFF, statuses=("trouve", _STATUT_INCONNU)
        )
        assert slice_.etiquette_certaine == report.status_counts["trouve"]

    def test_le_dashboard_refuse_un_statut_hors_de_son_jeu_affiche(self):
        assert _STATUT_INCONNU not in MATCH_STATUSES
        with pytest.raises(ValueError, match=_STATUT_INCONNU):
            matching_rate({"trouve": 10}, statuses=("trouve", _STATUT_INCONNU))


class TestChaineNueRefusee:
    """`Sequence[str]` accepte une chaine nue, et `tuple("trouve")` l'eclaterait
    en caracteres : le filtre ne retiendrait plus rien et la tranche reviendrait
    vide, sans erreur. Echec silencieux -> on leve (revue #34)."""

    def test_normalize_statuses_leve_sur_une_chaine(self):
        with pytest.raises(TypeError):
            normalize_statuses("trouve")

    def test_normalize_statuses_accepte_les_iterables(self):
        assert normalize_statuses(["trouve", "ambigu"]) == ("trouve", "ambigu")
        assert normalize_statuses({"trouve"}) == ("trouve",)

    def test_chaque_seam_refuse_une_chaine(self):
        with pytest.raises(TypeError):
            match_all(_DVF, _DPE, _SEUIL, statuses="trouve")
        with pytest.raises(TypeError):
            impact_dpe_rows([], POST_REFORM_CUTOFF, statuses="trouve")
        with pytest.raises(TypeError):
            impact_dpe_slice([], cutoff=POST_REFORM_CUTOFF, statuses="trouve")
        with pytest.raises(TypeError):
            matching_rate({"trouve": 1}, statuses="trouve")
