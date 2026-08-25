# DVF officiel brut (DGFiP) + géocodage via API BAN, pas geo-dvf Etalab enrichi

Le projet a pour but explicite de démontrer une compétence pipeline de bout en bout, API
incluse — pas seulement consommer une donnée déjà prête à l'emploi. Décision : utiliser le
fichier **DVF officiel brut** publié par la DGFiP sur data.gouv.fr (adresse en champs séparés,
pas de lat/lon), et ajouter une étape pipeline dédiée de **géocodage via l'API BAN** (Base
Adresse Nationale, `api-adresse.data.gouv.fr`, gouvernementale, gratuite) pour obtenir les
coordonnées nécessaires à la carte en points (voir carte en points individuels, décision Q3).

La plage d'années couverte n'est **pas fixée à l'avance** (la doc officielle annonce une
fenêtre glissante de 5 ans, mais la plage réelle observée peut différer) : le pipeline
`01_download.py` détecte et logge la plage réelle disponible à l'exécution plutôt que de
promettre une borne arbitraire.

**Alternative rejetée** : geo-dvf Etalab (déjà géolocalisé par jointure parcellaire, colonnes
déjà normalisées) — plus simple et plus rapide à mettre en œuvre, mais retire tout le travail
de parsing/normalisation d'adresse et de géocodage que le projet veut précisément démontrer.
Rejetée car elle masquerait la compétence pipeline visée par le portfolio.

**Risque connu, accepté par l'utilisateur** : le taux de succès du géocodage par adresse brute
n'est pas garanti à 100 % — sera mesuré et affiché comme le taux de matching DVF↔DPE (principe
CLAUDE.md : les limites méthodologiques ne se cachent pas).
