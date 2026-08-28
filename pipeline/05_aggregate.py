"""Produit les 3 tables d'agregats du dashboard (issue #13) a partir de
data/processed/dvf_dpe_matched.parquet (04_join) et data/processed/dvf_iris.parquet
(04b_join_iris) :

  - data/processed/agg_marche.parquet : prix/m2 moyen+median par commune, annee,
    type de bien -- toutes mutations. Vue "Marche" du dashboard.
  - data/processed/agg_dpe.parquet    : prix/m2 moyen+median par etiquette DPE et
    type de bien, sur le sous-ensemble a etiquette certaine ("trouve" OU
    "resolu_consensus", #23) ET mutation >= juillet 2021 (voir ci-dessous). Vue
    "Impact DPE".
  - data/processed/agg_iris.parquet   : prix/m2 moyen+median par IRIS et type de
    bien -- toutes mutations rattachees. Carte choroplethe.

La logique pure vit dans pipeline/lib/mutations.py (repli mutation + garde-fous)
et pipeline/lib/aggregate.py (groupement) -- ce script ne fait que le cablage et
le rapport.

--- Choix documente : prix/m2 calcule au niveau MUTATION (issue #26, ADR 0006) ---
`Valeur fonciere` DVF est un montant de mutation, recopie sur chaque ligne-lot du
brut DGFiP. Diviser ce montant par la surface d'un seul lot gonflait les ventes en
bloc (promoteur) a ~100 000 EUR/m2. `mutation_price_points` replie donc les lignes
par mutation ((date, code_insee, no_disposition, prix)) AVANT tout calcul : un
point prix/m2 par mutation (= prix / somme des surfaces habitation), habitation =
Appartement + Maison. Sont ecartes et COMPTES dans le resume : mutations mixtes
(habitation + commercial), `nature_mutation` hors {Vente, VEFA, Adjudication},
prix/m2 hors [200, 30 000]. `n` compte desormais des TRANSACTIONS, pas des lots.

--- Choix documente : plage d'annees de la vue "Marche" ---
Toutes les mutations disponibles (2016+), PAS "2021+". Le commentaire de l'issue
#13 disait "2021+" ; il est anterieur a ADR 0005 qui a (re)introduit le DVF
historique 2016-2020 via le miroir cquest, justement pour donner une tendance de
prix sur ~10 ans a la vue "Marche". ADR 0005 fait foi.

--- Choix documente : vue "Impact DPE" limitee aux paires temporellement coherentes ---
Le DPE post-reforme n'existe qu'a partir de juillet 2021. Or l'algorithme
d'appariement (adresse + surface, ADR 0003) rapproche aussi des mutations
ANTERIEURES d'un DPE etabli bien plus tard sur la meme adresse -- sur le jeu
courant, ~53 % des "trouve" sont des mutations < 2021-07. Apparier un prix de 2017
a un DPE de 2023 ne mesure rien de l'effet du DPE sur ce prix (l'acheteur de 2017
ne l'a jamais vu). agg_dpe est donc restreint aux mutations >= POST_REFORM_CUTOFF
(2021-07-01). Le filtre d'etat retient "trouve" ET "resolu_consensus" (#23 : ambigu
sauve par consensus d'etiquette -- l'etiquette, seule dimension consommee ici, est
certaine) ; le resume affiche "dont resolu par consensus". Ces paires anterieures
restent visibles dans dvf_dpe_matched.parquet et sont comptees dans le resume
ci-dessous -- pas supprimees, juste hors de cet agregat. Le decalage residuel
(vente 2021-2022 / DPE 2024) est porte comme avertissement sur la vue du dashboard
(user story #34).

--- Choix documente : agg_dpe = un point par (mutation, etiquette) (#26) ---
Une vente en bloc apparie chaque lot a son propre DPE : sans repli, un deal
institutionnel de 70 lots pesait 70 points dans une classe DPE. `agg_dpe` emet
donc un point par (mutation, etiquette_dpe) -- le denominateur du prix/m2 reste la
surface habitation de TOUTE la mutation.

--- Choix documente : agregats prix/m2 = habitation seulement (#26, ADR 0006) ---
Avant #26 les 3 agregats groupaient par `type_local` sans rien exclure -- une
ligne "Local industriel. commercial ou assimile" ou "Dependance" formait son
propre groupe avec son `n`. Depuis le repli mutation, le prix/m2 est une propriete
du LOGEMENT : `mutation_price_points` n'emet un point que pour les mutations
mono-type habitation (Appartement / Maison). Les mutations sans habitation (vente
pure de local commercial, cession de dependance) ne produisent donc plus de ligne
d'agregat -- ce n'est pas une suppression silencieuse : elles sont comptees
`sans_habitation` dans le resume, et `points + mixte + nature + hors_bande +
sans_habitation` reconcilie avec le nombre de mutations distinctes. Le dashboard
n'exposait de toute facon que maison / appartement (user story #35).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.lib.aggregate import IMPACT_DPE_STATUSES, aggregate_by, impact_dpe_rows  # noqa: E402
from pipeline.lib.clean_dpe import POST_REFORM_CUTOFF  # noqa: E402
from pipeline.lib.mutations import (  # noqa: E402
    NATURES_RETENUES,
    PRIX_M2_MAX,
    PRIX_M2_MIN,
    mutation_price_points,
)
from pipeline.lib.parquet_io import read_parquet_rows, write_parquet_rows  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
MATCHED_PATH = ROOT / "data" / "processed" / "dvf_dpe_matched.parquet"
IRIS_PATH = ROOT / "data" / "processed" / "dvf_iris.parquet"
OUT_MARCHE = ROOT / "data" / "processed" / "agg_marche.parquet"
OUT_DPE = ROOT / "data" / "processed" / "agg_dpe.parquet"
OUT_IRIS = ROOT / "data" / "processed" / "agg_iris.parquet"

# Colonnes lues en plus des dimensions d'agregat : la cle mutation (#26) a besoin
# de code_insee / no_disposition / prix, la regle A de nature_mutation.
_MUTATION_FIELDS = ["code_insee", "no_disposition", "nature_mutation", "date_mutation", "prix"]
_COMMON_FIELDS = [*_MUTATION_FIELDS, "commune", "type_local", "surface"]
_MATCHED_FIELDS = [*_COMMON_FIELDS, "match_status", "etiquette_dpe"]
_IRIS_FIELDS = [*_COMMON_FIELDS, "code_iris", "nom_iris"]

_AGG_COLUMN_TYPES = {
    "commune": "VARCHAR",
    "annee": "VARCHAR",
    "type_local": "VARCHAR",
    "etiquette_dpe": "VARCHAR",
    "code_iris": "VARCHAR",
    "nom_iris": "VARCHAR",
    "n": "BIGINT",
    "moyenne": "DOUBLE",
    "mediane": "DOUBLE",
}


def _agg_types(*group_keys: str) -> dict[str, str]:
    """Sous-ensemble ordonne de _AGG_COLUMN_TYPES : cles de groupe + n/moyenne/mediane.
    Chaque table n'ecrit que ses propres colonnes (pas de colonnes NULL parasites)."""
    return {c: _AGG_COLUMN_TYPES[c] for c in (*group_keys, "n", "moyenne", "mediane")}


