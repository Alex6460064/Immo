# Design — Récupération des ambigus DVF × DPE (dédup + filtre type + consensus)

Date : 2026-08-27
Statut : proposé (revue en attente)
Contexte lié : [ADR 0003](../../adr/0003-algorithme-appariement-dvf-dpe.md), `NOTES.md` (T10),
`CONTEXT.md` (terme « Ambigu »), issue #11.

---

## 1. Problème

Jeu courant : 56 929 mutations → **trouvé 34,6 % / non trouvé 18,4 % / ambigu 46,9 %**.
Parmi les 19 721 « trouvé », 10 448 portent sur une mutation < 2021-07 (exclues de la vue
Impact DPE).

L'ambigu de la passe 3 est une ambiguïté **d'identité de l'enregistrement DPE**, pas
forcément une ambiguïté **de la réponse analytique**. `agg_dpe` (vue Impact DPE) ne consomme
que `etiquette_dpe` + `type_local` — jamais `numero_dpe`, ni conso, ni GES. Donc :

- si N candidats indistinguables portent **tous** la même étiquette **et** le même GES, la
  mutation tombe dans le même bucket `agg_dpe` quel que soit « le bon » enregistrement →
  l'ambiguïté d'identité est sans effet sur la sortie ;
- une partie des « candidats » sont en réalité **le même logement diagnostiqué plusieurs
  fois** (renouvellement, correction, DPE de vente) — bruit de données, pas une vraie
  ambiguïté ;
- le pool de candidats n'est pas filtré par cohérence de type de bien (un DPE `maison`
  géocodé au même point qu'une vente d'appartement reste candidat).

## 2. Objectif

Réduire le taux d'ambigu en traitant ces trois causes, **sans jamais trancher au hasard**
sur une vraie ambiguïté (principe ADR 0003 / CONTEXT.md), et en gardant chaque niveau de
certitude **visible et distinct** dans les logs, le parquet et le dashboard.

Non-objectif : forcer un `numero_dpe` quand il reste incertain ; toucher aux passes 1 et 2
existantes ; modifier le seuil de distance (ADR 0003 / T9).

## 3. Approche retenue

Trois briques, dans cet ordre d'exécution :

### B — Déduplication des DPE redondants (nettoyage)

Avant construction de l'index de candidats (`build_dpe_index`), au sein d'une commune
(`code_insee_ban`) et d'une même `adresse_normalisee`, regrouper les DPE identiques sur la
**signature analytique + bâti** :

```
clé_dédup = (
    round(surface_habitable_logement, 1),
    etiquette_dpe,
    etiquette_ges,
    annee_construction,          # None si absent — bucket à part
    type_batiment,
)
```

Dans chaque groupe, garder **un seul** enregistrement : `date_etablissement_dpe` la plus
récente (départage déterministe : `numero_dpe` max). Compter les lignes retirées, les
logger dans le rapport de `04_join.py`.

Risque assumé : deux logements réellement distincts d'un même immeuble, identiques sur toute
la signature, sont fusionnés en un. Leur signature analytique étant identique, `agg_dpe`
n'est pas affecté. Documenté dans ADR 0003 + NOTES.md.

### C — Filtre `type_batiment` sur le pool de candidats

Après sélection de voie (passe 1 texte exact ou passe 2 distance), avant la passe 3 surface,
filtrer le pool :

| `type_local` (DVF) | candidats retirés |
|---|---|
| `Appartement` | `type_batiment == "maison"` |
| `Maison` | `type_batiment == "appartement"` |
| autre / absent | aucun filtre |

`type_batiment == "immeuble"` (DPE collectif) est **conservé** dans les deux cas.

**Décision à confirmer (D1)** : comportement quand le filtre vide le pool.
Proposé : *narrow-only* — si le filtre laisse 0 candidat, on l'ignore et on repart du pool
non filtré (C ne crée jamais un non-appariement à lui seul, il ne fait que resserrer).
Alternative : pool vidé → `non_trouve` (tous les candidats contredisent le type de bien).

