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
pytest + ruff (CI GitHub Actions).

## Installation

```bash
uv sync
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
```

## Dashboard

```bash
uv run streamlit run dashboard/app.py
```

Le dashboard lit `data/processed/` si le pipeline a tourné localement, sinon l'instantané
versionné `data/dashboard/` (régénéré par l'étape 06) — il fonctionne donc sur un clone frais
sans exécuter le pipeline.

Deux vues :

- **Marché** — tendance du prix/m² médian par commune et par année (2016+), carte choroplèthe
  du prix/m² médian par zone IRIS. Filtres : commune, période, type de bien (maison **ou**
  appartement — une médiane mélangeant les deux n'aurait pas de sens).
- **Impact DPE** — prix/m² par regroupement d'étiquette DPE (A-C / D / E / F-G) sur le
  sous-ensemble apparié **post-réforme** (mutations ≥ juillet 2021), avec le **taux
  d'appariement** (4 états : trouvé / résolu par consensus / non trouvé / ambigu) et
  l'avertissement sur le décalage temporel DVF / DPE affichés en clair. Filtres : commune,
  période, type de bien, regroupement DPE.

## Tests

```bash
uv run pytest
uv run ruff check .
```

## Documentation

- `CONTEXT.md` — vocabulaire métier (mutation, vente appariée, taux d'appariement…).
- `docs/adr/` — décisions d'architecture (sources de données, algorithme d'appariement, carte).
- `NOTES.md` — arbitrages méthodologiques fins (seuils, périmètres, choix du dashboard).
