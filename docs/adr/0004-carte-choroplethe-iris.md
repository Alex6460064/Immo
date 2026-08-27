# Carte en choroplèthe par IRIS, pas en points individuels

La carte du dashboard doit rester lisible malgré un volume élevé de mutations cumulées sur 10
ans (points individuels superposés, illisibles à l'échelle BAB). Décision : agréger par
**IRIS** (Ilots Regroupés pour l'Information Statistique, zonage officiel INSEE/IGN,
équivalent "quartier statistique" — contours geojson gratuits sur
[data.gouv.fr](https://www.data.gouv.fr/datasets/contours-iris-geographie-2024)), couleur =
prix moyen/m² par zone. Chaque mutation géocodée (lat/lon via API BAN) est rattachée à son IRIS
par jointure spatiale (point-in-polygon).

**Alternative rejetée** : points individuels géolocalisés — illisible à l'échelle du projet
(des centaines de mutations superposées par commune).
**Alternative rejetée** : polygones de quartiers dessinés à la main — arbitraire, non
défendable niveau exactitude des données (CLAUDE.md priorité #1), remplacée par un zonage
officiel existant.

**Limite connue à documenter** : les communes < ~5-10k habitants n'ont qu'un seul IRIS (= la
commune entière) — pas de sous-découpage disponible pour elles, à afficher tel quel plutôt que
masqué.

---

## Statistique de couleur : médiane (implémentation T13, 2026-08-27)

Cet ADR dit « couleur = prix moyen/m² par zone ». À l'implémentation du dashboard
(#14), la **médiane**/m² par IRIS a été retenue à la place de la moyenne :
vérifié à l'écran, un IRIS à quelques mutations multi-lots aberrantes (DVF ne
déduplique pas maison + garage) porte sa moyenne à ~70 000 €/m² et écrase toute
l'échelle de couleur. La médiane est déjà la statistique de référence du projet
pour cette raison (voir `NOTES.md`, « Valeurs prix/m² extrêmes non filtrées »).
Le principe de l'ADR — agrégat de quartier, zonage IRIS officiel — est inchangé.

## Source concrète des contours (implémentation T11, 2026-08-27)

Le GeoJSON national « Contours IRIS » n'est plus proposé en téléchargement direct sur
data.gouv.fr (« File too large » — la fiche renvoie désormais vers des services web). Le
pipeline (`pipeline/04b_join_iris.py`) interroge donc l'**API WFS officielle de l'IGN**
(Géoplateforme, `data.geopf.fr`), couche `STATISTICALUNITS.IRIS:contours_iris` — même donnée
IGN/INSEE que le fichier, servie par l'opérateur officiel. La requête est filtrée
(`CQL_FILTER code_insee IN (...)`, codes lus dans `config/communes.py`) aux 16 communes
ciblées : ~75 IRIS, ~250 Ko, jamais la France entière.

**Vérifié en direct le 2026-08-27** : `DescribeFeatureType` (attribut `code_insee`, géométrie
`MultiSurface`) et `GetFeature` filtré → 75 features sur les 16 communes attendues, dont
plusieurs communes à IRIS unique (limite ci-dessus confirmée).

**Reproductibilité** : le WFS ne versionne pas explicitement le millésime ; l'ancre de
reproductibilité est le GeoJSON téléchargé, mis en cache dans
`data/raw/iris_communes.geojson` (idempotent, supprimer pour re-télécharger). `data/raw/`
étant en `.gitignore`, une perte locale + une évolution du WFS re-géocoderaient les mutations
contre des contours potentiellement plus récents — acceptable (les IRIS bougent peu ; la carte
est un agrégat de quartier, pas une mesure fine).