def _print_exclusions(title: str, n_points: int, exclusions: dict[str, int]) -> None:
    total = n_points + sum(exclusions.values())
    print(f"\n  {title}  ({total} mutations distinctes)")
    print(f"    points prix/m2 retenus (1 par mutation)       : {n_points}")
    print(f"    ecartees -- mixte (habitation + commercial)   : {exclusions['mixte']}")
    print(f"    ecartees -- nature hors liste                 : {exclusions['nature']}")
    print(
        f"    ecartees -- prix/m2 hors [{PRIX_M2_MIN:.0f}, {PRIX_M2_MAX:.0f}]         : "
        f"{exclusions['hors_bande']}"
    )
    print(f"    sans lot habitation (local commercial seul)   : {exclusions['sans_habitation']}")


def _print_table(title: str, rows: list[dict], keys: list[str], preview: int = 6) -> None:
    print(f"\n  {title} : {len(rows)} lignes")
    for row in rows[:preview]:
        label = " / ".join(str(row[k]) for k in keys)
        print(
            f"    {label:<34} n={row['n']:>5}  "
            f"median={row['mediane']:>10.0f}  moyenne={row['moyenne']:>10.0f} EUR/m2"
        )
    if len(rows) > preview:
        print(f"    ... (+{len(rows) - preview})")


