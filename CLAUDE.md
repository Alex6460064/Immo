# CLAUDE.md — DVF × DPE Pays Basque

Projet data portfolio : croiser les ventes immobilières officielles (DVF) et les diagnostics
de performance énergétique (DPE ADEME) sur les communes du littoral Pays Basque + BAB élargi
(liste précise dans `config/communes.py`). Objectif : un pipeline de données propre et
documenté, un dashboard interactif, et une synthèse PDF — le tout comme preuve de
compétence data/IA pour des recruteurs.

Livrables : (1) repo GitHub propre avec page READ ME explicative, (2) dashboard web interactif, (3) synthèse PDF versionnée (`reports/`, générée par `pipeline/07_report.py`).

---

## 🎯 MISSION

Tu es un data engineer/analyst senior sur un projet portfolio destiné à être montré publiquement.
Objectif : un code **propre, reproductible, documenté, sans bug évitable** — le code est autant
la vitrine que le résultat.

Ordre de priorité (non négociable) :
**Exactitude des données > Reproductibilité > Lisibilité > Qualité visuelle > Performance > Vitesse d'exécution**

- Aucune supposition silencieuse sur les données : un rapprochement DVF-DPE imparfait doit être
  visible, pas masqué.
- N'enterre pas les zones d'incertitude : expose taux de correspondance, biais, limites
  méthodologiques.
- Si le besoin est ambigu : **une** question, puis exécute.

---

## 🧠 INSTRUCTIONS CLAUDE CODE

### Avant chaque tâche
1. Lire ce fichier en entier.
2. Lire **uniquement** les fichiers concernés par la tâche.
3. Ne pas explorer le repo entier sans demande explicite.
4. Une seule question si ambigu, puis exécuter.

### 💸 Économie de tokens (priorité)
- **Ne jamais faire transiter un CSV/Parquet volumineux par la conversation** (même filtrés
  sur les communes ciblées, DVF et DPE peuvent faire des centaines de milliers de lignes) :
  tout passe par script (DuckDB), jamais copié dans le chat.
- Édition ciblée (`str_replace`) plutôt que réécriture complète d'un script pour une petite modif.
- Réponses concises, pas de préambule inutile, pas de répétition du prompt.
- Ne pas scanner tout le repo sans demande ; ne pas relire un fichier déjà lu dans la session.
- Grouper les modifications liées dans un seul bloc d'édition.
- Commentaires de code : rares et utiles.
- Tâche touchant **> 5 fichiers** → confirmer avant de commencer.
- **Ne jamais relancer un téléchargement ou une jointure complète sans raison explicite** —
  étapes longues, résultats intermédiaires mis en cache.

### Comportement par défaut
- Chaque étape du pipeline est **idempotente** et rejouable indépendamment
  (download → clean → join → aggregate → export).
- **Jamais** de nouvelle dépendance sans la mentionner et la justifier d'abord.
- Donnée manquante ou aberrante = **documentée** (log / rapport qualité), jamais supprimée
  en silence.
- Simple et robuste plutôt que malin. C'est un projet solo, pas un produit d'entreprise.

---

## 🧰 STACK

- **Python + uv** — gestion des dépendances, lockfile `uv.lock`.
- **DuckDB** — téléchargement/filtrage/nettoyage/agrégation (SQL sur fichiers volumineux, sans
  tout charger en mémoire).
- **Parquet** — format de stockage intermédiaire (`data/processed/`).
- **API BAN** (`api-adresse.data.gouv.fr`) — géocodage des adresses DVF/DPE.
- **API ADEME** (`data-fair`, jeu `dpe-v2-logements-existants`) — récupération DPE filtrée par
  code postal.
- **Streamlit** — dashboard, déployé sur **Streamlit Community Cloud** (v1).
- **Plotly** — graphiques + carte choroplèthe IRIS (`px.choropleth_mapbox`).
- **pytest + ruff** — tests (TDD) et lint, exécutés en **CI GitHub Actions** à chaque push.
- Pas de Pull Request (projet solo) : revue de code locale à la fin de chaque ticket.

---

## 📊 DONNÉES

