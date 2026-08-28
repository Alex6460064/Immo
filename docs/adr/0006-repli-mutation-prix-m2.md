# Prix au m² calculé au niveau mutation, pas au niveau lot

## Contexte

Le fichier brut DGFiP porte **une ligne par lot** d'une mutation. La colonne
`Valeur foncière` y est le montant de la **mutation entière**, recopié verbatim
sur chacune de ses lignes. Jusqu'à l'issue #26, tout le pipeline d'agrégation
(`pipeline/lib/aggregate.price_per_m2`, appelé ligne à ligne) calculait
`prix / surface` **par ligne**.

Pour une vente en bloc — un promoteur ou un bailleur institutionnel achetant une
résidence entière en un acte — chaque lot d'environ 55 m² se voyait donc
attribuer le prix total de l'immeuble, soit ~100 000 €/m², répété sur des dizaines
de lignes. Une poignée de ces ventes suffisait à faire de la médiane d'un IRIS un
chiffre absurde.

**Cas déclencheur (issue #26)** : 3 place des Troubadours, Tarnos, 25/09/2017 —
6 587 120 € pour 65 lots d'appartement (4 741 m² au total, soit **1 389 €/m²**
réels). Le pipeline produisait 65 lignes à ~100 000 €/m² ; l'IRIS « Sud » de
Tarnos, qui ne compte que 15 autres ventes d'appartement sur dix ans, affichait
une médiane de **82 339 €/m²** sur la carte du dashboard.

Ampleur mesurée sur le jeu courant : ~236 ventes en bloc (≥ 5 lots, même prix)
sur le périmètre, ~2 700 lignes à prix/m² aberrant. `agg_iris`, `agg_marche` et
`agg_dpe` étaient tous touchés (~20 % des lignes à étiquette DPE certaine
appartiennent à des mutations multi-lots).

L'en-tête de `pipeline/05_aggregate.py` déclarait ce traitement « Out of Scope
(issue #1) » et s'appuyait sur la seule robustesse de la médiane. Le dashboard
compensait par un plafonnement de l'échelle de couleur au 95ᵉ centile. Ni l'un ni
l'autre ne suffisait : la carte montrait toujours des zones fausses.

## Décision

Le prix/m² est désormais une propriété de la **mutation**, calculée avant toute
agrégation par `pipeline/lib/mutations.py` (`mutation_price_points`, logique pure
testée). Cette ADR **annule** la note « hors scope #1 » de l'en-tête de
`05_aggregate.py`.

### Clé de mutation

`(date_mutation, code_insee, no_disposition, prix)`. `Identifiant de document`
est NULL sur tout le jeu (brut DGFiP courant comme miroir historique cquest,
[ADR 0005](0005-source-historique-dvf-2016-2020.md)), donc inutilisable. La valeur
foncière porte l'essentiel de la spécificité ; `no_disposition` sépare les
dispositions d'un même acte. Le coût d'une collision résiduelle (deux petites
ventes distinctes, même commune, même jour, même prix exact) est un point prix/m²
légèrement décalé, jamais aberrant.

### Règle C — habitation mono-type

Un point prix/m² n'est émis que si la mutation est **mono-type habitation** :
tous ses lots bâtis sont soit des `Appartement`, soit des `Maison` (pas un mélange
des deux). Les lignes `Dépendance` sont **ignorées** (ni au numérateur, ni au test
de pureté — le cas « maison + garage » reste calculé sur la seule surface de la
maison). Une mutation mêlant habitation et `Local industriel. commercial ou
assimilé` est **exclue** : la valeur foncière couvre alors les deux et aucune
répartition n'est défendable (sur le jeu courant, la part commerciale va jusqu'à
97 % de la surface — diviser le prix total par la seule surface habitation
donnerait 7 250 €/m² là où le vrai chiffre est ~216).

Prix/m² de la mutation = `prix / Σ(surface habitable des lots habitation)`.

### Règle A — garde-fous

- `nature_mutation` ∈ {`Vente`, `Vente en l'état futur d'achèvement`,
  `Adjudication`}. Exclut `Échange` (pas de prix en numéraire) et
  `Vente terrain à bâtir` (pas de bâti).
- Prix/m² ∈ **[200, 30 000] €/m²**. En dehors : saisie DGFiP douteuse — cession
  symbolique à 1 € (démembrement, vente intra-familiale), ou `Surface réelle
  bâti` grossièrement sous-déclarée (villa à 3,4 M€ enregistrée « 30 m² »).

Les exclusions sont **comptées par motif** dans le rapport de `05_aggregate.py`,
jamais silencieuses (CLAUDE.md).

