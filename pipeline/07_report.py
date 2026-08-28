"""Synthese PDF pour recruteurs -- `reports/synthese-pays-basque.pdf`.

Trois communes (Bayonne, Anglet, Biarritz) : evolution du prix/m2 moyen
(Appartement / Maison) sur ~10 / 5 / 1 an, et prix/m2 moyen par etiquette DPE
depuis la reforme (juillet 2021).

Entrees = instantanes VERSIONNES `data/dashboard/` (agg_marche + dvf_dpe_matched),
pas `data/processed/` : la synthese se regenere sur un clone frais sans rejouer le
pipeline (meme logique que le dashboard, CLAUDE.md "fix en aval").

Rendu : matplotlib + PdfPages (pages graphes + pages texte). La logique pure
(variations %, agregat DPE + ecart vs classe D) vit dans `pipeline/lib/report.py`.

--- Choix documente : la page DPE expose le confondant, ne le corrige pas ---
En brut, le prix/m2 par etiquette est domine par la LOCALISATION, pas par la
performance energetique : les passoires (F/G) sont concentrees dans l'ancien de
centre-ville et de front de mer, le plus cher au m2. Resultat : sur ce perimetre,
F/G ressortent souvent AU-DESSUS de A/B/C. La page 6 le dit explicitement et
renvoie la mesure d'une vraie decote (a quartier comparable) a un travail
ulterieur (decote intra-IRIS). Ne jamais presenter ces barres comme une "prime
verte inversee" sans ce cadrage -- CLAUDE.md, priorite #1.
"""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.backends.backend_pdf import PdfPages  # noqa: E402

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
OUT_PDF = ROOT / "reports" / "synthese-pays-basque.pdf"

# Perimetre de la synthese : les 3 poids lourds du BAB, en majuscules (forme des
# donnees DVF). Sous-ensemble de config/communes.py -- la synthese ne cible pas
# les 16 communes, seulement celles au volume suffisant pour une lecture publique.
VILLES = ("BAYONNE", "ANGLET", "BIARRITZ")
TYPES = ("Appartement", "Maison")
FENETRES_COURTES = (1, 5)

COULEUR_TYPE = {"Appartement": "#1f6feb", "Maison": "#d29922"}
COULEUR_VILLE = {"BAYONNE": "#1f6feb", "ANGLET": "#2da44e", "BIARRITZ": "#cf222e"}

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

SOURCE = (
    "Sources : DVF (DGFiP, fichier brut) + DPE post-réforme (ADEME, "
    "dpe-v2-logements-existants). Prix/m² calculé par mutation (ADR 0006)."
)


# --------------------------------------------------------------------------- data


def _serie_prix(marche: list[dict], commune: str, type_local: str) -> dict[str, float]:
    """{annee: prix/m2 moyen} pour une commune et un type de bien."""
    return {
        r["annee"]: r["moyenne"]
        for r in marche
        if r["commune"] == commune and r["type_local"] == type_local
    }


def _serie_effectifs(marche: list[dict], commune: str, type_local: str) -> dict[str, int]:
    return {
        r["annee"]: r["n"]
        for r in marche
        if r["commune"] == commune and r["type_local"] == type_local
    }


# ------------------------------------------------------------------------- render


_LARGEUR_WRAP = 90
_LIGNE_H = 0.0185


def _lignes_bloc(bloc: str) -> list[str]:
    """Pre-decoupe un bloc en lignes rendues : les lignes courtes (listes, texte
    deja mis en forme) restent verbatim, seul le texte long est rewrappe. Rendre
    la hauteur deterministe -- `wrap=True` de matplotlib rewrappe a l'affichage et
    fait chevaucher les blocs suivants."""
    lignes: list[str] = []
    for para in bloc.split("\n"):
        lignes.extend([para] if len(para) <= _LARGEUR_WRAP else textwrap.wrap(para, _LARGEUR_WRAP))
    return lignes


def _page_texte(pdf: PdfPages, titre: str, blocs: list[str]) -> None:
    fig = plt.figure(figsize=(8.27, 11.69))  # A4 portrait
    fig.text(0.08, 0.95, titre, fontsize=18, fontweight="bold", va="top")
    y = 0.89
    for bloc in blocs:
        lignes = _lignes_bloc(bloc)
        fig.text(0.08, y, "\n".join(lignes), fontsize=10.5, va="top", ha="left")
        y -= _LIGNE_H * len(lignes) + 0.014
    fig.text(0.08, 0.04, SOURCE, fontsize=7.5, color="#57606a", va="bottom")
    pdf.savefig(fig)
    plt.close(fig)