def main() -> None:
    for path, prev in ((MATCHED_PATH, "04_join.py"), (IRIS_PATH, "04b_join_iris.py")):
        if not path.exists():
            print(f"ERREUR : fichier introuvable : {path}", file=sys.stderr)
            print(f"  Lancer d'abord : python pipeline/{prev}", file=sys.stderr)
            sys.exit(1)

    if all(p.exists() and p.stat().st_size > 0 for p in (OUT_MARCHE, OUT_DPE, OUT_IRIS)):
        print(
            "[05_aggregate] Les 3 tables d'agregats existent deja -- calcul saute "
            "(idempotent). Supprimer les fichiers agg_*.parquet pour forcer un re-run."
        )
        return

    matched = read_parquet_rows(MATCHED_PATH, _MATCHED_FIELDS)
    iris = read_parquet_rows(IRIS_PATH, _IRIS_FIELDS)

    # agg_marche / agg_iris : un point prix/m2 par mutation (extra_keys vide).
    marche_points, marche_excl = mutation_price_points(matched)
    agg_marche = aggregate_by(marche_points, ["commune", "annee", "type_local"])

    # Repli AVANT le filtre code_iris : sinon un lot non geocode d'une mutation
    # multi-lots serait retire du denominateur (surface). Tous les lots d'une
    # mutation partagent l'adresse donc l'IRIS -- on filtre les points, pas les lignes.
    iris_points_all, iris_excl = mutation_price_points(iris)
    iris_points = [p for p in iris_points_all if p.get("code_iris") is not None]
    iris_hors_perimetre = len(iris_points_all) - len(iris_points)
    agg_iris = aggregate_by(iris_points, ["code_iris", "nom_iris", "type_local"])

    # agg_dpe : un point par (mutation, etiquette) -- puis filtre etiquette
    # certaine + mutation post-reforme (impact_dpe_rows).
    dpe_points, dpe_excl = mutation_price_points(
        matched, extra_keys=("etiquette_dpe", "match_status")
    )
    impact_rows = impact_dpe_rows(dpe_points, POST_REFORM_CUTOFF)
    agg_dpe = aggregate_by(impact_rows, ["etiquette_dpe", "type_local"])

    write_parquet_rows(agg_marche, _agg_types("commune", "annee", "type_local"), OUT_MARCHE)
    write_parquet_rows(agg_dpe, _agg_types("etiquette_dpe", "type_local"), OUT_DPE)
    write_parquet_rows(agg_iris, _agg_types("code_iris", "nom_iris", "type_local"), OUT_IRIS)

    impact_consensus = sum(1 for r in impact_rows if r.get("match_status") == "resolu_consensus")
    etiquette_certaine = sum(1 for r in dpe_points if r.get("match_status") in IMPACT_DPE_STATUSES)
    etiquette_pre_reforme = etiquette_certaine - len(impact_rows)

    print("=== Rapport agregation (T12 / #13 ; #23 ; repli mutation #26 / ADR 0006) ===")
    print(f"  Lignes-lots lues (matched)                   : {len(matched)}")
    print(f"  Natures retenues                             : {', '.join(NATURES_RETENUES)}")
    _print_exclusions("Marche (matched) :", len(marche_points), marche_excl)
    _print_exclusions("Carte IRIS (toutes mutations) :", len(iris_points_all), iris_excl)
    print(f"    dont hors perimetre IRIS (non geocodes, hors agg_iris) : {iris_hors_perimetre}")
    print("\n  Impact DPE :")
    print(f"    points (mutation x etiquette) retenus       : {len(dpe_points)}")
    print(f"      dont etiquette certaine (trouve + resolu_consensus) : {etiquette_certaine}")
    print(f"        dont mutation >= {POST_REFORM_CUTOFF} (agg_dpe) : {len(impact_rows)}")
    print(f"          dont resolu par consensus d'etiquette : {impact_consensus}")
    print(
        f"        dont mutation anterieure (exclu d'agg_dpe, cf. en-tete) : {etiquette_pre_reforme}"
    )
    print(f"      points (x etiquette) ecartes -- mixte     : {dpe_excl['mixte']}")
    print(f"      points (x etiquette) ecartes -- nature    : {dpe_excl['nature']}")
    print(f"      points (x etiquette) ecartes -- hors bande : {dpe_excl['hors_bande']}")

    _print_table(
        "agg_marche (commune / annee / type)", agg_marche, ["commune", "annee", "type_local"]
    )
    _print_table("agg_dpe (etiquette / type)", agg_dpe, ["etiquette_dpe", "type_local"], preview=16)
    _print_table(
        "agg_iris (code_iris / nom / type)", agg_iris, ["code_iris", "nom_iris", "type_local"]
    )

    if not agg_marche or not agg_dpe or not agg_iris:
        print(
            "ATTENTION : au moins une table d'agregat est vide -- verifier les "
            "fichiers d'entree et le filtre residentiel.",
            file=sys.stderr,
        )


if __name__ == "__main__":
    main()