### A2 — Récupération par consensus étiquette + GES

Nouvelle **passe 4**, après la passe 3 surface, quand celle-ci n'a pas isolé exactement 1
candidat. Sur le sous-ensemble de candidats retenu (voir §4), si **tous** partagent :

- la même `etiquette_dpe` non nulle, **et**
- la même `etiquette_ges` non nulle

→ mutation **`resolu_consensus`** : on porte `etiquette_dpe` + `etiquette_ges` (valeurs du
consensus), `numero_dpe` reste `NULL` (l'identité reste inconnue). Sinon → `ambigu`.

## 4. Ordre des passes (algorithme complet après changement)

```
dédup DPE (B, une fois par commune, à la construction de l'index)
  │
  ▼  pour chaque mutation :
passe 1  texte exact  → pool = DPE à adresse_normalisee identique
passe 2  distance     → si pool passe 1 vide : pool = DPE géocodés ≤ seuil (ADR 0003)
  │
filtre C type_batiment sur le pool (narrow-only, cf. D1)
  │
  ├─ pool vide            → non_trouve
  ├─ pool == 1            → trouve            (methode : texte_exact | distance | *_type)
  └─ pool > 1 :
        passe 3  surface ±2 m² → within
          ├─ within == 1       → trouve       (methode : *_surface)
          └─ sinon :
                passe 4  consensus (A2) sur  within si len(within) ≥ 2, sinon pool
                  ├─ consensus étiquette + GES → resolu_consensus
                  └─ sinon                     → ambigu
```

**Sous-ensemble de la passe 4** : `within` (candidats dans ±2 m²) s'il en reste au moins 2 ;
sinon (surface manquante côté mutation, ou 0 candidat dans la tolérance) le pool d'entrée de
la passe 3. Rationnel : quand la surface ne discrimine rien, la question honnête du consensus
porte sur l'ensemble du bâtiment.

## 5. États de sortie — 3 → 4

`match_status` passe de `{trouve, non_trouve, ambigu}` à
`{trouve, resolu_consensus, non_trouve, ambigu}`.

| état | sens | `numero_dpe` | `etiquette_dpe` / `_ges` |
|---|---|---|---|
| `trouve` | 1 DPE identifié | renseigné | du DPE |
| `resolu_consensus` | identité incertaine, **étiquette + GES certains** | `NULL` | du consensus |
| `ambigu` | plusieurs candidats, pas de consensus | `NULL` | `NULL` |
| `non_trouve` | aucun candidat | `NULL` | `NULL` |

`resolu_consensus` se lit comme *« ambigu sauvé »*, pas comme *« trouvé dégradé »* — dans les
rapports il est listé après `trouve`, avant `ambigu`.

### `match_methode` (valeurs après changement)

`texte_exact`, `distance`, `texte_exact_type`, `distance_type`, `texte_exact_surface`,
`distance_surface`, `texte_exact_type_surface`, `distance_type_surface`,
`consensus_etiquette_ges`.

(Change de convention : les libellés composés `*_type*` sont nouveaux ; `texte_exact_surface`
/ `distance_surface` conservés. Tests mis à jour.)

## 6. Colonnes de sortie ajoutées à `dvf_dpe_matched.parquet`

Contexte bâti, porté depuis le DPE apparié (`trouve`) ou depuis le consensus quand identique
sur tout le sous-ensemble, sinon `NULL` :

- `etiquette_ges` (VARCHAR)
- `type_batiment` (VARCHAR)
- `annee_construction` (BIGINT, nullable)
- `periode_construction` (VARCHAR)

## 7. Fichiers touchés

| fichier | changement |
|---|---|
| `pipeline/lib/clean_dpe.py` | `build_clean_record` : ajouter `annee_construction`, `periode_construction` (déjà : `type_batiment`, `etiquette_ges`) |
| `pipeline/03_clean_dpe.py` | `_CLEAN_COLUMNS` : 2 colonnes en plus |
| `pipeline/lib/match_dvf_dpe.py` | `dedup_dpe()` (B) ; filtre `type_batiment` (C) dans `_resolve` ; passe 4 consensus (A2) ; `MatchResult.status` 4 valeurs ; `MatchResult` porte `etiquette_dpe`, `etiquette_ges` (+ champs contexte) |
| `pipeline/04_join.py` | lecture des 2 colonnes DPE en plus ; appel dédup + comptage ; `_OUTPUT_COLUMNS` + 4 colonnes ; rapport 4 états + dont-consensus + dont-dédup |
| `pipeline/05_aggregate.py` | `impact_dpe_rows` : `match_status in ("trouve", "resolu_consensus")` ; compteur consensus dans le résumé |
| `tests/lib/test_match_dvf_dpe.py` | dédup, filtre type, consensus (oui/non), 4e état, sous-ensemble passe 4 |
| `tests/lib/test_clean_dpe.py` | présence des 2 nouveaux champs |
| `docs/adr/0003-*.md` | section « Récupération des ambigus (2026-08-27) » : B, C, A2, 4e état, mesures |
| `NOTES.md` | entrée datée : nouveaux taux mesurés, justification |
| `CONTEXT.md` | terme `Résolu par consensus` ; amender `Ambigu` ; amender `Taux d'appariement` |
| `README.md` | tableau des taux si présent |
| dashboard (`dashboard/app.py` / user story #33) | afficher 4 taux ; Impact DPE = `trouve` + `resolu_consensus`, avec mention « dont N résolus par consensus » |

≈ 12 fichiers → chemin architectural (spec + plan).

## 8. Plan de mesure (étape 1 de l'implémentation)

Script jetable (scratchpad) sur le jeu courant, **avant** de figer : combien d'ambigus
basculent grâce à B seul / +C / +A2, et résidu. Résultats reportés dans NOTES.md + ADR 0003.
Sert de test de non-régression sur données réelles (les taux attendus deviennent connus).

## 9. Tests (TDD)

Logique pure, `tests/lib/test_match_dvf_dpe.py`, avant implémentation :

- **dédup** : 3 DPE même adresse/surface/étiquette/GES/année → 1 gardé (le plus récent) ;
  année différente → 2 gardés ; surface à 0,05 près → même bucket (arrondi 0,1).
- **filtre type** : mutation Appartement + candidats {appartement, maison} → maison retirée ;
  {maison} seul + mutation Appartement → D1 (narrow-only : pool inchangé) ; `immeuble` gardé.
- **consensus** : within = {D/D, D/D} → `resolu_consensus` étiquette D GES D ; within =
  {D/D, D/E} → `ambigu` ; within = {D/D, C/D} → `ambigu` ; within vide + pool {D/D, D/D} →
  `resolu_consensus` ; étiquette nulle sur un candidat → `ambigu`.
- **sous-ensemble passe 4** : within ≥ 2 → consensus sur within (pas sur le pool) ;
  within = 1 → `trouve` (pas de passe 4).
- **non-régression** : cas trouvé/non_trouvé/ambigu existants inchangés ;
  `classify_match` ≡ `classify_match_indexed` (test différentiel déjà présent, à étendre).

Intégration : `04_join.py` sur échantillon fixe → 4 états présents, somme = total.

## 10. Décisions à confirmer en revue

- **D1** — filtre `type_batiment` : *narrow-only* (proposé) ou *rejet si pool vidé* ?
- **D2** — dédup : clé incluant `annee_construction` (proposé). L'inclure rend la dédup plus
  prudente (moins de fusions) mais laisse passer des doublons quand l'année est absente d'un
  côté. Alternative : clé sans année.
- **D3** — `agg_dpe` : inclure `resolu_consensus` (proposé, c'est le but) vs le garder visible
  mais hors agrégat comme les paires pré-2021-07.
- **D4** — nom du 4e état : `resolu_consensus` (proposé) / `resolu_batiment` / `etiquette_consensus`.
