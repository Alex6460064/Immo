"""Repli des lignes-lots DVF a la granularite mutation avant tout calcul de
prix/m2 (issue #26) -- logique pure, aucune I/O.

Le fichier brut DGFiP porte une ligne par lot ; `Valeur fonciere` y est le
montant de la **mutation entiere**, recopie verbatim sur chaque ligne. Diviser
ce montant par la surface d'un seul lot (comportement d'avant #26) gonflait les
ventes en bloc (promoteur achetant une residence) a ~100 000 EUR/m2, repete sur
des dizaines de lignes qui ecrasaient la mediane de leur IRIS.

`mutation_price_points` regroupe les lignes par mutation et n'emet qu'un point
prix/m2 par mutation (ou par (mutation, extra_keys) pour la vue Impact DPE) :

  - cle mutation      : (date_mutation, code_insee, no_disposition, prix)
  - habitation        : Appartement + Maison ; le prix/m2 = prix / somme des
                        surfaces habitation de la mutation
  - regle C           : point emis seulement si la mutation est mono-type
                        habitation ; lignes Dependance ignorees (ni au numerateur
                        ni au test de purete) ; une mutation habitation+commercial
                        (ou Appartement+Maison) est exclue et comptee
  - regle A (garde-fous, comptes par motif) :
      * nature_mutation dans NATURES_RETENUES
      * prix/m2 dans [PRIX_M2_MIN, PRIX_M2_MAX]

Les mutations sans aucun lot habitation ne produisent aucun point (le prix/m2 du
projet ne concerne que le logement) mais sont comptees `sans_habitation` pour que
`points + mixte + nature + hors_bande + sans_habitation` reconcilie avec le nombre
de mutations distinctes -- coherence des totaux (CLAUDE.md, protocole anti-bug).

Voir ADR 0006 -- ceci remplace la note "hors scope #1" de l'en-tete de
`pipeline/05_aggregate.py`.
"""

from __future__ import annotations

from collections import defaultdict

HABITATION_TYPES: frozenset[str] = frozenset({"Appartement", "Maison"})
DEPENDANCE_TYPE = "Dépendance"

# `nature_mutation` porteuses d'un prix de marche en numeraire. Exclut "Echange"
# (pas de prix cash) et "Vente terrain a batir" (pas de bati). "Adjudication"
# (vente aux encheres) est un vrai prix.
NATURES_RETENUES: tuple[str, ...] = (
    "Vente",
    "Vente en l'état futur d'achèvement",
    "Adjudication",
)

# Bande de coherence du prix/m2 (etudes DVF usuelles). En dehors : saisie DGFiP
# douteuse (cession symbolique a 1 EUR, surface bati grossierement sous-declaree).
PRIX_M2_MIN = 200.0
PRIX_M2_MAX = 30_000.0

_EXCLUSION_MOTIFS = ("mixte", "nature", "hors_bande", "sans_habitation")


def mutation_key(row: dict) -> tuple:
    """Cle d'identite d'une mutation : `(date_mutation, code_insee,
    no_disposition, prix)`. `identifiant_document` est NULL partout dans le brut
    DGFiP courant (et dans le miroir historique), d'ou cette cle synthetique --
    voir ADR 0006. Tolerante aux composantes manquantes (None dans le tuple)."""
    return (
        row.get("date_mutation"),
        row.get("code_insee"),
        row.get("no_disposition"),
        row.get("prix"),
    )


def _annee(date_mutation: str | None) -> str | None:
    return (date_mutation or "")[:4] or None


def mutation_price_points(
    rows: list[dict], *, extra_keys: tuple[str, ...] = ()
) -> tuple[list[dict], dict[str, int]]:
    """Replie `rows` (lignes-lots DVF) en points prix/m2 au niveau mutation.

    Retourne `(points, exclusions)` :

      - `points` : une copie d'une ligne representative par (mutation, valeurs
        des `extra_keys`), avec `prix_m2` (niveau mutation), `annee` (millesime)
        et `n_lots` (nb de lots habitation de la mutation) ajoutes/ecrases. Tous
        les points d'une meme mutation portent le MÊME `prix_m2`.
      - `exclusions` : `{"mixte": n, "nature": n, "hors_bande": n,
        "sans_habitation": n}` -- une entree par mutation NON representee dans
        `points`, par motif (un seul motif par mutation ; priorite
        sans_habitation > mixte > nature > hors_bande). `points` (compte de
        mutations distinctes emises, hors `extra_keys`) + somme des exclusions =
        nombre de mutations distinctes en entree.

    `extra_keys` : dimensions qui, combinees a la cle mutation, definissent un
    point distinct. `()` (defaut) -> un point par mutation, pour `agg_marche` /
    `agg_iris`. `("etiquette_dpe", "match_status")` -> un point par etiquette
    pour `agg_dpe` : le denominateur reste la surface habitation de TOUTE la
    mutation, jamais celle du seul sous-groupe.
    """
    by_mutation: dict[tuple, list[dict]] = defaultdict(list)
    for row in rows:
        by_mutation[mutation_key(row)].append(row)

    points: list[dict] = []
    exclusions = dict.fromkeys(_EXCLUSION_MOTIFS, 0)

    for lot_rows in by_mutation.values():
        habitation = [r for r in lot_rows if r.get("type_local") in HABITATION_TYPES]
        if not habitation:
            exclusions["sans_habitation"] += 1
            continue

        autre_bati = [
            r
            for r in lot_rows
            if r.get("type_local") not in HABITATION_TYPES
            and r.get("type_local") != DEPENDANCE_TYPE
            and (r.get("surface") or 0) > 0
        ]
        types_habitation = {r.get("type_local") for r in habitation}
        if autre_bati or len(types_habitation) > 1:
            exclusions["mixte"] += 1
            continue

        if habitation[0].get("nature_mutation") not in NATURES_RETENUES:
            exclusions["nature"] += 1
            continue

        surface_habitation = sum(r.get("surface") or 0.0 for r in habitation)
        prix = habitation[0].get("prix")
        if not surface_habitation or prix is None:
            continue
        prix_m2 = prix / surface_habitation
        if not (PRIX_M2_MIN <= prix_m2 <= PRIX_M2_MAX):
            exclusions["hors_bande"] += 1
            continue

        subgroups: dict[tuple, dict] = {}
        for r in habitation:
            subgroups.setdefault(tuple(r.get(k) for k in extra_keys), r)
        for representative in subgroups.values():
            point = dict(representative)
            point["prix_m2"] = prix_m2
            point["annee"] = _annee(representative.get("date_mutation"))
            point["n_lots"] = len(habitation)
            points.append(point)

    return points, exclusions
