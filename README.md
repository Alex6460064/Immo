# DVF × DPE Pays Basque

[![Streamlit App](https://static.streamlit.io/badges/streamlit_badge_black_white.svg)](https://dvf-dpe-pays-basque.streamlit.app/)
[![CI](https://github.com/Alex6460064/Immo/actions/workflows/ci.yml/badge.svg)](https://github.com/Alex6460064/Immo/actions/workflows/ci.yml)

**Dashboard interactif → https://dvf-dpe-pays-basque.streamlit.app/**

Projet portfolio *data engineering / data analysis*. Objectif : montrer un pipeline de données
propre, reproductible et honnête sur ses limites — le code est autant la vitrine que le résultat.

---

## Le projet expliqué simplement

Quand quelqu'un vend une maison ou un appartement en France, l'État enregistre le prix dans un
**registre public** : c'est **DVF** (Demandes de Valeurs Foncières).

Chaque logement a aussi une **étiquette énergie**, de **A** (très économe) à **G** (« passoire
thermique »). C'est le **DPE** (Diagnostic de Performance Énergétique).

Ces deux informations existent séparément. Ce projet les **recolle ensemble**, logement par
logement, sur **16 communes de la côte basque** (Bayonne, Anglet, Biarritz, Saint-Jean-de-Luz,
Hendaye… + Tarnos et Ondres pour comparer). Il répond à deux questions simples :

1. **Comment le prix du m² a évolué depuis 2016**, commune par commune ?
2. **Un logement mal noté (F ou G) se vend-il vraiment moins cher** qu'un logement bien noté ?

Le résultat : un **site web interactif** (graphiques + carte) et une **synthèse PDF**.

### La leçon honnête du projet

Sur les données brutes, la « décote passoire thermique » **ne se voit pas**. Pas parce qu'elle
n'existe pas, mais parce que les logements F et G sont surtout concentrés dans l'**ancien de
centre-ville et de bord de mer** — précisément là où le m² est le plus cher. Le prix élevé de
l'emplacement masque l'effet de l'étiquette.

Beaucoup de projets cacheraient ce problème. Ici il est **mis en avant** : le dashboard et le
PDF affichent la limite au lieu de la maquiller.

---

## Ce que montre le dashboard

**Vue « Marché »**
Une courbe du prix au m² par année (depuis 2016), toutes communes confondues, avec possibilité
d'ajouter une courbe par commune pour comparer. Une **carte** colore chaque quartier selon son
prix au m². Bascule **moyenne / médiane**, filtres période et type de bien (maison /
appartement).

**Vue « Impact DPE »**
Pour **une commune choisie**, le prix au m² selon le groupe d'étiquette énergie
(A-C / D / E / F-G). Comparer une commune à une autre n'aurait pas de sens (un bien F à Biarritz
front de mer reste plus cher qu'un bien A à Hasparren), donc la commune est obligatoire. La vue
affiche en clair le **taux de rapprochement** DVF↔DPE et l'**avertissement** sur le décalage de
dates entre une vente et son diagnostic.

---

## Pour un·e recruteur·se — ce que le projet démontre

| Compétence | Où ça se voit |
|---|---|
| Pipeline de données **reproductible** et rejouable étape par étape | `pipeline/`, chaque script idempotent |
| **Rapprochement d'enregistrements** sans identifiant commun (adresse → géocodage → surface → consensus) | `pipeline/lib/join_dvf_dpe.py`, [ADR 0003](docs/adr/0003-algorithme-appariement-dvf-dpe.md) |
| Traitement de **gros fichiers** sans tout charger en mémoire (SQL sur fichiers) | DuckDB, partout dans `pipeline/` |
| **Honnêteté méthodologique** : taux de correspondance, biais temporel et biais de localisation affichés, jamais masqués | dashboard, `reports/`, `NOTES.md` |
| **Tests** (TDD) + **intégration continue** | `tests/`, CI GitHub Actions (ruff + pytest) |
| **Décisions d'architecture documentées** | `docs/adr/`, `CONTEXT.md`, `NOTES.md` |
| **Déploiement** d'un dashboard public | Streamlit Community Cloud |
| **Rapport automatisé** reproductible bit à bit | `pipeline/07_report.py` → PDF Typst |

---

## D'où viennent les données

| Source | Fournisseur | Contenu | Filtre appliqué au téléchargement |
|---|---|---|---|
| **DVF** (fichier brut DGFiP) | data.gouv.fr | Ventes immobilières, une ligne par lot, sans identité des parties (RGPD-safe par construction) | codes INSEE des 16 communes ciblées, dept. 64 + 40 ([ADR 0002](docs/adr/0002-dvf-brut-plus-geocodage-ban.md)) |
| **DVF historique 2016-2020** | miroir cquest | Même format, pour la tendance sur ~10 ans | idem ([ADR 0005](docs/adr/0005-source-historique-dvf-2016-2020.md)) |
| **DPE** | data.ademe.fr | Étiquette A-G, adresse, date, surface — **uniquement post-réforme** (méthode en vigueur depuis juillet 2021) | communes ciblées |
| **Contours IRIS** | INSEE / IGN | Découpage infra-communal pour la carte | communes ciblées ([ADR 0004](docs/adr/0004-carte-choroplethe-iris.md)) |

Le fichier DVF brut ne contient **pas** de coordonnées : le géocodage est fait en interne via
l'**API BAN** (`api-adresse.data.gouv.fr`), pour DVF et DPE, afin que les deux jeux partagent la
même précision de coordonnées.

Le périmètre géographique vit dans **un seul fichier** (`config/communes.py`) — ajouter une
commune ne touche qu'un endroit.

---

## Comment les données sont nettoyées

Rien n'est supprimé en silence : chaque ligne écartée est **comptée et affichée** dans le résumé
du script.

**DVF** (`pipeline/lib/clean_dvf.py`)
- Prix et surface parsés depuis le format DGFiP (virgule décimale française).
- Ligne écartée si **prix à 0/absent** ou **surface à 0/absente** (inutilisable pour un prix/m²).
- Surface retenue : « Surface réelle bâti » (renseignée bien plus souvent que la surface Carrez
  sur ce périmètre).
- Adresse recomposée depuis les colonnes éclatées (n°, bis/ter, type de voie, voie) puis
  **normalisée** (clé de comparaison texte avec le DPE).

**DPE** (`pipeline/lib/clean_dpe.py`)
- **DPE pré-réforme exclus** (avant juillet 2021) : ancienne méthode de calcul, non comparable.
  Dates manquantes ou invalides également écartées, chacune comptée à part.
- Adresse normalisée comme pour DVF ; requête de géocodage enrichie du code postal + commune.
- On **re-géocode** via notre propre étape plutôt que de réutiliser les coordonnées ADEME.

**Prix au m²** (`pipeline/lib/mutations.py`, [ADR 0006](docs/adr/0006-repli-mutation-prix-m2.md))
- Calculé **par mutation** (`prix ÷ somme des surfaces habitation`), jamais par lot. Le brut
  DGFiP recopie le montant total de la vente sur chaque ligne-lot : diviser par la surface d'un
  seul lot ferait exploser une vente d'immeuble en bloc à ~100 000 €/m² et fausserait tout un
  quartier sur la carte.
- Garde-fous : mutations mono-type habitation uniquement, prix/m² borné à [200, 30 000] €.

---

## Le rapprochement DVF × DPE

Aucun identifiant commun entre une vente et un diagnostic. L'appariement se fait en cascade
(détail : [ADR 0003](docs/adr/0003-algorithme-appariement-dvf-dpe.md)) :

1. **Adresse normalisée identique** ;
2. sinon **proximité géographique** des points géocodés (seuil calibré à **15 m**) ;
3. **départage par surface** (± 2 m²) et par type de bâtiment s'il reste plusieurs candidats ;
4. si les candidats restants portent **tous la même étiquette**, on garde l'étiquette (identité
   du DPE inconnue mais réponse analytique certaine) → état `resolu_consensus`.

Chaque mutation reçoit **un des 4 états** — `trouvé` / `resolu_consensus` / `non trouvé` /
`ambigu` — et **les 4 taux sont publiés** (dashboard + logs), jamais agrégés pour faire joli.
Aucune mutation ambiguë n'est appariée au hasard.

Sur le jeu courant : environ **trouvé 38 % / consensus 12 % / non trouvé 18 % / ambigu 32 %**.
Le taux d'ambigu élevé est **attendu** : en habitat collectif dense (BAB), plusieurs logements
d'un même immeuble partagent adresse et surface — l'algorithme refuse de trancher.

---

## Installation

Gestion des dépendances avec [uv](https://docs.astral.sh/uv/).

```bash
uv sync                     # pipeline + dashboard
uv sync --group report      # + Typst, pour régénérer la synthèse PDF (étape 07)
git config core.hooksPath .githooks   # active le hook pre-commit (ruff, miroir CI)
```

## Pipeline

Chaque étape est idempotente et rejouable indépendamment. Les résultats intermédiaires sont mis
en cache dans `data/processed/` (non versionné).

```bash
uv run python pipeline/download_dvf.py             # DVF brut courant (dept. 64+40)
uv run python pipeline/download_dvf_historique.py  # DVF historique 2016-2020 (miroir cquest, ADR 0005)
uv run python pipeline/download_dpe.py             # DPE post-réforme, communes ciblées
uv run python pipeline/02_clean_dvf.py
uv run python pipeline/02b_geocode_ban.py          # géocodage des adresses DVF via l'API BAN
uv run python pipeline/03_clean_dpe.py
uv run python pipeline/04_join.py                  # appariement DVF↔DPE + rapport 4 états
uv run python pipeline/04b_join_iris.py            # rattachement spatial mutation → IRIS
uv run python pipeline/05_aggregate.py             # agrégats commune / IRIS / étiquette DPE
uv run python pipeline/06_publish_dashboard_data.py  # instantané versionné data/dashboard/
uv run --group report python pipeline/07_report.py   # synthèse PDF (reports/, lit data/dashboard/)
```

Chaque script affiche un résumé (nombre de lignes, taux de correspondance, valeurs manquantes)
et échoue bruyamment plutôt que de produire une sortie douteuse.

`data/dashboard/` est un **instantané versionné** (produit uniquement par l'étape 06) : il
permet au dashboard et à la synthèse PDF de fonctionner sur un clone frais, **sans exécuter le
pipeline**. L'étape 07 lit cet instantané, jamais `data/processed/`.

## Dashboard

```bash
uv run streamlit run dashboard/app.py
```

Lit `data/processed/` si le pipeline a tourné localement, sinon l'instantané `data/dashboard/`.

## Synthèse PDF

[`reports/synthese-pays-basque.pdf`](reports/synthese-pays-basque.pdf) — 6 pages sur Bayonne /
Anglet / Biarritz : évolution du prix/m² moyen (appartement / maison, 2016-2025) avec les
variations sur ~10 ans, 5 ans et 1 an ; prix/m² par étiquette DPE et par commune depuis la
réforme ; puis une **lecture critique** du biais de localisation (les passoires F/G, concentrées
dans l'ancien cher, ne laissent apparaître aucune décote DPE lisible sur donnée brute).

Régénérée par `pipeline/07_report.py` : le script calcule les chiffres depuis
`data/dashboard/`, `pipeline/report/template.typ` les met en page (Typst, graphes
[lilaq](https://typst.app/universe/package/lilaq)). PDF **reproductible bit à bit** (polices
embarquées, versions épinglées, date figée).

## Tests

```bash
uv run pytest
uv run ruff check .
```

TDD sur toute la logique pure (`pipeline/lib/`) : normalisation d'adresse, distance géocodée,
départage par surface, agrégats, rendu du rapport. Tests d'intégration sur échantillon fixe par
étape. CI GitHub Actions (ruff + pytest) à chaque push. Un hook `pre-commit` versionné
(`.githooks/`, activé via `git config core.hooksPath .githooks`) rejoue `ruff check` +
`ruff format --check` avant chaque commit.

## Limites connues

- **Taux de correspondance structurellement bas avant juillet 2021** : le DPE nouvelle méthode
  n'existe pas avant cette date, une vente de 2017 n'a presque aucune chance d'être appariée.
  La vue « Impact DPE » ne travaille donc que sur les ventes post-réforme.
- **~32 % d'ambigus** en habitat collectif dense — affichés tels quels, jamais résolus de force.
- **Décalage temporel** vente / diagnostic (une vente 2021 peut être appariée à un DPE 2024) —
  signalé en clair sur la vue.
- **Biais de localisation** : l'étiquette DPE est corrélée à l'emplacement (ancien de centre et
  bord de mer), ce qui masque toute décote sur donnée brute. Un modèle toutes choses égales par
  ailleurs serait nécessaire pour isoler l'effet — hors périmètre de ce projet.
- **Traitement fin des valeurs aberrantes** hors périmètre (issue #1) : la médiane reste la
  statistique robuste de référence, la moyenne est fournie mais plus sensible.

## Documentation

- `CONTEXT.md` — vocabulaire métier (mutation, vente appariée, taux d'appariement…).
- `docs/adr/` — décisions d'architecture (sources de données, algorithme d'appariement, carte).
- `NOTES.md` — arbitrages méthodologiques fins (seuils, périmètres, choix du dashboard).
