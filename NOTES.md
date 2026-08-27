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