### Granularité des agrégats

- `agg_marche` et `agg_iris` : **un point par mutation**. Tous les lots d'une
  vente partagent commune / année / type / IRIS.
- `agg_dpe` : **un point par (mutation, étiquette_dpe)** — une vente en bloc
  apparie chaque lot à son propre DPE ; sans repli, un deal institutionnel de
  70 lots pesait 70 points dans une classe DPE. Le dénominateur du prix/m² reste
  la surface habitation de **toute** la mutation, jamais celle du sous-groupe
  d'une seule étiquette.

`n` compte désormais des **transactions**, plus des lots — ce qui est le sens
correct de « prix médian au m² d'une zone ».

### Dashboard

- `dashboard/data.py` : la re-agrégation live de la vue « Impact DPE » utilise la
  même chaîne (`mutation_price_points` → `impact_dpe_rows` → `aggregate_by`).
  L'instantané `data/dashboard/dvf_dpe_matched.parquet` gagne trois colonnes
  (`code_insee`, `no_disposition`, `nature_mutation`) requises par la clé de
  mutation et la règle A.
- `color_range` : le plafonnement au 95ᵉ centile est **retiré** (l'échelle
  reflète les vraies valeurs, il n'y a plus d'IRIS aberrant à cacher).
- L'encart « médiane aberrante — issue #1 » de la carte est supprimé.

## Portée volontairement limitée

Le repli ne touche **que la couche d'agrégation**. `dvf_clean`, `dvf_geocoded`,
`dvf_iris` et `dvf_dpe_matched` gardent la granularité ligne-lot : l'appariement
DVF ↔ DPE ([ADR 0003](0003-algorithme-appariement-dvf-dpe.md)) rapproche bien un
logement d'un diagnostic, il travaille au bon niveau.

## Alternatives rejetées

- **Nouvelle étape de pipeline repliant `dvf_clean` en mutations** avant le
  géocodage : conceptuellement le plus propre, mais casse l'appariement DPE
  par lot et impose un changement de schéma sur quatre parquets — trop lourd
  pour un projet solo.
- **Répartition au prorata des surfaces** pour les ventes mixtes
  habitation + commercial : récupère ~600 mutations mais suppose un prix/m²
  uniforme entre commerce et logement, ce que les données démentent — exactement
  la « supposition silencieuse » que CLAUDE.md interdit.
- **Filtre `nature_mutation` seul, sans bande de cohérence** : laisse les ~230
  mutations à 1 € ou à surface sous-déclarée tirer la médiane des petits IRIS.

## Limite connue — collision de clé sur ventes identiques le même jour

La clé `(date_mutation, code_insee, no_disposition, prix)` ne peut pas distinguer
deux mutations **réellement distinctes** qui partageraient la date, la commune,
le n° de disposition (`000001` presque partout) *et* le prix exact — par exemple
un promoteur vendant plusieurs lots neufs identiques au même prix le même jour.
Elles seraient repliées en une seule « mutation », surfaces sommées, et le prix/m²
résultant (≈ prix_unitaire ÷ N) serait faux, voire écarté par la bande basse.

**Mesuré sur le jeu courant** : parmi les groupes multi-lots de même clé, 23
(184 lignes) ont un prix/m² replié < 200 €/m² alors que le prix/m² par ligne
serait dans la bande. Inspection manuelle : ce sont des **vraies ventes en bloc**
(6,5 M€ pour 45 lots à Anglet, blocs d'investisseur récurrents à Bayonne) ou des
**cessions symboliques** (21 000 € pour 6 lots) — exactement les cas que la bande
doit écarter. Les 7 groupes VEFA multi-lots affichent un prix/m² replié réaliste
(2 000–6 000 €/m² à Biarritz / Saint-Jean-de-Luz), c.-à-d. le repli est correct.
**Aucun cas observé de N ventes retail distinctes fusionnées à tort.** Le risque
reste théorique ; le documenter suffit (CLAUDE.md : exposer les limites).

## Vérification

- `pipeline/lib/mutations.py` : 23 tests unitaires (clé, repli bloc, règles C et
  A, `extra_keys`). Suite complète verte (342 tests).
- Exécution réelle : IRIS « Sud » de Tarnos passe de **82 339** à **2 352 €/m²**
  (appartement, n=15) ; plus aucun IRIS au-dessus de 30 000 €/m² ; médiane IRIS
  maximale = Biarritz « Front de Mer » à 8 675 €/m² (maison), plausible.
- 44 626 points transaction pour la vue Marché ; exclusions loggées :
  746 mixtes, 99 nature, 228 hors bande.
