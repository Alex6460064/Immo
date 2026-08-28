# NOTES.md — décisions méthodologiques

Décisions de méthode prises en cours d'implémentation qui ne sont pas (encore) dans un ADR
dédié. Les ADR restent la source de vérité pour les grands choix ; ce fichier note les
arbitrages plus fins, avec leur date et leur justification.

---

## 2026-08-28 — Chaîne Impact DPE unifiée (`pipeline/lib/impact_dpe.py`, issue #28)

La chaîne `mutation_price_points(extra_keys) → filtre → impact_dpe_rows(cutoff) → aggregate_by`
était écrite deux fois (`pipeline/05_aggregate.py` pour `agg_dpe.parquet` ; `dashboard/data.py`
pour la ré-agrégation filtrée de la vue #15), synchronisées seulement par des docstrings.
Littéral `extra_keys=("etiquette_dpe", "match_status")` répété 3×, comptage pré-réforme écrit
2× avec des formulations différentes, `impact_dpe_breakdown` recalculant sa propre copie.

**Décision** (grilling 2026-08-28, jumelle de #27) : un seul module `pipeline/lib/impact_dpe.py`
qui possède `impact_dpe_rows` (déplacé depuis `aggregate.py`) et `impact_dpe_slice(matched_rows,
*, cutoff, keep=None) → ImpactDpeSlice` (6 champs : `points`, `n_points`, `etiquette_certaine`,
`resolu_consensus`, `pre_reforme`, `exclusions`). Découpage : la lib = mécanique
repli/filtre/cutoff + comptages ; le dashboard = sémantique de la sélection UI (`matched_keep`
construit un prédicat `keep`, `dpe_group` / bornes de période restent côté dashboard).
`aggregate.py` redevient groupement générique pur. Invariant testé
(`test_slice_sans_keep_egale_recette_pipeline`) : `impact_dpe_slice` sans `keep` agrège
exactement les mutations de `agg_dpe.parquet`.

**Non-régression** : sortie stdout de `05_aggregate.py` identique au bit ; sha256 des 3
`agg_*.parquet` inchangés ; `impact_dpe_aggregate` sans filtre = `agg_dpe` regroupé (A-C
Appartement 4484 = 49+313+4122, etc.) ; breakdown 10816 / 2546 / 12983 = rapport pipeline.
`04_join` / `dvf_dpe_matched.parquet` / instantané `data/dashboard/` non touchés.

---

## 2026-08-28 — Refonte UI dashboard : vue Marché (courbe de référence + toggle stat), vue Impact DPE (commune obligatoire)

**Vue Marché.** Par défaut, une seule courbe : prix/m² **toutes communes confondues** par année,
ré-agrégée depuis les mutations (`market_trend_global` → `mutation_price_points` → `aggregate_by(["annee"])`).
`st.multiselect` « Communes à comparer » superpose une courbe par commune cochée. Évite le fouillis
des 16 courbes par défaut. Le `selectbox` « Carte — commune » (inchangé) ne pilote plus que la carte IRIS.

**Type de bien « Tous »** (comme la vue Impact DPE) : une courbe **par type**, jamais une série
fusionnant maison + appartement (populations distinctes, stat mélangée = non-sens — principe conservé,
`mutation_price_points` n'émet d'ailleurs de point que pour les mutations mono-type habitation).
Encodage : couleur = commune, trait = type (plein maison / pointillé appartement). La carte IRIS ne
peut porter qu'une valeur par zone → sous « Tous » elle affiche un message « choisir un type précis »,
pas de fusion silencieuse.

**Statistique : moyenne par défaut** (toggle `Moyenne` / `Médiane` dans la sidebar), pilote la courbe
**et** la carte. Revirement assumé vs le choix initial « médiane = stat de référence » (ADR 0004) :
demande explicite pour la lisibilité « prix moyen au m² ». Le prix/m² étant déjà calculé par mutation
et borné [200, 30 000] en amont (#26), la moyenne d'ensemble n'est plus polluée par les ventes en bloc ;
`agg_marche` / `agg_iris` portaient déjà les deux colonnes, aucun re-run pipeline. Médiane reste
disponible d'un clic. Non-régression (jeu courant, Maison) : courbe globale 2016 → 2025 de
~3 250 à ~5 000 €/m² médiane (moyenne ~3 550 → ~5 600) ; n global = 10 320 = Σ agg_marche Maison.

**Vue Impact DPE : commune obligatoire** (défaut Anglet), plus d'option « Toutes ». Mélanger les
communes n'est pas comparable : un bien F à Biarritz front de mer reste plus cher qu'un bien A à
Hasparren. Regroupement A-C / D / E / F-G conservé : par commune, A/B et G sont trop rares pour une
barre isolée (ex. Guéthary A=1, Arcangues G=0, Bassussarry F=G=0) ; A-C = « performant », F-G =
passoires thermiques (catégorie réglementaire), D et E séparés car gros volume. Anglet (contrôle) :
8 barres, n de 25 (F-G Appartement) à 832 (A-C Appartement).

---

## 2026-08-28 — Repli mutation pour le prix/m² (issue #26, ADR 0006)

Carte dashboard : IRIS « Sud » de Tarnos à **82 339 €/m²** médiane appartement. Cause :
`Valeur foncière` DVF est un montant de mutation recopié sur chaque ligne-lot du brut DGFiP,
et le pipeline divisait par la surface d'un seul lot → une vente en bloc (promoteur) à
6,6 M€ pour 65 appartements donnait 65 lignes à ~100 000 €/m².

**Décision** (grilling 2026-08-28, détail dans [ADR 0006](docs/adr/0006-repli-mutation-prix-m2.md)) :
`pipeline/lib/mutations.py` replie les lignes par mutation
(`(date_mutation, code_insee, no_disposition, prix)`) avant tout calcul. Prix/m² =
`prix ÷ Σ surface habitation`, habitation = Appartement + Maison, mono-type seulement
(mutation mixte habitation+commercial exclue et comptée). Garde-fous : `nature_mutation`
∈ {Vente, VEFA, Adjudication}, prix/m² ∈ [200, 30 000]. `agg_marche`/`agg_iris` = 1 point
par mutation ; `agg_dpe` = 1 point par (mutation, étiquette). `n` = transactions, plus lots.

**Chiffres de référence pour la non-régression** (jeu courant) : Tarnos « Sud »
appartement **2 352 €/m²** (n=15) ; médiane IRIS max = Biarritz « Front de Mer » maison
8 675 €/m² ; aucun IRIS > 30 000. Vue Marché : 44 626 points transaction ; exclusions
746 mixtes / 99 nature / 228 hors bande. Taux d'appariement DVF↔DPE **inchangés** (la
jointure n'est pas touchée).

Le dashboard : `color_range` ne plafonne plus au 95ᵉ centile ; encart « médiane aberrante
— issue #1 » retiré ; instantané `data/dashboard/dvf_dpe_matched.parquet` + 3 colonnes
(`code_insee`, `no_disposition`, `nature_mutation`).

---

## 2026-08-27 — Seuil de distance passe 2 : `DISTANCE_THRESHOLD_M = 15`

Calibré sur 5 733 paires (adresse normalisée identique DVF↔DPE, géocodées des deux côtés).
Distribution dégénérée : ~96 % à exactement 0 m, pas de bande de jitter, le reste = échecs de
géocodage à l'échelle du km. 15 m = borne basse défendable pour un texte proche mais non
identique (BIS/TER, numéro manquant). Détail complet au bas de
[ADR 0003](docs/adr/0003-algorithme-appariement-dvf-dpe.md).

## 2026-08-27 — Appariement DVF↔DPE (T10) : taux et cas « ambigu »

Sur 56 929 mutations : **trouvé 34,6 % / non trouvé 18,4 % / ambigu 46,9 %**.

L'ambigu élevé est une donnée du projet, pas un défaut : en habitat collectif dense (BAB),
plusieurs logements d'un même immeuble partagent adresse normalisée + surface à ± 2 m² —
l'algorithme (ADR 0003) refuse de trancher au hasard. À afficher tel quel sur la vue
« Impact DPE » (user story #33), jamais masqué ni résolu de force.

## 2026-08-27 — Vue « Impact DPE » (agg_dpe) : mutations ≥ juillet 2021 uniquement

`pipeline/05_aggregate.py` restreint l'agrégat prix/m² par étiquette DPE aux mutations
`date_mutation >= 2021-07-01` (`POST_REFORM_CUTOFF`), en plus du filtre « trouvé ».

**Pourquoi** : le DPE post-réforme n'existe pas avant juillet 2021. L'algorithme d'appariement
(adresse + surface) rapproche aussi des mutations plus anciennes d'un DPE établi bien après la
vente — **sur le jeu courant, ~53 % des « trouvé » (10 448 / 19 721) sont des mutations
< 2021-07**. Apparier un prix de 2017 à un DPE de 2023 ne mesure rien de l'effet du DPE sur ce
prix. Cohérent avec `CONTEXT.md` (« Vente appariée … structurellement limité aux ventes
proches ou postérieures à juillet 2021 ») et avec le scope verrouillé au grilling du
2026-08-25 (« Impact DPE = matched subset 2021+ only »).

Les paires antérieures **restent dans `dvf_dpe_matched.parquet`** (transparence) et sont
comptées séparément dans le résumé de `04_join.py` et `05_aggregate.py` — juste hors de cet
agrégat. Le décalage résiduel (vente 2021-2022 / DPE 2024) est porté par la note
d'avertissement de la vue (user story #34).

## 2026-08-27 — Vue « Marché » (agg_marche) : toutes les années (2016+)

Le commentaire de l'issue #13 disait « 2021+ ». Il est antérieur à
[ADR 0005](docs/adr/0005-source-historique-dvf-2016-2020.md), qui a (re)introduit le DVF
historique 2016-2020 (miroir cquest) **exactement pour** donner une tendance de prix sur
~10 ans à la vue « Marché ». `agg_marche` porte donc toutes les années disponibles ; ADR 0005
fait foi.

## 2026-08-27 — `type_local` : dimension de groupement, pas un filtre

Les 3 agrégats sont groupés par `type_local` (Appartement / Maison / Local commercial /
Dépendance) — aucune mutation n'est exclue sur ce critère (CLAUDE.md : pas de suppression
silencieuse). Le dashboard filtre maison / appartement côté lecture (user story #35). Chaque
ligne d'agrégat porte son `n=`, donc les petits groupes (Dépendance, n≈7) restent visibles.

## 2026-08-27 — Valeurs prix/m² extrêmes non filtrées

DVF ne déduplique pas une mutation multi-lots (maison + garage = 2 lignes, même prix total,
surfaces différentes → prix/m² aberrant sur la ligne du petit lot). Le traitement avancé des
aberrations est **Out of Scope** (issue #1). Conséquence assumée : la **médiane** est la
statistique de référence (robuste), la moyenne est fournie mais sensible. `05_aggregate.py`
affiche le nombre de lignes hors [200, 30 000] €/m² (jeu courant : 1 753) pour rester visible.

## 2026-08-27 — Dashboard vue « Impact DPE » (#15) : ré-agrégée à la volée

Le graphique prix/m² de la vue « Impact DPE » est **recalculé à la lecture**
depuis `dvf_dpe_matched.parquet`, pas lu depuis `agg_dpe.parquet`.

**Pourquoi** : `agg_dpe.parquet` (#T12) n'est indexé que par (étiquette exacte,
type de bien) — il ne permet ni les filtres **commune** / **période** demandés
par #15, ni le **regroupement A-C / D / E / F-G** que le ticket décrit
explicitement (« prix/m² par étiquette DPE (A-C/D/E/F-G) »). Une médiane par
regroupement ne se recompose pas à partir des médianes par lettre.
`dashboard/data.py:impact_dpe_aggregate()` applique les filtres sur les lignes
brutes puis réutilise **les mêmes fonctions pures** que
`pipeline/05_aggregate.py` (`impact_dpe_rows` → `price_per_m2` → `aggregate_by`),
en groupant par `dpe_group(etiquette)` × type de bien. Sans filtre
commune/période, **les mêmes mutations** sont agrégées que dans `agg_dpe.parquet`
(mêmes effectifs totaux) — seule la maille de groupe diffère. `agg_dpe.parquet`
reste la sortie canonique du pipeline (témoin de non-régression CI).
`dvf_dpe_matched.parquet` fait 56 929 lignes — chargé en entier sans souci.

Regroupement plutôt que 7 barres A→G : sur le sous-ensemble apparié post-réforme,
plusieurs lettres ont un `n` trop faible pour une médiane lisible commune par
commune. Le `n` de chaque barre reste affiché (au survol) — CLAUDE.md : pas de
petit groupe masqué.

Taux d'appariement affiché sur la vue : les **4 états** (`trouvé` 37,8 % /
`resolu_consensus` 12,1 % / `non trouvé` 18,4 % / `ambigu` 31,7 %) sur
l'**ensemble du périmètre** (pas re-filtré par commune/période — donnée de
cadrage du projet, CONTEXT.md). Mention « dont N résolus par consensus » +
avertissement décalage temporel DVF (2016+) / DPE (juillet 2021+) portés en clair
sur la vue.

## 2026-08-27 — Dashboard carte IRIS (#14) : cumul toutes années

La carte choroplèthe lit `agg_iris.parquet` — prix/m² par IRIS, **cumulé sur
toutes les années** (ADR 0004 : agrégat de quartier sur ~10 ans, pas une mesure
temporelle). Le filtre *Période* n'agit donc **pas** sur la carte — dit en
légende pour ne pas laisser croire à un rafraîchissement.

**Couleur = médiane, pas moyenne** (précise la formulation « prix moyen/m² »
d'ADR 0004). Vérifié à l'écran : avec la moyenne, un IRIS à quelques mutations
multi-lots aberrantes montait à ~70 000 €/m² et écrasait toute l'échelle de
couleur (reste uniformément violet). La médiane est déjà la stat de référence du
projet (entrée « Valeurs prix/m² extrêmes non filtrées » ci-dessous). Comme la
vue Marché impose un type de bien, chaque IRIS a une seule ligne `agg_iris` —
pas de recombinaison inter-types à faire.

Communes à IRIS unique (code `…0000`, 7 sur 16) : rendues comme une seule zone,
sans traitement spécial (critère d'acceptation #14). La carte se recadre sur la
boîte englobante des IRIS de la commune sélectionnée
(`dashboard/data.py:geojson_center`), sinon les communes du sud (Hendaye,
Urrugne) tombaient hors cadre.

Trace : `go.Choroplethmap` (MapLibre, sans jeton). `px.choropleth_mapbox`
mentionné dans l'issue #14 est déprécié depuis Plotly 6 — même rendu.

## 2026-08-27 — Dashboard vue « Marché » : un type de bien obligatoire

La courbe de tendance trace une **médiane** de prix/m². Mélanger maisons et
appartements dans une même médiane annuelle n'a pas de sens (deux populations de
prix distinctes) et produisait une courbe en zigzag. Le sélecteur *Type de bien*
de la vue Marché n'a donc **pas** d'option « Tous » — maison **ou** appartement,
défaut appartement. La vue Impact DPE garde « Tous » : les barres y restent
séparées par type, chaque barre est une médiane homogène.

## 2026-08-27 — Récupération des ambigus (#23) : spike de mesure + gate

Script jetable (scratchpad, non versionné) sur le jeu courant (56 929 mutations / 61 277 DPE).
Baseline reproduit exactement 34,6 / 18,4 / 46,9. Sweep :

| config | trouvé | consensus | non trouvé | ambigu |
|---|---|---|---|---|
| baseline (algo actuel) | 34,6 % | — | 18,4 % | **46,9 %** |
| B (dédup, clé période) | 36,3 % | — | 18,4 % | 45,3 % |
| B + C (filtre type) | 37,8 % | — | 18,4 % | 43,8 % |
| **B + C + A2 (consensus étiquette)** | **37,8 %** | **12,1 %** | **18,4 %** | **31,7 %** |
| B + C + A2 (consensus étiquette **+ GES**) | 37,8 % | 9,2 % | 18,4 % | 34,6 % |

**Dédup B** : clé `période` retire 12 920 DPE (4 533 groupes fusionnés) ; `année` 12 833,
`signature seule` 13 039 — quasi équivalent, `période` retenu (couverture 100 % vs 48 % pour
`année`). 4 069 des 4 533 groupes fusionnés ont toutes leurs dates d'établissement < 90 j :
ce sont des logements à plan identique diagnostiqués ensemble (immeuble neuf), pas des
renouvellements. Fusion **analytiquement neutre** : la clé inclut `etiquette_dpe` + `etiquette_ges`,
B ne change donc jamais une étiquette ; `agg_dpe` n'est pas affecté. Risque résiduel = un
`numero_dpe` qui pointe l'un de deux enregistrements indistinguables — sans effet sur la sortie.

**Filtre C** : resserre le pool sur 5 047 mutations (8,9 %), le vide sur 741 (narrow-only D1 :
pool gardé, jamais de `non_trouve` créé), et laisse 1 414 `trouvé` pool==1 à type
contradictoire (C n'est pas un validateur — typo `type_batiment` probable).

**Consensus A2** : étiquette seule fait basculer 6 873 ambigus (−12,1 pts) ; +GES n'en
récupère que 5 238 (−2,9 pts de perte pour aucun gain sur `agg_dpe` qui ne lit pas le GES).
**D5 confirmé par les chiffres** : consensus sur `etiquette_dpe` seule.

**Périmètre `agg_dpe` (mutation ≥ 2021-07)** : `trouvé` 10 065 + `resolu_consensus` 2 829 =
**+28 % de matière analytique**.

**Gate — décision : on implémente B + C + A2 (consensus étiquette seule) en entier.** Les trois
briques passent leurs seuils (§8 de la spec) : B analytiquement neutre, C départage 8,9 %
(≫ 1 %), A2 −12,1 pts d'ambigu (≫ 2 pts). Nouveaux taux de référence pour la non-régression :
**trouvé 37,8 % / resolu_consensus 12,1 % / non trouvé 18,4 % / ambigu 31,7 %**.

## 2026-08-27 — Instantané de données versionné `data/dashboard/` (#24)

Streamlit Community Cloud déploie **le repo**, sans exécuter le pipeline. Le dashboard lisait
4 fichiers tous sous `.gitignore` (`data/processed/*`, `data/raw/*`) → rien à afficher sur un
clone frais.

**Choix** : un dossier **tracké** `data/dashboard/` (2 agrégats + `iris_communes.geojson`
copiés tels quels ; `dvf_dpe_matched.parquet` réduit aux 7 colonnes lues par le dashboard —
2,5 Mo → 393 Ko). Produit **uniquement** par `pipeline/06_publish_dashboard_data.py`, jamais
posé à la main. `dashboard/data.py:_source()` lit `data/processed/<f>` si présent (dev local
après un run pipeline), sinon l'instantané.

**Idempotence** : agrégats + geojson = copie octet à octet ; le parquet matched est
re-projeté via DuckDB avec `ORDER BY ALL` pour figer l'ordre des lignes → à version DuckDB
constante, deux exécutions successives donnent des fichiers identiques (vérifié par hash),
pas de churn git. Un bump de version DuckDB réécrit le pied de page Parquet (`created_by`)
sur données identiques — sans conséquence, on recommitte l'instantané régénéré.

**Rafraîchir l'instantané** : après un nouveau run du pipeline, `uv run python
pipeline/06_publish_dashboard_data.py` puis committer `data/dashboard/`. La liste des 7
colonnes vit dans `pipeline/lib/publish_dashboard.py` (`DASHBOARD_MATCHED_COLUMNS`),
importée par `dashboard/data.py` — une seule source, pas de dérive possible.

## 2026-08-27 — Manifeste de dépendances pour Streamlit Cloud (#25)

`requirements.txt` (deps de prod uniquement) plutôt que le support `uv` natif de Streamlit
Cloud : universel, pas de surprise de résolution côté plateforme. Il se **régénère depuis
`uv.lock`** (la source de vérité reste `pyproject.toml` + `uv.lock`) :

```bash
uv export --no-dev --no-hashes --no-emit-project --format requirements-txt -o requirements.txt
```

À refaire à chaque changement de dépendance. `.python-version` passé de `3.14` à **`3.12`** :
aligne le runtime Cloud sur `requires-python = ">=3.12"` — 3.12 est disponible partout, pas
de pari sur la dernière version supportée par la plateforme. Suite pytest vérifiée verte sur
3.12.
