"""Synthese PDF pour recruteurs -- `reports/synthese-pays-basque.pdf`.

Trois communes (Bayonne, Anglet, Biarritz) : evolution du prix/m2 moyen
(Appartement / Maison) sur ~10 / 5 / 1 an, et prix/m2 moyen par etiquette DPE
depuis la reforme (juillet 2021).

Entrees = instantanes VERSIONNES `data/dashboard/` (agg_marche + dvf_dpe_matched),
pas `data/processed/` : la synthese se regenere sur un clone frais sans rejouer le
pipeline (meme logique que le dashboard, CLAUDE.md "fix en aval").

Rendu : Typst (`pipeline/report/template.typ`), graphes natifs via le paquet
`lilaq`. Ce script ne fait AUCUNE mise en forme -- il calcule les chiffres
(`_build_data`, via les seams purs de `pipeline/lib/report.py`), les serialise en
JSON et lance `typst.compile`. Le paquet pip `typst` embarque le binaire et les
polices : pas d'install systeme.

Reproductibilite bit-a-bit (comme data/dashboard/) : `ignore_system_fonts=True`
(polices bundlees only), `timestamp=0` + `set document(date: none)` cote template,
version `typst` epinglee (pyproject.toml), `lilaq` epingle dans le template. Le
premier `typst.compile` telecharge `lilaq` depuis Typst Universe puis le met en
cache -- pas de re-telechargement ensuite.

--- Choix documente : la page DPE expose le confondant, ne le corrige pas ---
En brut, le prix/m2 par etiquette est domine par la LOCALISATION, pas par la
performance energetique : les passoires (F/G) sont concentrees dans l'ancien de
centre-ville et de front de mer, le plus cher au m2. Resultat : sur ce perimetre,
F/G ressortent souvent AU-DESSUS de A/B/C. La derniere page le dit explicitement
et renvoie la mesure d'une vraie decote (a quartier comparable) a un travail
ulterieur (decote intra-IRIS). Ne jamais presenter ces barres comme une "prime
verte inversee" sans ce cadrage -- CLAUDE.md, priorite #1.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import typst

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.lib.clean_dpe import POST_REFORM_CUTOFF  # noqa: E402
from pipeline.lib.impact_dpe import impact_dpe_slice  # noqa: E402
from pipeline.lib.match_dvf_dpe import IMPACT_DPE_STATUSES  # noqa: E402
from pipeline.lib.parquet_io import read_parquet_rows  # noqa: E402
from pipeline.lib.report import (  # noqa: E402
    ETIQUETTES,
    appariement_par_mutation,
    decote_dpe,
    evolutions_synthese,
)

ROOT = Path(__file__).resolve().parent.parent
DASHBOARD = ROOT / "data" / "dashboard"
AGG_MARCHE = DASHBOARD / "agg_marche.parquet"
MATCHED = DASHBOARD / "dvf_dpe_matched.parquet"
TEMPLATE = ROOT / "pipeline" / "report" / "template.typ"
OUT_PDF = ROOT / "reports" / "synthese-pays-basque.pdf"

# Perimetre de la synthese : les 3 poids lourds du BAB, en majuscules (forme des
# donnees DVF). Sous-ensemble de config/communes.py -- la synthese ne cible pas
# les 16 communes, seulement celles au volume suffisant pour une lecture publique.
VILLES = ("BAYONNE", "ANGLET", "BIARRITZ")
TYPES = ("Appartement", "Maison")
FENETRES_COURTES = (1, 5)
POST_REFORME_LIB = "juillet 2021"

COULEUR_TYPE = {"Appartement": "#1f6feb", "Maison": "#d29922"}

_MATCHED_FIELDS = [
    "commune",
    "code_insee",
    "no_disposition",
    "nature_mutation",
    "date_mutation",
    "type_local",
    "surface",
    "prix",
    "match_status",
    "etiquette_dpe",
]
_MARCHE_FIELDS = ["commune", "annee", "type_local", "n", "moyenne"]


# --------------------------------------------------------------------------- data


def _serie(marche: list[dict], commune: str, type_local: str, champ: str) -> dict:
    return {
        r["annee"]: r[champ]
        for r in marche
        if r["commune"] == commune and r["type_local"] == type_local
    }


def _libelle_fenetre(c: dict) -> str:
    return {1: "1 an", 5: "5 ans"}.get(c["fenetre_ans"], f"depuis {c['annee_debut']}")


def _pct_signe(valeur: float, decimales: int) -> str:
    """`+3.1 %` / `−10.0 %` -- vrai signe moins (U+2212), pas un trait d'union."""
    signe = "+" if valeur >= 0 else "−"
    return f"{signe}{abs(valeur):.{decimales}f} %"


def _serie_data(marche: list[dict], commune: str, type_local: str, fin: str) -> dict | None:
    prix = _serie(marche, commune, type_local, "moyenne")
    if not prix:
        return None
    effectifs = _serie(marche, commune, type_local, "n")
    annees = sorted(prix)
    calculees, sautees = evolutions_synthese(prix, fin=fin, fenetres_courtes=FENETRES_COURTES)
    evolutions = [
        {
            "libelle": _libelle_fenetre(c),
            "prix_debut": c["prix_debut"],
            "prix_fin": c["prix_fin"],
            "variation_pct": c["variation_pct"],
            "variation_txt": _pct_signe(c["variation_pct"], 1),
        }
        for c in calculees
    ]
    return {
        "type": type_local,
        "couleur": COULEUR_TYPE[type_local],
        "annee_debut": annees[0],
        "n_debut": effectifs.get(annees[0], 0),
        "n_fin": effectifs.get(fin, 0),
        "points": [{"annee": a, "prix": prix[a], "n": effectifs.get(a, 0)} for a in annees],
        "evolutions": evolutions,
        "sautees": [{"libelle": f"{s['fenetre_ans']} ans", "raison": s["raison"]} for s in sautees],
    }


