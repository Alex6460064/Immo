# NOTES.md — décisions méthodologiques

Décisions de méthode prises en cours d'implémentation qui ne sont pas (encore) dans un ADR
dédié. Les ADR restent la source de vérité pour les grands choix ; ce fichier note les
arbitrages plus fins, avec leur date et leur justification.

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

La carte choroplèthe lit `agg_iris.parquet` tel quel — prix **moyen**/m² par IRIS,
**cumulé sur toutes les années** (ADR 0004 : la carte est un agrégat de quartier
sur ~10 ans, pas une mesure temporelle). Le filtre *Période* de la barre latérale
n'agit donc **pas** sur la carte — dit explicitement en légende pour ne pas
laisser croire à un rafraîchissement. Quand les deux types de bien sont retenus
(vue Impact DPE ; la vue Marché impose un type — cf. ci-dessous), les moyennes
par IRIS sont combinées par **moyenne pondérée de `n`** (valide pour une moyenne,
pas pour une médiane — d'où `moyenne` et non `mediane` sur la carte). Communes à
IRIS unique (code `…0000`, 7 sur 16) : rendues comme une seule zone, sans
traitement spécial (critère d'acceptation #14). La carte se recadre sur la
boîte englobante des IRIS de la commune sélectionnée
(`dashboard/data.py:geojson_center`), sinon elle reste centrée sur un point du
périmètre trop excentré pour les communes du sud (Hendaye, Urrugne).

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
