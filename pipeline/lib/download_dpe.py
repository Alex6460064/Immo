"""Logique pure de recuperation des DPE via l'API data-fair d'ADEME.

Endpoint, slug de dataset et nom de champ confirmes en direct le 2026-08-25 contre l'API
data-fair d'ADEME (voir l'en-tete de pipeline/download_dpe.py pour le detail complet de la
verification) -- jamais depuis la memoire du modele, voir CLAUDE.md priorite #1 (exactitude
des donnees).

Constat cle de la verification live : le slug historique `dpe-v2-logements-existants` n'existe
plus (404). Le dataset actif equivalent ("DPE Logements existants, depuis juillet 2021") a pour
slug `dpe03existant` (id interne `meg-83tjwtg8dyz4vv7h1dqe`) -- les deux valeurs fonctionnent
comme segment d'URL `/datasets/{id_ou_slug}`. Le schema live expose `code_insee_ban`, le code
INSEE normalise issu du geocodage BAN de l'adresse du DPE, qui correspond directement aux codes
de `config/communes.py` : on filtre donc sur ce champ plutot que sur le code postal (voir choix
documente dans le script, qui evite l'ambiguite un-CP/plusieurs-communes).

Ce module isole la logique pure et testable (construction du filtre, pagination, resume par
commune) du code reseau, sur le meme principe de "seam" que pipeline/lib/geocode_ban.py : le
client HTTP est injecte, jamais importe ici en dur.

Champs recuperes (`select`) -- choix documente, pas un oubli
--------------------------------------------------------------
Le dataset live expose 230 colonnes (details methodologiques du calcul DPE : generateurs de
chauffage/ECS par installation, isolation par paroi, etc.). Mesure en direct : recuperer les
230 colonnes complique fortement le temps de reponse de l'API (~123s pour 2000 lignes, contre
~28s avec `select` applique) -- pour 61 277 enregistrements sur les 16 communes, la difference
est de l'ordre de l'heure. On restreint donc les colonnes recuperees a celles utiles aux etapes
suivantes du pipeline documentees dans CLAUDE.md/ADR 0003 (jointure DVF x DPE texte -> distance
BAN -> surface, puis agregation par commune/IRIS/etiquette) : identifiants, dates, etiquette
DPE/GES, type de logement, surface, adresse (BAN + brute), coordonnees BAN et `_geopoint`. Les
colonnes de detail methodologique du DPE (generateurs, isolation par paroi, etc.) sont hors
perimetre de ce projet et volontairement exclues -- decision documentee ici, pas un filtrage
silencieux d'une "vraie" extraction brute complete (voir CLAUDE.md : donnee non retenue doit
etre documentee, jamais juste absente sans explication).

Contrat du client HTTP injecte
-------------------------------
`client` expose une methode :

    client.get(url: str) -> response

ou `response` expose `.json() -> dict`, comme un `requests.Response` (ou tout stub
equivalent dans les tests).
"""

from __future__ import annotations

from urllib.parse import urlencode

DPE_DATASET_SLUG = "dpe03existant"
DPE_LINES_URL = f"https://data.ademe.fr/data-fair/api/v1/datasets/{DPE_DATASET_SLUG}/lines"
INSEE_FIELD = "code_insee_ban"
DEFAULT_PAGE_SIZE = 2000

# Champs confirmes presents dans le schema live du dataset (verifie le 2026-08-25) -- voir
# justification du choix dans la docstring de module ci-dessus.
SELECT_FIELDS = [
    "_id",
    "numero_dpe",
    "date_etablissement_dpe",
    "date_visite_diagnostiqueur",
    "etiquette_dpe",
    "etiquette_ges",
    "type_batiment",
    "annee_construction",
    "periode_construction",
    "surface_habitable_logement",
    "adresse_ban",
    "adresse_brut",
    "adresse_complete_brut",
    "identifiant_ban",
    "code_insee_ban",
    "code_postal_ban",
    "code_postal_brut",
    "nom_commune_ban",
    "nom_commune_brut",
    "coordonnee_cartographique_x_ban",
    "coordonnee_cartographique_y_ban",
    "score_ban",
    "_geopoint",
]


def build_qs_filter(codes_insee: list[str]) -> str:
    """Filtre `qs` data-fair (syntaxe type Lucene) : OR sur le code INSEE normalise BAN."""
    if not codes_insee:
        raise ValueError("codes_insee ne peut pas etre vide")
    return " OR ".join(f"{INSEE_FIELD}:{code}" for code in codes_insee)


def build_initial_url(
    codes_insee: list[str],
    page_size: int = DEFAULT_PAGE_SIZE,
    select_fields: list[str] | None = None,
) -> str:
    """Construit l'URL de la premiere page. Les pages suivantes suivent le curseur `next`
    renvoye tel quel par l'API -- aucune reconstruction manuelle necessaire.

    `select_fields=None` (defaut) applique SELECT_FIELDS ; passer `[]` explicitement pour
    ne pas restreindre les colonnes (retour au comportement "toutes colonnes" de l'API).
    """
    qs = build_qs_filter(codes_insee)
    params = {"qs": qs, "size": page_size}
    fields = SELECT_FIELDS if select_fields is None else select_fields
    if fields:
        params["select"] = ",".join(fields)
    return f"{DPE_LINES_URL}?{urlencode(params)}"


def fetch_all_lines(
    client,
    codes_insee: list[str],
    page_size: int = DEFAULT_PAGE_SIZE,
    select_fields: list[str] | None = None,
) -> list[dict]:
    """Recupere toutes les lignes DPE des communes donnees, en suivant le curseur `next`
    renvoye par data-fair (pagination search_after) jusqu'a epuisement.

    `next` est absent/None sur la derniere page (confirme en live) : c'est le signal d'arret.
    """
    url = build_initial_url(codes_insee, page_size, select_fields=select_fields)
    records: list[dict] = []
    while url:
        payload = client.get(url).json()
        records.extend(payload.get("results", []))
        url = payload.get("next")
    return records


def summarize_by_commune(records: list[dict], insee_field: str = INSEE_FIELD) -> dict[str, int]:
    """Compte le nombre d'enregistrements DPE par code INSEE -- utilise pour le resume
    affiche en fin de script (nb par commune, communes couvertes vs cible).

    Un enregistrement sans le champ (valeur absente/None) est compte sous la cle None,
    jamais supprime en silence (voir CLAUDE.md : donnee manquante = documentee).
    """
    counts: dict[str | None, int] = {}
    for r in records:
        code = r.get(insee_field)
        counts[code] = counts.get(code, 0) + 1
    return counts
