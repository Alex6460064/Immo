"""Tests for pipeline.lib.normalize_address.normalize_address.

Written before the implementation (TDD, per CLAUDE.md).
"""

from pipeline.lib.normalize_address import normalize_address


class TestEmptyAndWhitespace:
    def test_empty_string(self):
        assert normalize_address("") == ""

    def test_whitespace_only(self):
        assert normalize_address("   ") == ""

    def test_collapses_multiple_internal_spaces(self):
        assert normalize_address("12    RUE   DE  LA PAIX") == "12 RUE DE LA PAIX"

    def test_strips_leading_and_trailing_whitespace(self):
        assert normalize_address("  12 RUE DE LA PAIX  ") == "12 RUE DE LA PAIX"

    def test_collapses_tabs_and_newlines(self):
        assert normalize_address("12\tRUE\nDE LA PAIX") == "12 RUE DE LA PAIX"


class TestAlreadyNormalized:
    def test_already_uppercase_full_words_unchanged(self):
        assert normalize_address("12 RUE DE LA PAIX") == "12 RUE DE LA PAIX"

    def test_idempotent_on_simple_address(self):
        once = normalize_address("5 av. du marechal foch")
        twice = normalize_address(once)
        assert once == twice

    def test_idempotent_on_saint_abbreviation(self):
        once = normalize_address("RUE ST JEAN")
        twice = normalize_address(once)
        assert once == twice

    def test_idempotent_on_sainte_abbreviation(self):
        once = normalize_address("IMPASSE STE MARIE")
        twice = normalize_address(once)
        assert once == twice


class TestCase:
    def test_lowercase_is_uppercased(self):
        assert normalize_address("12 rue de la paix") == "12 RUE DE LA PAIX"

    def test_mixed_case_is_uppercased(self):
        assert normalize_address("12 Rue De La Paix") == "12 RUE DE LA PAIX"


class TestAccents:
    def test_e_acute_and_e_grave(self):
        assert normalize_address("15 Général de Gaulle") == "15 GENERAL DE GAULLE"

    def test_e_circumflex_and_l_apostrophe(self):
        assert normalize_address("5 RUE DE L'ÉGLISE") == "5 RUE DE L'EGLISE"

    def test_c_cedilla(self):
        assert normalize_address("RUE DU FAÇONNIER") == "RUE DU FACONNIER"

    def test_i_diaeresis(self):
        assert normalize_address("CHEMIN DE NAÏADES") == "CHEMIN DE NAIADES"


class TestAbbreviations:
    def test_r_dot_to_rue(self):
        assert normalize_address("12 R. DE LA PAIX") == "12 RUE DE LA PAIX"

    def test_r_no_dot_to_rue(self):
        assert normalize_address("12 R DE LA PAIX") == "12 RUE DE LA PAIX"

    def test_av_dot_to_avenue(self):
        assert normalize_address("5 AV. DU MARECHAL FOCH") == "5 AVENUE DU MARECHAL FOCH"

    def test_ave_to_avenue(self):
        assert normalize_address("5 AVE DE BAYONNE") == "5 AVENUE DE BAYONNE"

    def test_bd_to_boulevard(self):
        assert normalize_address("3 BD DE LA REPUBLIQUE") == "3 BOULEVARD DE LA REPUBLIQUE"

    def test_bd_dot_to_boulevard(self):
        assert normalize_address("3 BD. DE LA REPUBLIQUE") == "3 BOULEVARD DE LA REPUBLIQUE"

    def test_pl_dot_to_place(self):
        assert normalize_address("1 PL. DE LA MAIRIE") == "1 PLACE DE LA MAIRIE"

    def test_st_to_saint(self):
        assert normalize_address("RUE ST JEAN") == "RUE SAINT JEAN"

    def test_ste_to_sainte(self):
        assert normalize_address("IMPASSE STE MARIE") == "IMPASSE SAINTE MARIE"

    def test_che_to_chemin(self):
        assert normalize_address("2 CHE DES ECOLIERS") == "2 CHEMIN DES ECOLIERS"

    def test_imp_to_impasse(self):
        assert normalize_address("4 IMP DES LILAS") == "4 IMPASSE DES LILAS"

    def test_rte_to_route(self):
        assert normalize_address("10 RTE DE BAYONNE") == "10 ROUTE DE BAYONNE"

    def test_multiple_abbreviations_in_one_address(self):
        assert normalize_address("12 R. ST JEAN") == "12 RUE SAINT JEAN"

    def test_abbreviation_not_matched_inside_longer_word(self):
        # "AVENUE" already spelled out must not be mangled by the "AV" rule.
        assert normalize_address("5 AVENUE DE BAYONNE") == "5 AVENUE DE BAYONNE"

    def test_saint_word_not_double_expanded(self):
        # "SAINT" already spelled out must not be touched by the "ST" rule.
        assert normalize_address("RUE SAINT JEAN") == "RUE SAINT JEAN"


class TestApostrophesAndPunctuation:
    def test_straight_apostrophe_preserved(self):
        assert normalize_address("2 CHEMIN D'ARCANGUES") == "2 CHEMIN D'ARCANGUES"

    def test_curly_apostrophe_normalized_to_straight(self):
        assert normalize_address("2 CHEMIN D’ARCANGUES") == "2 CHEMIN D'ARCANGUES"

    def test_hyphenated_commune_name_untouched(self):
        assert (
            normalize_address("PLACE DE LA MAIRIE, SAINT-JEAN-DE-LUZ")
            == "PLACE DE LA MAIRIE, SAINT-JEAN-DE-LUZ"
        )
