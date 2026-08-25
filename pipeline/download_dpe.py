"""Telecharge les DPE (logements existants) des communes ciblees via l'API data-fair
d'ADEME, filtres par code INSEE au moment de la requete -- jamais un fichier national.

Etape idempotente : si le fichier de sortie existe deja dans data/raw/, aucun appel reseau
n'est refait (voir CLAUDE.md : jamais de re-telechargement complet sans raison explicite).

--- Verification de l'API live (2026-08-25) -- rien n'est suppose depuis l'entrainement ---

1. Recherche du dataset :
   GET https://data.ademe.fr/data-fair/api/v1/datasets?q=dpe-v2-logements-existants
   -> le slug historique "dpe-v2-logements-existants" (mentionne dans le ticket) n'existe
   plus : GET .../datasets/dpe-v2-logements-existants renvoie 404. Le dataset actif
   equivalent est "DPE Logements existants (depuis juillet 2021)", slug `dpe03existant`
   (id interne `meg-83tjwtg8dyz4vv7h1dqe`) ; id et slug fonctionnent tous les deux comme
   segment d'URL `/datasets/{id_ou_slug}`.

2. Schema du dataset :
   GET https://data.ademe.fr/data-fair/api/v1/datasets/dpe03existant
   -> 230 champs. Champs pertinents pour le filtrage geographique confirmes dans le
   schema live : `code_insee_ban` (code INSEE normalise, issu du geocodage BAN de
   l'adresse du DPE), `code_postal_ban`, `code_postal_brut`, `nom_commune_ban`.
   Choix : filtrer sur `code_insee_ban` plutot que le code postal -- il correspond
   directement, sans conversion, aux codes de config/communes.py (source de verite
   unique du perimetre), et evite l'ambiguite qu'un code postal peut couvrir plusieurs
   communes / qu'une commune peut avoir plusieurs codes postaux (voir ticket #6).

3. Requete reelle (limit=1, puis pagination) :
   GET https://data.ademe.fr/data-fair/api/v1/datasets/dpe03existant/lines
       ?qs=code_insee_ban:64122&size=2
   -> reponse `{"total": int, "results": [...], "next": "<url complete>"}` confirmee.
   `next` est absent/None sur la derniere page (verifie avec une commune a faible volume :
   396 resultats sur 396 -> next=None). La pagination consiste donc a suivre `next` tel
   quel jusqu'a ce qu'il soit absent -- aucune reconstruction manuelle d'URL necessaire
   (voir fetch_all_lines dans pipeline/lib/download_dpe.py).

   Total combine mesure en live pour les 16 communes ciblees : 61 277 enregistrements.

Endpoint final : https://data.ademe.fr/data-fair/api/v1/datasets/dpe03existant/lines
Filtre        : qs=code_insee_ban:<code1> OR code_insee_ban:<code2> OR ...

Choix technique -- colonnes recuperees (`select`) : le dataset expose 230 colonnes, dont la
grande majorite est le detail methodologique du calcul DPE (generateurs de chauffage/ECS par
installation, isolation par paroi, etc.) sans rapport avec l'appariement DVF x DPE et
l'agregation par etiquette decrits dans CLAUDE.md/ADR 0003. Mesure en live : recuperer les 230
colonnes est ~4x plus lent (123s pour 2000 lignes, contre 28s avec `select` applique) --
sur 61 277 enregistrements cela ferait ~60-70 min contre ~14 min. On applique donc `select`
avec la liste `SELECT_FIELDS` de pipeline/lib/download_dpe.py (identifiants, dates, etiquette
DPE/GES, type de logement, surface, adresse BAN + brute, coordonnees BAN, `_geopoint`) --
c'est un choix de perimetre documente ici et dans le module (voir sa docstring), pas une perte
de donnees silencieuse (CLAUDE.md : donnee non retenue = documentee).

Client HTTP : urllib (stdlib), pas `requests` -- un simple GET recursif en suivant l'URL
`next` fournie telle quelle par l'API suffit ; pas de fonctionnalite avancee necessaire
(CLAUDE.md : pas de nouvelle dependance sans justification).
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

# Execution en script direct (`python pipeline/download_dpe.py` depuis la racine, comme documente
# dans le WORKFLOW de CLAUDE.md) : la racine du repo n'est pas automatiquement sur sys.path
# (contrairement a pytest, ou pyproject.toml fixe pythonpath=["."]). Ajout local a ce script.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.communes import get_communes  # noqa: E402
from pipeline.lib.download_dpe import (  # noqa: E402
    DEFAULT_PAGE_SIZE,
    fetch_all_lines,
    summarize_by_commune,
)

OUTPUT_PATH = Path(__file__).resolve().parent.parent / "data" / "raw" / "dpe_pays_basque.jsonl"
USER_AGENT = "dvf-dpe-pays-basque/0.1 (portfolio project; contact via GitHub Alex6460064/Immo)"
REQUEST_TIMEOUT_S = 120


class UrllibClient:
    """Client HTTP minimal (stdlib urllib) respectant le contrat `.get(url) -> response`
    avec `response.json() -> dict`, attendu par pipeline.lib.download_dpe.fetch_all_lines."""

    class _Response:
        def __init__(self, body: bytes):
            self._body = body

        def json(self) -> dict:
            return json.loads(self._body)

    def get(self, url: str) -> UrllibClient._Response:
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_S) as response:
            return UrllibClient._Response(response.read())


def _fetch_with_retry(
    client, codes_insee: list[str], page_size: int, max_retries: int = 3
) -> list[dict]:
    """Enveloppe fetch_all_lines avec un retry simple sur erreur reseau transitoire
    (l'API data-fair est parfois lente/instable sur de gros volumes -- confirme en live :
    une requete a size=10000 a echoue par timeout, d'ou aussi un page_size modere)."""
    last_error: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            return fetch_all_lines(client, codes_insee, page_size=page_size)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            last_error = exc
            print(f"  [retry {attempt}/{max_retries}] erreur reseau : {exc}", file=sys.stderr)
            time.sleep(5)
    raise RuntimeError(f"Echec apres {max_retries} tentatives : {last_error}") from last_error


def main() -> None:
    communes = get_communes()
    codes_insee = [c["code_insee"] for c in communes]

    if OUTPUT_PATH.exists() and OUTPUT_PATH.stat().st_size > 0:
        with OUTPUT_PATH.open("r", encoding="utf-8") as f:
            existing_count = sum(1 for _ in f)
        print(
            f"[download_dpe] Fichier deja present ({OUTPUT_PATH}, {existing_count} lignes) "
            "-- telechargement saute (idempotent). Supprimer le fichier pour forcer un "
            "re-telechargement complet."
        )
        return

    print(
        f"[download_dpe] Recuperation DPE ADEME (dataset dpe03existant) pour "
        f"{len(codes_insee)} communes -- filtre code_insee_ban, pagination size="
        f"{DEFAULT_PAGE_SIZE}."
    )

    client = UrllibClient()
    records = _fetch_with_retry(client, codes_insee, page_size=DEFAULT_PAGE_SIZE)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_PATH.open("w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False))
            f.write("\n")

    counts = summarize_by_commune(records)
    communes_couvertes = {code for code in counts if code in codes_insee}

    print(f"[download_dpe] Termine : {len(records)} enregistrements DPE ecrits dans {OUTPUT_PATH}")
    print(
        f"[download_dpe] Communes couvertes (>=1 DPE trouve) : {len(communes_couvertes)}/"
        f"{len(codes_insee)}"
    )
    nom_par_code = {c["code_insee"]: c["nom"] for c in communes}
    for code in codes_insee:
        nom = nom_par_code[code]
        print(f"  - {nom} ({code}) : {counts.get(code, 0)} DPE")
    manquantes = [nom_par_code[c] for c in codes_insee if c not in counts]
    if manquantes:
        print(
            f"[download_dpe] ATTENTION -- aucune donnee DPE trouvee pour : {', '.join(manquantes)}"
        )
    hors_perimetre = sum(n for code, n in counts.items() if code not in codes_insee)
    if hors_perimetre:
        print(
            f"[download_dpe] NOTE -- {hors_perimetre} enregistrement(s) avec un code_insee_ban "
            "hors perimetre cible ou absent (voir cle None ci-dessus si applicable)."
        )


if __name__ == "__main__":
    main()