def _page_couverture(pdf: PdfPages, marche: list[dict], appariement: dict[str, int]) -> None:
    annees = sorted({r["annee"] for r in marche})
    total = sum(appariement.values())
    certains = sum(appariement.get(s, 0) for s in IMPACT_DPE_STATUSES)
    taux = 100 * certains / total if total else 0.0
    blocs = [
        "Trois communes du Pays Basque : Bayonne, Anglet, Biarritz.",
        f"Période couverte : {annees[0]}-{annees[-1]} (ventes DVF).\n"
        "DPE : diagnostics post-réforme, méthode en vigueur depuis juillet 2021.",
        "Contenu :\n"
        "  1. Évolution du prix/m² moyen par commune (Appartement / Maison),\n"
        "     variations sur ~10 ans, 5 ans et 1 an.\n"
        "  2. Prix/m² moyen par étiquette DPE (A-G) et par commune depuis 2021,\n"
        "     et ce que ce chiffre brut ne dit pas (biais de localisation).",
        f"Appariement DVF <-> DPE : {certains} / {total} mutations résidentielles des 3 "
        f"communes rapprochées d'un DPE d'étiquette certaine ({taux:.0f} %).\n"
        "Ce taux, structurellement limité par le périmètre DPE post-réforme (une vente "
        "d'avant 2021 n'a de DPE que si un second a été réalisé depuis), est affiché ici "
        "comme une donnée du projet, pas masqué.",
        "Généré par pipeline/07_report.py à partir de l'instantané versionné data/dashboard/.",
    ]
    _page_texte(pdf, "Marché immobilier & performance énergétique", blocs)


def _page_commune(pdf: PdfPages, marche: list[dict], commune: str, fin: str) -> None:
    fig, (ax_courbe, ax_txt) = plt.subplots(
        2, 1, figsize=(8.27, 11.69), gridspec_kw={"height_ratios": [2, 1.5]}
    )

    lignes_txt: list[str] = []
    for type_local in TYPES:
        prix = _serie_prix(marche, commune, type_local)
        effectifs = _serie_effectifs(marche, commune, type_local)
        if not prix:
            continue
        annees = sorted(prix)
        ax_courbe.plot(
            annees,
            [prix[a] for a in annees],
            marker="o",
            label=type_local,
            color=COULEUR_TYPE[type_local],
        )
        calculees, sautees = evolutions_synthese(prix, fin=fin, fenetres_courtes=FENETRES_COURTES)
        lignes_txt.append(
            f"{type_local}  (n {annees[0]}={effectifs.get(annees[0], 0)}, "
            f"n {fin}={effectifs.get(fin, 0)})"
        )
        for c in calculees:
            libelle = (
                "1 an"
                if c["fenetre_ans"] == 1
                else "5 ans"
                if c["fenetre_ans"] == 5
                else f"depuis {c['annee_debut']}"
            )
            signe = "+" if c["variation_pct"] >= 0 else ""
            lignes_txt.append(
                f"   {libelle:<12} {c['prix_debut']:>7.0f} -> {c['prix_fin']:>7.0f} EUR/m2   "
                f"{signe}{c['variation_pct']:.1f} %"
            )
        for s in sautees:
            lignes_txt.append(f"   {s['fenetre_ans']} ans : non calcule ({s['raison']})")
        lignes_txt.append("")

    ax_courbe.set_title(f"{commune.title()} - prix/m² moyen par année", fontweight="bold")
    ax_courbe.set_ylabel("EUR / m²")
    ax_courbe.grid(True, alpha=0.3)
    ax_courbe.legend()

    ax_txt.axis("off")
    ax_txt.text(
        0.0,
        1.0,
        "Variation du prix/m2 moyen (EUR/m2)\n" + "\n".join(lignes_txt),
        fontsize=9.5,
        va="top",
        family="monospace",
    )
    fig.text(0.08, 0.04, SOURCE, fontsize=7.5, color="#57606a")
    fig.tight_layout(rect=(0, 0.05, 1, 1))
    pdf.savefig(fig)
    plt.close(fig)


