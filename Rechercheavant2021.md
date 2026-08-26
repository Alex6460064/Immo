# Recherche : données DVF antérieures à la fenêtre officielle (2016-2020)

Recherche menée le 2026-08-26 suite à une question d'Alexandre : une session Claude Code
précédente avait affirmé que "les données DVF ne remontent pas avant 2021, pas d'archives".
Ce document vérifie cette affirmation avec des sources primaires et documente les options
trouvées pour récupérer un historique 2016-2020.

## 1. Ce qui est confirmé : la fenêtre glissante de 5 ans est réelle et légale

Vérifié en direct le 2026-08-26 via l'API JSON de data.gouv.fr (pas depuis la mémoire du
modèle) :

- Dataset officiel brut DGFiP (id `5c4ae55a634f4117716d5656`, celui utilisé par le pipeline,
  voir ADR 0002) : 5 ressources `txt.zip`, millésimes **2021 à 2025**, mises à jour le
  2026-04-05.
- Dataset Etalab géolocalisé "geo-dvf" (id `5cc1b94a634f4165e96436c1`, explicitement rejeté par
  ADR 0002) : `temporal_coverage` = **2020-07-01 → 2025-12-31**, fichier unique
  "DVF janvier 2021 - décembre 2025". Même fenêtre glissante, même rythme (avril/octobre).

Base légale trouvée sur Légifrance : [Décret n° 2018-1350 du 28 décembre 2018](https://www.legifrance.gouv.fr/jorf/id/JORFTEXT000037884472),
article R. 112 A-1 : l'administration fiscale n'est tenue de publier que les "mutations à
titre onéreux intervenues au cours des **cinq dernières années**". C'est la raison légale
exacte de la fenêtre glissante — confirmée à la source, pas juste citée par un forum.

**Conclusion** : l'affirmation "pas d'archive sur le flux officiel actuel" est correcte. Elle
est fausse en revanche si elle sous-entend qu'aucune donnée antérieure n'existe nulle part —
voir section 2.

## 2. Sources alternatives trouvées (fiabilité variable, à vérifier avant usage)

### a) Miroir communautaire au format brut (même schéma que le pipeline actuel)

- `http://data.cquest.org/dgfip_dvf/<millesime>/valeursfoncieres-<annee>.txt.gz`
- Source : script [`dvf_download.sh`](https://github.com/cquest/dvf_as_api/blob/master/dvf_download.sh)
  du dépôt `cquest/dvf_as_api` (Christian Quest, contributeur reconnu de l'open data/OSM
  français), boucle sur les années **2014 à 2019**.
- **Non vérifié en direct** : `data.cquest.org` bloque l'accès automatisé (robots.txt) depuis
  cet outil — impossible de confirmer aujourd'hui si l'archive est toujours en ligne, à jour,
  ou si elle couvre 2020. À vérifier manuellement (navigateur, ou `curl`/`wget` en local —
  aucune restriction de ce type ne s'applique à une session Claude Code sur ta machine).
- Avantage : même format pipe-delimited que le fichier officiel actuel → réutilise le
  parsing existant sans nouveau code.

### b) Miroir communautaire au format géolocalisé (Etalab enrichi)

- `https://cadastre.data.gouv.fr/data/etalab-dvf/<millesime>/csv/<annee>/full.csv.gz`
- Même script source, années 2014-2019. Même limite de vérification (accès direct bloqué
  pour cet outil).
- Format différent de celui retenu par ADR 0002 (déjà géocodé) → casserait la logique
  "on géocode nous-mêmes via l'API BAN" si utilisé tel quel pour ces années.

### c) OpenDataArchives

- `files.opendatarchives.fr` — mentionné sur le forum [TeamOpenData](https://teamopendata.org/t/dvf-donnees-avant-2016/3035)
  comme miroir automatique de jeux de données open data français, dont d'anciens millésimes
  DVF. Non vérifié du tout (piste à explorer, pas confirmée).

### d) Sources officielles agrégées (pas de mutation individuelle) — RETENUES pour l'usage confirmé (section 4)

- [Données valeurs foncières à la commune, année par année](https://www.data.gouv.fr/datasets/donnees-valeurs-foncieres-a-la-commune-annee-par-annee)
  (Caisse des Dépôts / LIFTI / CEREMA / Modaal, base DVF+) : indicateurs **agrégés par
  commune**, années **2014 à 2020** (2020 incomplète). Vérifié en direct sur data.gouv.fr.
- [Données valeurs foncières à la commune par période](https://www.data.gouv.fr/en/datasets/donnees-valeurs-foncieres-a-la-commune-par-periode/)
  : même famille (DVF+ CEREMA), agrégé par périodes 2014-2016 et 2017-2019.
- Utilisables pour un graphique de tendance (prix moyen/m², volume) sur 2014-2020,
  **pas** pour l'appariement DVF×DPE par adresse (granularité commune, pas mutation) — non
  bloquant vu l'usage confirmé (section 4).

### e) DVF+ complet (non agrégé) via CEREMA Datafoncier

- Portail [doc-datafoncier.cerema.fr](https://doc-datafoncier.cerema.fr/doc/guide/dv3f/de-dvf-a-dv3f)
  : accès à la donnée mutation par mutation, historique potentiellement plus long, mais
  nécessite une inscription/convention CEREMA (pas un simple téléchargement HTTP ouvert).
  Non creusé en détail (accès + périmètre exact à confirmer si cette piste intéresse un jour).

### f) Piste écartée / peu fiable

- [Compilation DVF par département](https://www.data.gouv.fr/datasets/compilation-des-donnees-de-valeurs-foncieres-dvf-par-departement)
  (compte perso Geoffrey Aldebert) : aucune couverture temporelle documentée, score qualité
  data.gouv.fr de 0,33. Non recommandé sans vérification approfondie.

## 3. Point important pour CE projet : le gain réel est limité par le périmètre DPE

Rappel de `CONTEXT.md` (déjà documenté dans le projet) : le DPE "post-réforme" (seule source
DPE retenue par le projet) n'existe que depuis juillet 2021. Une mutation de 2016-2020
n'a donc **structurellement aucune chance raisonnable** d'être appariée à un DPE, sauf second
diagnostic réalisé après 2021 sur le même bien (cas marginal).

## 4. Décision (confirmée par Alexandre le 2026-08-26)

Usage confirmé : comparer l'évolution des **prix de l'immobilier** sur 2016-2021 avec les
données déjà collectées (2021-2026) — **pas** de jointure DPE sur cette période (assumé et
attendu, le DPE post-réforme n'existe pas avant juillet 2021).

Conséquence pratique : pas besoin du niveau mutation individuelle ni d'un miroir communautaire
non vérifié pour ce cas d'usage. Les sources officielles agrégées CEREMA/Caisse des Dépôts
(section 2d — fiables, vérifiées, couvrent 2014-2020) suffisent pour un graphique de tendance
prix/volume, à afficher à côté (pas fusionné) du jeu de données mutation-level 2021+.

**Pas d'implémentation demandée pour l'instant** — Alexandre a choisi "recherche seulement".
Prochaine étape si le projet avance : soit trancher côté Claude Code (accès réseau sans les
restrictions de cette session Cowork, donc capable de vérifier en direct la source (a) si le
niveau mutation est finalement voulu), soit intégrer directement les jeux agrégés (d) au
dashboard existant avec une nouvelle ADR documentant le choix de source et la limite de
granularité (commune, pas mutation) pour cette période.