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