def _page_dpe_barres(pdf: PdfPages, decote: list[dict]) -> None:
    """Un panneau par commune (echelle propre) : les ecarts entre communes
    (Biarritz ~2x Bayonne) ecraseraient tout gradient DPE sur une echelle
    partagee -- c'est justement le confondant explique page suivante."""
    fig, axes = plt.subplots(len(VILLES), 1, figsize=(8.27, 11.69))
    x = range(len(ETIQUETTES))
    largeur = 0.38
    for ax, ville in zip(axes, VILLES, strict=True):
        for i, type_local in enumerate(TYPES):
            par_classe = {
                r["etiquette_dpe"]: r
                for r in decote
                if r["commune"] == ville and r["type_local"] == type_local
            }
            barres = ax.bar(
                [xi + (i - 0.5) * largeur for xi in x],
                [par_classe.get(e, {}).get("pm2_moyen", 0) for e in ETIQUETTES],
                largeur,
                label=type_local,
                color=COULEUR_TYPE[type_local],
            )
            for rect, e in zip(barres, ETIQUETTES, strict=True):
                n = par_classe.get(e, {}).get("n", 0)
                if n:
                    ax.text(
                        rect.get_x() + rect.get_width() / 2,
                        rect.get_height(),
                        f"n={n}",
                        ha="center",
                        va="bottom",
                        fontsize=6,
                        rotation=90,
                    )
        ax.set_title(
            f"{ville.title()} - prix/m² moyen par étiquette DPE (ventes depuis juillet 2021)",
            fontweight="bold",
            fontsize=10,
        )
        ax.set_xticks(list(x))
        ax.set_xticklabels(ETIQUETTES)
        ax.set_ylabel("EUR / m²")
        ax.grid(True, axis="y", alpha=0.3)
        ax.set_ylim(top=ax.get_ylim()[1] * 1.35)  # place pour les labels n= et la legende
        ax.legend(fontsize=8, loc="upper right")

    fig.text(
        0.08,
        0.02,
        "Lecture prudente : ces barres ne mesurent PAS une décote DPE (voir page suivante).\n"
        + SOURCE,
        fontsize=7.5,
        color="#57606a",
    )
    fig.tight_layout(rect=(0, 0.05, 1, 1))
    pdf.savefig(fig)
    plt.close(fig)


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
                        f"  {ville.title()} / {type_local} - classe {cls} : "
                        f"{r['ecart_pct']:+.0f} % vs classe D ({sens}, n={r['n']})"
                    )
    return lignes


def _page_dpe_synthese(pdf: PdfPages, decote: list[dict]) -> None:
    blocs = [
        "Ce que le graphe précédent ne dit pas",
        "Attendu : à bien comparable, une étiquette F ou G se vend moins cher qu'une "
        "étiquette C ou D (coût des travaux, contrainte de location). Sur ce périmètre, "
        "les barres brutes montrent souvent l'INVERSE.",
        "Pourquoi : l'étiquette DPE est corrélée à la localisation. Les logements "
        "énergivores (F/G) sont surtout de l'ancien de centre-ville et de front de mer -- "
        "les secteurs les plus chers au m². La classe DPE capte donc surtout l'adresse, "
        "pas la performance : le prix/m² par classe mélange deux effets de sens opposés.",
        "Exemples d'écarts bruts (classe vs classe D, même commune / même type) :",
        "\n".join(_exemples_ecarts(decote)) or "  (pas assez d'observations F/G exploitables)",
        "Conclusion : à ce niveau d'agrégation, le signe de l'écart est instable d'une "
        "commune et d'un type à l'autre (les appartements F ressortent légèrement sous la "
        "classe D, mais G repart au-dessus, sur de petits effectifs). Aucune décote DPE "
        "robuste ne se dégage : l'effet énergétique, s'il existe, est du même ordre que le "
        "bruit et dominé par la localisation. Le mesurer proprement demande de comparer à "
        "quartier comparable (écart par classe calculé DANS chaque IRIS puis moyenné) -- "
        "extension identifiée, non traitée ici.",
        "C'est une limite assumée, pas un résultat caché : le dashboard applique la même "
        "prudence (comparaison DPE par commune uniquement).",
    ]
    _page_texte(pdf, "Impact DPE - lecture critique", blocs)


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

    fin = max(r["annee"] for r in marche)

    slice_dpe = impact_dpe_slice(
        matched, cutoff=POST_REFORM_CUTOFF, keep=lambda p: p.get("commune") in VILLES
    )
    decote = decote_dpe(slice_dpe.points, reference="D")
    appariement = appariement_par_mutation(matched, VILLES)

    OUT_PDF.parent.mkdir(parents=True, exist_ok=True)
    # metadata dates figees -> PDF reproductible bit a bit (comme data/dashboard/).
    meta = {
        "CreationDate": None,
        "ModDate": None,
        "Producer": "pipeline/07_report.py",
        "Creator": "pipeline/07_report.py",
    }
    with PdfPages(OUT_PDF, metadata=meta) as pdf:
        _page_couverture(pdf, marche, appariement)
        for commune in VILLES:
            _page_commune(pdf, marche, commune, fin)
        _page_dpe_barres(pdf, decote)
        _page_dpe_synthese(pdf, decote)

    n_pages = 3 + len(VILLES)
    print("=== Synthese PDF (pipeline/07_report.py) ===")
    print(f"  Communes            : {', '.join(v.title() for v in VILLES)}")
    print(f"  Annee de reference  : {fin}")
    print(f"  Points Impact DPE   : {len(slice_dpe.points)} (post-reforme, 3 communes)")
    print(f"  Appariement mutations residentielles : {appariement}")
    print(f"  Pages ecrites       : {n_pages}")
    print(
        f"  Fichier             : {OUT_PDF.relative_to(ROOT)}  "
        f"({OUT_PDF.stat().st_size // 1024} Ko)"
    )


if __name__ == "__main__":
    main()