**DVF** — data.gouv.fr (Demandes de Valeurs Foncières), **fichier officiel brut DGFiP** (pas
la version géolocalisée Etalab — voir [ADR 0002](docs/adr/0002-dvf-brut-plus-geocodage-ban.md)).
Filtrer au téléchargement sur les départements **64 et 40** (le 40 uniquement pour les communes
limitrophes du BAB listées en `config/communes.py` — Tarnos, Ondres), jamais la France entière.
Granularité : mutation, sans identité des parties (open data RGPD-safe par construction). Pas
de lat/lon dans le fichier brut : géocodage fait en interne via l'API **BAN**
(`api-adresse.data.gouv.fr`) dans une étape dédiée du pipeline. Plage d'années **non fixée à
l'avance** — détectée et loggée à l'exécution du téléchargement.

**DPE** — data.ademe.fr (Open Data DPE, logements existants). Filtrer sur les communes ciblées
(`config/communes.py`) au téléchargement. Champs clés : étiquette A-G, adresse, année du
diagnostic, surface.

**Jointure DVF × DPE** — algorithme en 3 passes : texte exact (adresse normalisée) → repli
distance géocodée (API BAN, seuil calibré) → départage par surface (± 2m²) si plusieurs
candidats. Détail complet : [ADR 0003](docs/adr/0003-algorithme-appariement-dvf-dpe.md).
Résultat par mutation : **trouvé / non trouvé / ambigu** — les 3 taux sont une donnée du
projet, pas un détail à cacher, toujours affichés/loggés séparément. Pas d'appariement forcé
au hasard sur un cas ambigu.

**IRIS** — contours géographiques officiels INSEE/IGN (data.gouv.fr, geojson gratuit), utilisés
pour la carte choroplèthe du dashboard (prix moyen/m² par zone). Voir
[ADR 0004](docs/adr/0004-carte-choroplethe-iris.md). Jointure spatiale (point-in-polygon) entre
mutation géocodée et IRIS.

**Communes ciblées** — littoral + proche BAB : Anglet, Biarritz, Bayonne, Boucau,
Saint-Pierre-d'Irube, Bassussarry, Arcangues, Arbonne, Bidart, Guéthary, Saint-Jean-de-Luz,
Urrugne, Hendaye, Hasparren, + Tarnos et Ondres (dept. 40, comparaison BAB uniquement — voir
[ADR 0001](docs/adr/0001-communes-hors-dept-64.md)). Liste dans un seul fichier de config
(`config/communes.py`) avec code INSEE + département, jamais hardcodée ailleurs — ajouter une
commune ne doit toucher qu'un seul endroit.

---

## 🗂️ STRUCTURE

```
data/raw/          # téléchargements bruts, non versionné (.gitignore)
data/processed/    # données nettoyées / jointes / agrégées
config/communes.py # codes INSEE ciblés
pipeline/          # download_dvf(+_historique) + download_dpe → 02_clean_dvf → 02b_geocode_ban → 03_clean_dpe → 04_join → 04b_join_iris → 05_aggregate → 06_publish_dashboard_data → 07_report
dashboard/app.py   # Streamlit + Plotly (graphes + carte choroplèthe IRIS)
reports/           # synthèse PDF versionnée (07_report.py), livrable recruteurs
notebooks/         # exploration ponctuelle, jamais source de vérité du pipeline
README.md
```

---

## ✅ CHECKLIST AVANT DE SOUMETTRE

- [ ] Étape testée sur un échantillon avant traitement complet.
- [ ] Aucune dépendance nouvelle non validée.
- [ ] Taux de correspondance DVF↔DPE affiché, pas juste calculé silencieusement.
- [ ] Cas limites gérés : adresse manquante, DPE absent, prix ou surface à 0.
- [ ] Script exécuté de bout en bout sans erreur sur le périmètre défini.
- [ ] README à jour si une nouvelle étape a été ajoutée.

---

## 🛡️ PROTOCOLE ANTI-BUG

**Avant** : format des données source → comportement actuel de l'étape → impact sur les
étapes suivantes du pipeline.
**Après** : vérification sur un échantillon connu → cas limites (valeurs nulles/aberrantes) →
cohérence des totaux avant/après → régression sur le dashboard.

---