def _exemples_ecarts(decote: list[dict]) -> list[str]:
    """Quelques ecarts bruts F/G vs D pour appuyer le texte -- illustre que le
    signe part souvent dans le mauvais sens."""
    lignes = []
    for ville in VILLES:
        for type_local in TYPES:
            par_classe = {
                r["etiquette_dpe"]: r
                for r in decote
                if r["commune"] == ville and r["type_local"] == type_local
            }
            for cls in ("F", "G"):
                r = par_classe.get(cls)
                if r and r["ecart_pct"] is not None:
                    sens = "au-dessus" if r["ecart_pct"] > 0 else "en-dessous"
                    lignes.append(
                        f"{ville.title()} / {type_local} — classe {cls} : "
                        f"{_pct_signe(r['ecart_pct'], 0)} vs classe D ({sens}, n={r['n']})"
                    )
    return lignes


def _dpe_par_commune(decote: list[dict]) -> list[dict]:
    par_commune = []
    for ville in VILLES:
        series = []
        for type_local in TYPES:
            par_classe = {
                r["etiquette_dpe"]: r
                for r in decote
                if r["commune"] == ville and r["type_local"] == type_local
            }
            series.append(
                {
                    "type": type_local,
                    "couleur": COULEUR_TYPE[type_local],
                    "pm2": [
                        round(par_classe.get(e, {}).get("pm2_moyen", 0) or 0) for e in ETIQUETTES
                    ],
                    "n": [par_classe.get(e, {}).get("n", 0) for e in ETIQUETTES],
                }
            )
        par_commune.append({"nom_affiche": ville.title(), "series": series})
    return par_commune


def _build_data(marche: list[dict], matched: list[dict]) -> dict:
    """Assemble le dict serialise vers `template.typ`. Aucune I/O, aucun rendu."""
    annees = sorted({r["annee"] for r in marche})
    fin = max(r["annee"] for r in marche)

    appariement = appariement_par_mutation(matched, VILLES)
    total = sum(appariement.values())
    certains = sum(appariement.get(s, 0) for s in IMPACT_DPE_STATUSES)

    slice_dpe = impact_dpe_slice(
        matched, cutoff=POST_REFORM_CUTOFF, keep=lambda p: p.get("commune") in VILLES
    )
    decote = decote_dpe(slice_dpe.points, reference="D")

    communes = []
    for ville in VILLES:
        series = [s for t in TYPES if (s := _serie_data(marche, ville, t, fin)) is not None]
        communes.append({"nom_affiche": ville.title(), "series": series})

    return {
        "meta": {
            "annee_min": annees[0],
            "annee_max": annees[-1],
            "annee_ref": fin,
            "post_reforme": POST_REFORME_LIB,
            "villes": list(VILLES),
        },
        "appariement": {
            "total": total,
            "certains": certains,
            "taux": 100 * certains / total if total else 0.0,
            "par_statut": appariement,
        },
        "communes": communes,
        "dpe": {
            "par_commune": _dpe_par_commune(decote),
            "exemples_ecarts": _exemples_ecarts(decote),
        },
        "_points_impact": len(slice_dpe.points),
    }


# ------------------------------------------------------------------------- render


def render_pdf(data: dict, out_path: Path) -> None:
    """Compile `template.typ` avec `data` en entree. Options figees pour un PDF
    reproductible bit a bit (cf. docstring module)."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    typst.compile(
        str(TEMPLATE),
        output=str(out_path),
        sys_inputs={"data": json.dumps(data, ensure_ascii=False)},
        ignore_system_fonts=True,
        timestamp=0,
    )


# --------------------------------------------------------------------------- main


def main() -> None:
    for path, prev in (
        (AGG_MARCHE, "05_aggregate.py + 06_publish_dashboard_data.py"),
        (MATCHED, "04_join.py + 06_publish_dashboard_data.py"),
    ):
        if not (path.exists() and path.stat().st_size > 0):
            print(f"ERREUR : fichier introuvable : {path}", file=sys.stderr)
            print(f"  Lancer d'abord : python pipeline/{prev}", file=sys.stderr)
            sys.exit(1)

    marche = [r for r in read_parquet_rows(AGG_MARCHE, _MARCHE_FIELDS) if r["commune"] in VILLES]
    matched = read_parquet_rows(MATCHED, _MATCHED_FIELDS)

    if not marche:
        print(
            f"ERREUR : aucune ligne pour {', '.join(VILLES)} dans {AGG_MARCHE.name}.\n"
            "  Regenerer l'instantane (06_publish_dashboard_data.py) ou verifier la casse "
            "des noms de commune (constante VILLES).",
            file=sys.stderr,
        )
        sys.exit(1)

    data = _build_data(marche, matched)
    render_pdf(data, OUT_PDF)

    n_pages = 3 + len(VILLES)
    print("=== Synthese PDF (pipeline/07_report.py) ===")
    print(f"  Communes            : {', '.join(v.title() for v in VILLES)}")
    print(f"  Annee de reference  : {data['meta']['annee_ref']}")
    print(f"  Points Impact DPE   : {data['_points_impact']} (post-reforme, 3 communes)")
    print(f"  Appariement mutations residentielles : {data['appariement']['par_statut']}")
    print(f"  Pages ecrites       : {n_pages}")
    print(
        f"  Fichier             : {OUT_PDF.relative_to(ROOT)}  "
        f"({OUT_PDF.stat().st_size // 1024} Ko)"
    )


if __name__ == "__main__":
    main()
