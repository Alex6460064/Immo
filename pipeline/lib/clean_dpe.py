"""Logique pure de nettoyage des DPE ADEME avant appariement DVF x DPE (T8, #9).

Aucune I/O, aucun reseau ici -- lit des dict Python deja en memoire (un enregistrement
brut = une ligne de data/raw/dpe_pays_basque.jsonl deserialisee), ne fait aucun appel
BAN. Le geocodage reseau (via pipeline/lib/geocode_ban.py) et la lecture/ecriture disque
vivent dans le script I/O pipeline/03_clean_dpe.py, qui appelle ce module.

Trois responsabilites pures exposees ici :

1. classify_dpe_date / is_post_reform -- filtre "post-reforme juillet 2021" (Out of
   Scope de l'issue #1 : les DPE pre-reforme ne sont pas fiables/comparables, on les
   exclut explicitement plutot que de les laisser polluer silencieusement le dataset).

2. build_geocoding_query -- construit la chaine d'adresse soumise a l'API BAN pour le
   geocodage. Choix documente : on assemble adresse_brut + code_postal_brut +
   nom_commune_brut (les champs "bruts" declaratifs du DPE), JAMAIS adresse_ban /
   code_postal_ban / nom_commune_ban / _geopoint qui sont le resultat du geocodage BAN
   deja effectue par ADEME elle-meme -- l'objectif de ce projet est de re-geocoder de
   maniere independante via notre propre seam (pipeline/lib/geocode_ban.py), pour que
   DVF et DPE partagent la meme source/precision de coordonnees (important pour le
   calibrage de la jointure par distance en T9/T11, voir ADR 0003). Le seul champ rue
   (adresse_brut) est souvent ambigu sans commune (ex. "Rue de la Paix" existe dans
   plusieurs communes) : on enrichit donc la requete BAN avec code postal + commune
   brute, ce qui est distinct de adresse_normalisee (voir point 3) qui sert, elle, de
   cle de comparaison textuelle DVF<->DPE et ne doit pas etre polluee par le CP/commune.

3. build_clean_record / process_records -- assemble l'enregistrement de sortie (sans
   lat/lon, ajoutes par le script I/O apres appel reseau) et classe l'ensemble d'un
   batch brut en (lignes retenues, compteur d'exclusions par raison) -- CLAUDE.md :
   une donnee exclue est documentee, jamais juste absente sans explication.
"""

from __future__ import annotations

import re
from datetime import date

from pipeline.lib.normalize_address import normalize_address

# Date de la reforme DPE (methode de calcul 3CL revisee) -- DPE etablis avant cette date
# sont hors perimetre du projet (Out of Scope, issue #1).
POST_REFORM_CUTOFF = "2021-07-01"
_CUTOFF_DATE = date.fromisoformat(POST_REFORM_CUTOFF)

_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

_WHITESPACE_RE = re.compile(r"\s+")


def classify_dpe_date(date_etablissement_dpe: str | None) -> str:
    """Classe `date_etablissement_dpe` (attendu format ISO 'YYYY-MM-DD') vis-a-vis du
    seuil post-reforme. Retourne l'une de :

    - "post_reform"  : date valide >= POST_REFORM_CUTOFF
    - "pre_reform"   : date valide < POST_REFORM_CUTOFF
    - "missing_date" : valeur absente (None) ou chaine vide
    - "invalid_date" : valeur non vide mais pas une date ISO 'YYYY-MM-DD' valide
    """
    if not date_etablissement_dpe:
        return "missing_date"
    if not _ISO_DATE_RE.match(date_etablissement_dpe):
        return "invalid_date"
    try:
        parsed = date.fromisoformat(date_etablissement_dpe)
    except ValueError:
        return "invalid_date"
    return "post_reform" if parsed >= _CUTOFF_DATE else "pre_reform"


def is_post_reform(date_etablissement_dpe: str | None) -> bool:
    """Raccourci booleen sur classify_dpe_date."""
    return classify_dpe_date(date_etablissement_dpe) == "post_reform"


def build_geocoding_query(record: dict) -> str | None:
    """Construit la chaine d'adresse a soumettre a l'API BAN pour le geocodage.

    Voir la docstring de module pour le choix des champs (bruts, jamais les champs
    BAN pre-calcules par ADEME). Retourne None si adresse_brut est absente/vide --
    rien a geocoder pour cette ligne (documente dans le resume du script I/O, pas
    une ligne supprimee silencieusement du dataset de sortie).
    """
    adresse_brut = (record.get("adresse_brut") or "").strip()
    if not adresse_brut:
        return None

    parts = [_WHITESPACE_RE.sub(" ", adresse_brut).strip()]

    code_postal = record.get("code_postal_brut")
    if code_postal:
        parts.append(str(code_postal))

    commune = (record.get("nom_commune_brut") or "").strip()
    if commune:
        parts.append(commune)

    return " ".join(parts)


def build_clean_record(record: dict) -> dict:
    """Transforme un enregistrement DPE brut (dict issu du JSONL ADEME) en enregistrement
    nettoye, pret pour la sortie -- sans lat/lon, ajoutes par le script I/O apres l'appel
    reseau de geocodage (cette fonction reste pure, pas d'appel BAN ici).
    """
    adresse_brut = record.get("adresse_brut") or ""
    return {
        "numero_dpe": record.get("numero_dpe"),
        "date_etablissement_dpe": record.get("date_etablissement_dpe"),
        "etiquette_dpe": record.get("etiquette_dpe"),
        "etiquette_ges": record.get("etiquette_ges"),
        "type_batiment": record.get("type_batiment"),
        "surface_habitable_logement": record.get("surface_habitable_logement"),
        "adresse_brut": adresse_brut,
        "adresse_normalisee": normalize_address(adresse_brut),
        "adresse_geocodage": build_geocoding_query(record),
        "code_insee_ban": record.get("code_insee_ban"),
        "nom_commune_ban": record.get("nom_commune_ban"),
        "code_postal_ban": record.get("code_postal_ban"),
    }


def process_records(records: list[dict]) -> tuple[list[dict], dict[str, int]]:
    """Classe un batch de DPE bruts : retient les post-reforme (nettoyes via
    build_clean_record), compte les exclusions par raison pour les autres.

    Retourne (lignes_retenues, {"pre_reform": n, "missing_date": n, "invalid_date": n}).
    Aucune ligne n'est supprimee sans etre comptee quelque part (CLAUDE.md : donnee
    exclue = documentee).
    """
    clean_rows: list[dict] = []
    exclusions = {"pre_reform": 0, "missing_date": 0, "invalid_date": 0}

    for record in records:
        status = classify_dpe_date(record.get("date_etablissement_dpe"))
        if status == "post_reform":
            clean_rows.append(build_clean_record(record))
        else:
            exclusions[status] += 1

    return clean_rows, exclusions