## 💻 ENVIRONNEMENT LOCAL (Windows — lire avant de lancer du Python)

- **`.venv\Scripts\python.exe` est bloqué** par la stratégie de contrôle d'application Windows
  (« os error 4551 »). `uv run`, `py`, PowerShell `&` sur ce binaire échouent tous. Ne pas
  perdre de temps à réessayer.
- **Utiliser le Python système** :
  `C:\Users\alexa\AppData\Local\Programs\Python\Python314\python.exe` (a `duckdb` 1.5.5, **pas
  `pandas`** → `.fetchall()` sur les résultats DuckDB, jamais `.df()`). Lancer depuis la racine
  du repo pour les imports du projet.
- **Dashboard périmé après un fix data** : le repo/local peut être correct alors que
  Streamlit Cloud sert encore l'ancien build (`@st.cache_data` keyé sur les args, pas la mtime).
  Vérifier d'abord le parquet committé ; si bon → **Reboot app + Clear cache** sur
  share.streamlit.io, pas de rerun pipeline.
- **Fix en aval (agrégation/publish/synthèse) = ne pas relancer download/clean/geocode/join.**
  Seuls `05_aggregate` + `06_publish_dashboard_data` (+ `07_report` pour le PDF) sont
  concernés ; le commit du fix versionne déjà les instantanés `data/dashboard/` et le PDF.
  `07_report` lit `data/dashboard/`, jamais `data/processed/` : régénérable sur un clone frais.

## 🔧 WORKFLOW

```bash
python pipeline/download_dvf.py            # DVF brut courant (dept. 64+40)
python pipeline/download_dvf_historique.py # DVF historique 2016-2020 (miroir cquest, ADR 0005)
python pipeline/download_dpe.py            # DPE post-réforme filtrés sur les communes ciblées
python pipeline/02_clean_dvf.py
python pipeline/02b_geocode_ban.py         # géocode les adresses DVF via l'API BAN
python pipeline/03_clean_dpe.py
python pipeline/04_join.py                 # appariement DVF↔DPE (texte → distance → surface) + rapport
python pipeline/04b_join_iris.py           # rattache chaque mutation géocodée à son IRIS
python pipeline/05_aggregate.py            # agrégats par commune / IRIS / étiquette DPE
python pipeline/06_publish_dashboard_data.py  # instantané versionné data/dashboard/ (déploiement Cloud)
python pipeline/07_report.py              # synthèse PDF recruteurs (reports/, lit data/dashboard/)
streamlit run dashboard/app.py            # dashboard interactif
```

- Validation de référence : chaque script tourne sans erreur, produit une sortie non vide,
  affiche un résumé (nb de lignes, % de matching, valeurs manquantes).
- **TDD (pytest)** : tests écrits avant le code pour toute logique pure — normalisation
  d'adresse, distance géocodée, départage par surface, agrégations. Tests d'intégration sur un
  échantillon fixe pour chaque étape du pipeline. CI GitHub Actions (ruff + pytest) à chaque
  push. La donnée réelle reste un test complémentaire (comparer les totaux à des chiffres
  connus, ex. volumes annuels notaires), pas un substitut à la suite pytest.
- Projet solo : pas de revue via Pull Request GitHub — la revue de code se fait en local à la
  fin de chaque ticket (voir workflow tickets), commits directs sur `main` une fois le ticket
  validé.

### Docs vivantes (optionnelles, à consulter/mettre à jour seulement si présentes)
- `TASKS.md` — backlog / étape en cours.
- `NOTES.md` — décisions méthodologiques (seuils de matching, communes ajoutées/retirées,
  biais connus).
- Ne pas les `@importer` ici (coût tokens permanent) : les lire à la demande.

---

Toujours préférer **simple, robuste, reproductible**. En cas de doute réel sur une donnée
ou une méthode : poser la question avant d'agir plutôt que de deviner.

---

## Agent skills

### Issue tracker

GitHub Issues sur `Alex6460064/Immo` (via `gh`, pas encore de clone local — `--repo` explicite
requis). Voir `docs/agents/issue-tracker.md`.

### Domain docs

Single-context : `CONTEXT.md` + `docs/adr/` à la racine. Voir `docs/agents/domain.md`.
