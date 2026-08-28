"""Logique pure de la synthese PDF (`reports/synthese-pays-basque.pdf`,
`pipeline/07_report.py`) -- aucune I/O, aucun rendu.

Seams :

  - `appariement_par_mutation` : effectif de mutations residentielles par statut
    d'appariement (plie les lignes-lots de `dvf_dpe_matched` par mutation).
  - `evolution` : variation du prix/m2 moyen entre une annee de depart et l'annee
    de fin, pour plusieurs fenetres (10 / 5 / 1 an). Une fenetre non calculable
    (annee absente de la serie, prix de depart nul) est RETOURNEE a part avec son
    motif -- jamais remplacee par une valeur inventee (CLAUDE.md : exposer les
    zones d'incertitude, pas les masquer).
  - `decote_dpe` : prix/m2 moyen par (commune, type_local, etiquette_dpe) et
    ecart % vs la classe de reference (D par defaut). Consomme les points de
    `impact_dpe_slice` (deja replies au niveau mutation, post-reforme, habitation
    seulement). Le rendu du graphe montre que cet ecart brut est domine par la
    localisation, pas par l'etiquette -- ce module ne fait que le calcul.
"""

from __future__ import annotations

from collections.abc import Sequence

from pipeline.lib.aggregate import aggregate_by
from pipeline.lib.mutations import HABITATION_TYPES, mutation_key

ETIQUETTES = ("A", "B", "C", "D", "E", "F", "G")

# Priorite pour resumer en un seul statut les lots d'une meme mutation (une
# mutation multi-lots peut avoir un lot apparie et un autre non).
_RANG_STATUT = {"trouve": 3, "resolu_consensus": 2, "ambigu": 1, "non_trouve": 0}


def appariement_par_mutation(matched: list[dict], communes: Sequence[str]) -> dict[str, int]:
    """Effectif de MUTATIONS residentielles par statut d'appariement, pas de
    lignes-lots.

    `dvf_dpe_matched` porte une ligne par lot DVF (04_join) et n'est pas dedupliquee
    (02_clean_dvf) : compter les lignes gonfle le denominateur (garages, lots
    commerciaux) et compte N fois une vente multi-lots. On plie par `mutation_key`
    en ne gardant que les lots d'habitation (Appartement / Maison) et, par mutation,
    le meilleur statut observe (`_RANG_STATUT`). Une mutation sans lot d'habitation
    est absente du resultat.
    """
    retenus = set(communes)
    best: dict[tuple, str] = {}
    for row in matched:
        if row.get("commune") not in retenus or row.get("type_local") not in HABITATION_TYPES:
            continue
        key = mutation_key(row)
        statut = row.get("match_status")
        if key not in best or _RANG_STATUT.get(statut, -1) > _RANG_STATUT.get(best[key], -1):
            best[key] = statut
    tally: dict[str, int] = {}
    for statut in best.values():
        tally[statut] = tally.get(statut, 0) + 1
    return tally


def evolution(
    prix_par_annee: dict[str, float],
    *,
    fin: str,
    fenetres: Sequence[int],
) -> tuple[list[dict], list[dict]]:
    """Pour chaque fenetre de `fenetres` (en annees), compare le prix/m2 moyen de
    `str(int(fin) - fenetre)` a celui de `fin`.

    Retourne `(calculees, sautees)` :

      - `calculees` : `{"fenetre_ans", "annee_debut", "annee_fin", "prix_debut",
        "prix_fin", "variation_eur", "variation_pct"}`, dans l'ordre de `fenetres`.
      - `sautees` : `{"fenetre_ans", "annee_debut", "raison"}` pour les fenetres
        non calculables -- annee de fin absente, annee de depart absente, prix de
        depart nul (pas de division par zero).
    """
    calculees: list[dict] = []
    sautees: list[dict] = []
    prix_fin = prix_par_annee.get(fin)

    for fenetre in fenetres:
        annee_debut = str(int(fin) - fenetre)
        prix_debut = prix_par_annee.get(annee_debut)

        raison = (
            "annee de fin absente"
            if prix_fin is None
            else "annee de depart absente"
            if prix_debut is None
            else "prix de depart nul"
            if prix_debut == 0
            else None
        )
        if raison is not None:
            sautees.append({"fenetre_ans": fenetre, "annee_debut": annee_debut, "raison": raison})
            continue

        calculees.append(
            {
                "fenetre_ans": fenetre,
                "annee_debut": annee_debut,
                "annee_fin": fin,
                "prix_debut": prix_debut,
                "prix_fin": prix_fin,
                "variation_eur": prix_fin - prix_debut,
                "variation_pct": (prix_fin - prix_debut) / prix_debut * 100,
            }
        )

    return calculees, sautees


def evolutions_synthese(
    prix_par_annee: dict[str, float],
    *,
    fin: str,
    fenetres_courtes: Sequence[int] = (1, 5),
) -> tuple[list[dict], list[dict]]:
    """`evolution` pour les fenetres courtes PLUS une fenetre "longue" allant de la
    premiere annee presente dans la serie jusqu'a `fin`.

    Le fichier DVF du projet commence en 2016 : il n'y a pas de fenetre 10 ans
    pleine. Plutot qu'afficher une case "non calcule", la synthese montre la plus
    longue variation reellement disponible (p. ex. 2016 -> 2025). Si la serie est
    vide ou ne remonte pas plus loin que la plus grande fenetre courte, seules les
    fenetres courtes sont renvoyees.
    """
    fenetres = tuple(fenetres_courtes)
    if prix_par_annee:
        fenetre_longue = int(fin) - int(min(prix_par_annee))
        if fenetre_longue > max(fenetres_courtes):
            fenetres = (*fenetres, fenetre_longue)
    return evolution(prix_par_annee, fin=fin, fenetres=fenetres)


def decote_dpe(points: list[dict], *, reference: str = "D") -> list[dict]:
    """Agrege `points` (sortie de `impact_dpe_slice`) par (commune, type_local,
    etiquette_dpe) et ajoute `ecart_pct` = ecart relatif du prix/m2 moyen de la
    classe vs celui de la classe `reference` du meme (commune, type_local).

    `ecart_pct` vaut `None` si la classe de reference est absente de ce groupe
    (commune, type_local). Lignes triees par (commune, type_local, etiquette).
    """
    agg = aggregate_by(points, ["commune", "type_local", "etiquette_dpe"])

    ref_par_groupe: dict[tuple, float] = {
        (row["commune"], row["type_local"]): row["moyenne"]
        for row in agg
        if row["etiquette_dpe"] == reference
    }

    rows: list[dict] = []
    for row in agg:
        pm2_ref = ref_par_groupe.get((row["commune"], row["type_local"]))
        ecart_pct = None if pm2_ref in (None, 0) else (row["moyenne"] - pm2_ref) / pm2_ref * 100
        rows.append(
            {
                "commune": row["commune"],
                "type_local": row["type_local"],
                "etiquette_dpe": row["etiquette_dpe"],
                "n": row["n"],
                "pm2_moyen": row["moyenne"],
                "ecart_pct": ecart_pct,
            }
        )

    return rows
