# Source communautaire (miroir cquest) pour le DVF historique 2016-2020

Le flux officiel DGFiP sur data.gouv.fr n'expose qu'une **fenêtre glissante de 5 ans**
(base légale : [décret n° 2018-1350](https://www.legifrance.gouv.fr/jorf/id/JORFTEXT000037884472),
article R. 112 A-1 — l'administration fiscale n'est tenue de publier que les mutations
« intervenues au cours des cinq dernières années »), soit **2021-2025** aujourd'hui. Aucune
archive au-delà n'est disponible sur ce flux. Or le projet veut une tendance des prix sur
**10 ans**, ce qui suppose les millésimes 2016-2020 au même niveau de granularité (mutation
individuelle) que le jeu déjà collecté.

[ADR 0002](0002-dvf-brut-plus-geocodage-ban.md) fixe data.gouv.fr comme source du DVF brut.
**Décision : dérogation ciblée à ADR 0002 pour la seule tranche 2016-2020** — ces millésimes
sont téléchargés depuis le miroir communautaire
`http://data.cquest.org/dgfip_dvf/202104/` (édition DGFiP d'avril 2021, la dernière à couvrir
2016 avant que la fenêtre glissante ne l'exclue). Christian Quest est un contributeur reconnu
de l'open data et d'OpenStreetMap français ; le format est pipe-delimited, quasi identique au
fichier officiel actuel. ADR 0002 **reste la décision pour 2021+** et n'est pas remise en
cause : le flux officiel couvre nativement cette période, le miroir n'est utilisé que là où
l'officiel n'a rien.

**Pourquoi la dérogation reste limitée à 2016-2020** : (1) 2021+ est déjà servi par la source
officielle, sans besoin de miroir ; (2) le DPE post-réforme (seule source DPE du projet)
n'existe pas avant juillet 2021 — la tranche 2016-2020 est un jeu « prix seul », jamais
apparié à un DPE par adresse (voir [ADR 0003](0003-algorithme-appariement-dvf-dpe.md) et
`CONTEXT.md`), donc l'enjeu d'exactitude fine sur ces années est moindre que sur la période
appariée.

**Vérification faite** (sources primaires, pas une affirmation reprise d'un forum) :

- Fenêtre glissante et sa base légale confirmées à la source (API JSON data.gouv.fr +
  Légifrance) le 2026-08-26 — détail dans `Rechercheavant2021.md`.
- Miroir vérifié en direct par `curl` le 2026-08-27 : `HTTP/1.1 200 OK`,
  `Last-Modified: Tue, 30 Mar 2021` (édition d'avril 2021 confirmée),
  `Content-Length: 391 545 490` pour `valeursfoncieres-2016.txt`. Le listing du répertoire
  expose `valeursfoncieres-2016.txt` … `valeursfoncieres-2020.txt`.
- Schéma comparé colonne à colonne (DuckDB `DESCRIBE`) entre les parquets bruts filtrés
  2016-2020 et le millésime 2021 officiel : **43 colonnes, identiques à une seule près** —
  `Code service CH` (miroir) correspond à `Identifiant de document` (officiel). L'alias est
  appliqué explicitement à l'écriture, jamais silencieux
  (`pipeline/lib/download_dvf_historique.py`, `HISTORICAL_COLUMN_ALIASES`, testé unitairement).
- Intégration aval confirmée par exécution réelle (issue #19) : `02_clean_dvf.py` et
  `02b_geocode_ban.py` rejoués sans modification absorbent 2016-2020 par leur glob existant,
  millésimes présents côte à côte avec 2021-2025 et mêmes colonnes de sortie.

**Alternative rejetée** : les jeux **agrégés officiels** DVF+ (CEREMA / Caisse des Dépôts,
2014-2020, vérifiés et fiables — `Rechercheavant2021.md` section 2d). Granularité **commune**,
pas mutation : casse l'homogénéité avec le jeu mutation-level 2021+ et interdit la jointure
spatiale IRIS ([ADR 0004](0004-carte-choroplethe-iris.md)). Conservés comme piste de repli si
le miroir cquest disparaît.

**Alternative rejetée** : le miroir **géolocalisé** `cadastre.data.gouv.fr/data/etalab-dvf/`
(mêmes années). Données déjà géocodées par jointure parcellaire — contredit ADR 0002 (le
projet géocode lui-même via l'API BAN pour démontrer cette étape).

**Risque connu, accepté par l'utilisateur** : `data.cquest.org` est un miroir personnel, sans
engagement de maintien dans le temps par un opérateur officiel. S'il disparaît, les parquets
déjà filtrés dans `data/raw/` (`dvf_brut_2016.parquet` … `dvf_brut_2020.parquet`) sont la
seule copie exploitable de cette tranche — et `data/raw/` est en `.gitignore` (non versionné) :
une perte locale de `data/raw/` **et** la disparition du miroir rendraient 2016-2020 non
regénérable. Repli en dernier recours : les jeux agrégés CEREMA ci-dessus (tendance prix à la
commune, sans le niveau mutation). L'édition d'avril 2021 est par ailleurs figée — pas de
correction rétroactive des millésimes 2016-2020 après cette date ; acceptable pour des données
anciennes déjà stabilisées.
