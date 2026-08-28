# DVF × DPE Pays Basque

[![Streamlit App](https://static.streamlit.io/badges/streamlit_badge_black_white.svg)](https://dvf-dpe-pays-basque.streamlit.app/)

**Dashboard interactif → https://dvf-dpe-pays-basque.streamlit.app/** (Streamlit Community Cloud).

Croisement des **ventes immobilières officielles** (DVF, DGFiP) et des **diagnostics de
performance énergétique** (DPE post-réforme, ADEME) sur le littoral Pays Basque et le BAB
élargi (16 communes, `config/communes.py`).

Projet portfolio data : pipeline reproductible + dashboard interactif. Le code est autant la
vitrine que le résultat — priorité à l'exactitude des données et à la transparence des
limites méthodologiques (taux d'appariement, biais temporel), jamais masquées.

## Stack

Python + [uv](https://docs.astral.sh/uv/) · DuckDB · Parquet · Streamlit + Plotly ·
matplotlib (synthèse PDF, groupe `report`) · pytest + ruff (CI GitHub Actions).

## Installation

```bash
uv sync                     # pipeline + dashboard
uv sync --group report      # + matplotlib, pour régénérer la synthèse PDF (étape 07)
```

## Pipeline

Chaque étape est idempotente et rejouable indépendamment (résultats mis en cache dans
`data/processed/`, non versionnés).

```bash
uv run python pipeline/download_dvf.py             # DVF brut courant (dept. 64+40)
uv run python pipeline/download_dvf_historique.py  # DVF historique 2016-2020 (miroir cquest, ADR 0005)
uv run python pipeline/download_dpe.py             # DPE post-réforme filtrés sur les communes ciblées
uv run python pipeline/02_clean_dvf.py
uv run python pipeline/02b_geocode_ban.py  # géocodage adresses DVF via l'API BAN
uv run python pipeline/03_clean_dpe.py
uv run python pipeline/04_join.py          # appariement DVF↔DPE (texte → distance → surface) + rapport
uv run python pipeline/04b_join_iris.py    # rattachement spatial mutation → IRIS
uv run python pipeline/05_aggregate.py     # agrégats commune / IRIS / étiquette DPE
uv run python pipeline/06_publish_dashboard_data.py  # instantané versionné data/dashboard/ (déploiement Cloud)
uv run --group report python pipeline/07_report.py   # synthèse PDF (reports/, lit data/dashboard/)
```

L'étape 07 est en aval de l'instantané `data/dashboard/` : elle ne relit jamais
`data/processed/` et se régénère sur un clone frais. Le PDF produit est reproductible bit à
bit (métadonnées de date figées), comme `data/dashboard/`.

## Dashboard

```bash
uv run streamlit run dashboard/app.py
```

Le dashboard lit `data/processed/` si le pipeline a tourné localement, sinon l'instantané
versionné `data/dashboard/` (régénéré par l'étape 06) — il fonctionne donc sur un clone frais
sans exécuter le pipeline.

Deux vues :

- **Marché** — courbe de référence **toutes communes confondues** (prix/m² par année, 2016+),
  plus une courbe par commune cochée pour comparer sans noyer le graphe sous 16 séries ;
  carte choroplèthe du prix/m² par zone IRIS. Un toggle **Moyenne / Médiane** (moyenne par
  défaut) pilote la courbe **et** la carte. Le prix/m² est calculé **par mutation** (prix ÷
  surface habitation totale), pas par lot — sinon une vente d'immeuble en bloc fausserait
  toute une zone (ADR 0006). Filtres : période, type de bien — maison, appartement, ou
  **Tous** (une courbe par type, jamais fusionnées ; la carte demande alors un type précis).
- **Impact DPE** — prix/m² par regroupement d'étiquette DPE (A-C / D / E / F-G) pour **une
  commune** (obligatoire : comparer un bien F à Biarritz front de mer à un bien A à Hasparren
  n'a pas de sens), sur le sous-ensemble apparié **post-réforme** (mutations ≥ juillet 2021),
  avec le **taux d'appariement** (4 états : trouvé / résolu par consensus / non trouvé /
  ambigu) et l'avertissement sur le décalage temporel DVF / DPE affichés en clair. Filtres :
  commune, période, type de bien, regroupement DPE.

## Synthèse PDF

[`reports/synthese-pays-basque.pdf`](reports/synthese-pays-basque.pdf) — 6 pages, Bayonne /
Anglet / Biarritz : évolution du prix/m² moyen (Appartement / Maison, 2016-2025) avec les
variations sur ~10 ans, 5 ans et 1 an ; prix/m² moyen par étiquette DPE et par commune depuis
la réforme, suivi d'une lecture critique du biais de localisation (les passoires F/G,
concentrées dans l'ancien cher du centre et du front de mer, ne laissent apparaître aucune
décote DPE lisible sur donnée brute). Régénéré par `pipeline/07_report.py` à partir de
l'instantané `data/dashboard/`.

## Tests

```bash
uv run pytest
uv run ruff check .
```

## Documentation

- `CONTEXT.md` — vocabulaire métier (mutation, vente appariée, taux d'appariement…).
- `docs/adr/` — décisions d'architecture (sources de données, algorithme d'appariement, carte).
- `NOTES.md` — arbitrages méthodologiques fins (seuils, périmètres, choix du dashboard).
