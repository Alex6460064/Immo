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

La logique pure (prix/m2, groupement) est testee sans I/O dans
pipeline/lib/aggregate.py -- ce script ne fait que le cablage et le rapport.

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
restent visibles dans dvf_dpe_matched.parquet
et sont comptees dans le resume ci-dessous -- pas supprimees, juste hors de cet
agregat. Le decalage residuel (vente 2021-2022 / DPE 2024) est porte comme
avertissement sur la vue du dashboard (user story #34).

--- Choix documente : type de bien = dimension de groupement, pas un filtre ---
`type_local` (Appartement / Maison / Local commercial / Dependance) est une cle
de groupement des 3 agregats -- aucune mutation n'est exclue sur ce critere
(CLAUDE.md : pas de suppression silencieuse). Le dashboard filtre maison /
appartement cote lecture (user story #35) ; chaque groupe porte son `n=`, donc
les petits groupes (Dependance) restent visibles plutot que masques.

--- Valeurs de prix/m2 extremes ---
DVF ne deduplique pas une mutation multi-lots (maison + garage = 2 lignes, meme
prix total, surfaces differentes -> prix/m2 aberrant sur la ligne du petit lot).
Le traitement avance des aberrations est Out of Scope (issue #1). On ne filtre
donc PAS : la MEDIANE est la statistique de reference (robuste), la moyenne est
fournie mais sensible a ces lignes. Le nombre de lignes hors [200, 30000] EUR/m2
est affiche dans le resume pour rester visible.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.lib.aggregate import (  # noqa: E402
    IMPACT_DPE_STATUSES,
    aggregate_by,
    impact_dpe_rows,
    price_per_m2,
)
from pipeline.lib.clean_dpe import POST_REFORM_CUTOFF  # noqa: E402
from pipeline.lib.parquet_io import read_parquet_rows, write_parquet_rows  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
MATCHED_PATH = ROOT / "data" / "processed" / "dvf_dpe_matched.parquet"
IRIS_PATH = ROOT / "data" / "processed" / "dvf_iris.parquet"
OUT_MARCHE = ROOT / "data" / "processed" / "agg_marche.parquet"
OUT_DPE = ROOT / "data" / "processed" / "agg_dpe.parquet"
OUT_IRIS = ROOT / "data" / "processed" / "agg_iris.parquet"

_SANITY_MIN, _SANITY_MAX = 200.0, 30_000.0

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


def _enrich_rows(rows: list[dict]) -> list[dict]:
    """Ajoute `prix_m2` (prix / surface) et `annee` (millesime de la mutation) a
    chaque ligne. Ne filtre rien : le type de bien reste une dimension de
    groupement, jamais un motif d'exclusion silencieuse (CLAUDE.md)."""
    out = []
    for row in rows:
        enriched = dict(row)
        enriched["prix_m2"] = price_per_m2(row.get("prix"), row.get("surface"))
        enriched["annee"] = (row.get("date_mutation") or "")[:4] or None
        out.append(enriched)
    return out


def _agg_types(*group_keys: str) -> dict[str, str]:
    """Sous-ensemble ordonne de _AGG_COLUMN_TYPES : cles de groupe + n/moyenne/mediane.
    Chaque table n'ecrit que ses propres colonnes (pas de colonnes NULL parasites)."""
    return {c: _AGG_COLUMN_TYPES[c] for c in (*group_keys, "n", "moyenne", "mediane")}


def _count_extremes(rows: list[dict]) -> int:
    return sum(
        1
        for r in rows
        if r.get("prix_m2") is not None and not (_SANITY_MIN <= r["prix_m2"] <= _SANITY_MAX)
    )


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

    matched = _enrich_rows(
        read_parquet_rows(
            MATCHED_PATH,
            [
                "commune",
                "date_mutation",
                "type_local",
                "surface",
                "prix",
                "match_status",
                "etiquette_dpe",
            ],
        )
    )
    iris = _enrich_rows(
        read_parquet_rows(
            IRIS_PATH,
            ["commune", "date_mutation", "type_local", "surface", "prix", "code_iris", "nom_iris"],
        )
    )

    agg_marche = aggregate_by(matched, ["commune", "annee", "type_local"])
    impact_rows = impact_dpe_rows(matched, POST_REFORM_CUTOFF)
    agg_dpe = aggregate_by(impact_rows, ["etiquette_dpe", "type_local"])
    agg_iris = aggregate_by(
        [r for r in iris if r.get("code_iris") is not None],
        ["code_iris", "nom_iris", "type_local"],
    )

    write_parquet_rows(agg_marche, _agg_types("commune", "annee", "type_local"), OUT_MARCHE)
    write_parquet_rows(agg_dpe, _agg_types("etiquette_dpe", "type_local"), OUT_DPE)
    write_parquet_rows(agg_iris, _agg_types("code_iris", "nom_iris", "type_local"), OUT_IRIS)

    matched_usable = sum(1 for r in matched if r.get("prix_m2") is not None)
    etiquette_usable = sum(
        1
        for r in matched
        if r.get("prix_m2") is not None and r.get("match_status") in IMPACT_DPE_STATUSES
    )
    impact_usable = sum(1 for r in impact_rows if r.get("prix_m2") is not None)
    impact_consensus = sum(
        1
        for r in impact_rows
        if r.get("prix_m2") is not None and r.get("match_status") == "resolu_consensus"
    )

    print("=== Rapport agregation (T12 / #13 ; #23 : 4e etat resolu_consensus) ===")
    print(f"  Mutations avec un prix/m2 exploitable    : {matched_usable}")
    print(f"    dont etiquette certaine (trouve + resolu_consensus) : {etiquette_usable}")
    print(f"    dont mutation >= {POST_REFORM_CUTOFF} (retenu pour agg_dpe) : {impact_usable}")
    print(f"        dont resolu par consensus d'etiquette : {impact_consensus}")
    print(
        f"    dont mutation anterieure (exclu d'agg_dpe, cf. en-tete) : "
        f"{etiquette_usable - impact_usable}"
    )
    print(
        f"  Lignes prix/m2 hors [{_SANITY_MIN:.0f}, {_SANITY_MAX:.0f}] EUR/m2 "
        f"(conservees, cf. en-tete) : {_count_extremes(matched)}"
    )

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
