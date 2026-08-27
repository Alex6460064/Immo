# Design — Récupération des ambigus DVF × DPE (dédup + filtre type + consensus étiquette)

Date : 2026-08-27
Statut : accepté (grilling 2026-08-27) — implémentation conditionnée au spike (§8)
Issue : [#23](https://github.com/Alex6460064/Immo/issues/23)
Contexte lié : [ADR 0003](../../adr/0003-algorithme-appariement-dvf-dpe.md), `NOTES.md` (T10),
`CONTEXT.md` (terme « Ambigu »), issue #11 (matcher 3 passes livré).

---

## 1. Problème

Jeu courant : 56 929 mutations → **trouvé 34,6 % / non trouvé 18,4 % / ambigu 46,9 %**.
Parmi les 19 721 « trouvé », 10 448 portent sur une mutation < 2021-07 (exclues de la vue
Impact DPE).

L'ambigu de la passe 3 est une ambiguïté **d'identité de l'enregistrement DPE**, pas
forcément une ambiguïté **de la réponse analytique**. `agg_dpe` (vue Impact DPE) ne consomme
que `etiquette_dpe` + `type_local` — jamais `numero_dpe`, ni conso, ni GES. Donc :

- si N candidats indistinguables portent **tous** la même étiquette, la mutation tombe dans
  le même bucket `agg_dpe` quel que soit « le bon » enregistrement → l'ambiguïté d'identité
  est sans effet sur la sortie ;
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
existantes ; modifier le seuil de distance (ADR 0003 / T9) ; construire le dashboard (→ #15).

## 3. Approche : spike d'abord, gate ensuite

Le design ci-dessous est **conditionné** à ce que le spike (§8) montre un gain réel. Les
briques ne sont figées qu'après le gate (§8) :

- **B (dédup)** — implémenté sauf si le spike estime > ~200 fusions de logements réellement
  distincts.
- **C (filtre type)** — gardé si le spike montre un départage ≥ ~1 % des mutations (≈ 570)
  **ou** ≥ ~2 pts d'ambigu.
- **A2 (passe 4 consensus)** — gardé si ≥ ~2 pts d'ambigu basculent vers `resolu_consensus`.
  Sinon le 4e état ne se justifie pas : on s'arrête à B (+C), l'ambigu résiduel reste tel
  quel et documenté.

## 4. Les trois briques

Trois briques, dans cet ordre d'exécution :

### B — Déduplication des DPE redondants

Fonction **pure** `dedup_dpe(candidats)` dans `pipeline/lib/match_dvf_dpe.py`, appelée par
`classify_match` (référence) **et** `build_dpe_index` (indexé) — les deux chemins doivent
voir la même liste dédupliquée (test différentiel).

Au sein d'une commune (`code_insee_ban`) et d'une **`adresse_normalisee` exacte identique**
(les DPE à adresse vide ne sont pas groupés — comptés à part), regrouper les DPE identiques
sur la signature analytique + bâti :

```
clé_dédup = (
    round(surface_habitable_logement, 1),
    etiquette_dpe,
    etiquette_ges,
    periode_construction,     # présent sur 100 % des DPE du jeu (annee_construction : 48 %)
    type_batiment,
)
```

Dans chaque groupe, garder **un seul** enregistrement : `date_etablissement_dpe` la plus
récente (départage déterministe : `numero_dpe` max ; date absente → trie en dernier, cas
théorique, tous les DPE étant post-réforme donc datés). Compter les lignes retirées, les
logger dans le rapport de `04_join.py`.

**Portée** : `adresse_normalisee` exacte seulement (option A du grilling). On ne déduplique
**pas** sur le voisinage géocodé de la passe 2 — l'ambigu résiduel de la passe 2 est rattrapé
par la passe 4 si les étiquettes concordent. Rouvrable dans un ticket suivant si le spike
montre que le gros du résidu vient de ce cas.

Risque assumé : deux logements réellement distincts d'un même immeuble, identiques sur toute
la signature, sont fusionnés en un. Leur signature analytique étant identique, `agg_dpe`
n'est pas affecté. Documenté dans ADR 0003 + NOTES.md. Le spike estime l'ampleur.

### C — Filtre `type_batiment` : départageur, pas validateur

Le filtre C **départage** un pool ambigu ; il **n'exclut jamais** un appariement.
Conséquence directe : il ne s'applique **que quand le pool a > 1 candidat**. Un candidat
unique de type contradictoire (typo `type_batiment`, maison de ville classée appart…) reste
`trouvé` — signal trop faible pour casser un appariement texte-exact.

Quand pool > 1, après sélection de voie (passe 1 texte exact ou passe 2 distance) et avant la
passe 3 surface, filtrer le pool :

| `type_local` (DVF) | candidats retirés |
|---|---|
| `Appartement` | `type_batiment == "maison"` |
| `Maison` | `type_batiment == "appartement"` |
| autre / absent | aucun filtre |

`type_batiment == "immeuble"` (DPE collectif) est **conservé** dans les deux cas.

**D1 — narrow-only** : si le filtre laisse 0 candidat, on l'ignore et on repart du pool non
filtré. C ne crée jamais un non-appariement à lui seul. Le spike compte séparément les cas
« pool vidé » ; s'ils sont significatifs on rediscutera le rejet.

Quand C a effectivement retiré des candidats, la colonne de sortie `filtre_type_applique`
passe à `true` pour cette mutation.

### A2 — Récupération par consensus d'étiquette

Nouvelle **passe 4**, après la passe 3 surface, quand celle-ci n'a pas isolé exactement 1
candidat. Sur le sous-ensemble de candidats retenu (voir §5), si **tous** partagent la même
`etiquette_dpe` non nulle :

→ mutation **`resolu_consensus`** : on porte `etiquette_dpe` (valeur du consensus),
`numero_dpe` reste `NULL` (l'identité reste inconnue). Sinon → `ambigu`.

**D5 — consensus sur l'étiquette seule.** `agg_dpe` ne consomme que `etiquette_dpe` : exiger
aussi un consensus GES rendrait la récupération plus rare sans gain sur l'objectif. `etiquette_ges`
et les autres colonnes de contexte (§6) sont portées **uniquement si elles sont unanimes** sur
le sous-ensemble, sinon `NULL` — même règle que pour un `trouve`.

Méthode : `consensus_etiquette`.

## 5. Ordre des passes (algorithme complet après changement)

```
dédup DPE (B, dans dedup_dpe(), vue par les deux chemins)
  │
  ▼  pour chaque mutation :
passe 1  texte exact  → pool = DPE à adresse_normalisee identique
passe 2  distance     → si pool passe 1 vide : pool = DPE géocodés ≤ seuil (ADR 0003)
  │
  ├─ pool vide            → non_trouve
  ├─ pool == 1            → trouve            (methode : texte_exact | distance)
  └─ pool > 1 :
        filtre C type_batiment (narrow-only, D1) → filtre_type_applique
          │
        passe 3  surface ±2 m² → within
          ├─ within == 1       → trouve       (methode : texte_exact_surface | distance_surface)
          └─ sinon :
                passe 4  consensus (A2) sur  within si len(within) ≥ 2, sinon pool
                  ├─ étiquette unanime non nulle → resolu_consensus  (methode : consensus_etiquette)
                  └─ sinon                       → ambigu
```

**Sous-ensemble de la passe 4** : `within` (candidats dans ±2 m²) s'il en reste au moins 2 ;
sinon (surface manquante côté mutation, ou 0 candidat dans la tolérance) le pool d'entrée de
la passe 3. Rationnel : quand la surface ne discrimine rien, la question honnête du consensus
porte sur l'ensemble du bâtiment. Le spike montrera que ce repli rapporte peu ; s'il rapporte
0, il est retiré à l'implémentation.

## 6. États de sortie — 3 → 4

`match_status` passe de `{trouve, non_trouve, ambigu}` à
`{trouve, resolu_consensus, non_trouve, ambigu}`.

| état | sens | `numero_dpe` | `etiquette_dpe` | `etiquette_ges` / contexte |
|---|---|---|---|---|
| `trouve` | 1 DPE identifié | renseigné | du DPE | du DPE |
| `resolu_consensus` | identité incertaine, **étiquette certaine** | `NULL` | du consensus | du consensus si unanime, sinon `NULL` |
| `ambigu` | plusieurs candidats, pas de consensus d'étiquette | `NULL` | `NULL` | `NULL` |
| `non_trouve` | aucun candidat | `NULL` | `NULL` | `NULL` |

`resolu_consensus` se lit comme *« ambigu sauvé »*, pas comme *« trouvé dégradé »* — dans les
rapports il est listé après `trouve`, avant `ambigu`.

### `match_methode` (valeurs après changement)

`texte_exact`, `distance`, `texte_exact_surface`, `distance_surface`, `consensus_etiquette`.

**Une seule valeur nouvelle** (`consensus_etiquette`) : les libellés existants sont
inchangés. L'information « le filtre type a resserré le pool » vit dans une colonne
booléenne séparée `filtre_type_applique`, orthogonale à `match_methode` (plus lisible dans
le parquet, `GROUP BY` direct, pas de churn sur les tests de libellés).

### Contrat `match_mutation`

`match_mutation()` (signature critères #11) garde sa signature mais son vocabulaire de sortie
passe à 4 valeurs. `TestEveryMutationEndsInExactlyOneState` est étendu. Changement de contrat
vs #11 assumé et noté dans #23.

## 7. Colonnes de sortie ajoutées à `dvf_dpe_matched.parquet`

Contexte bâti, porté depuis le DPE apparié (`trouve`) ou depuis le consensus quand identique
sur tout le sous-ensemble, sinon `NULL` :

- `filtre_type_applique` (BOOLEAN) — C a retiré ≥ 1 candidat pour cette mutation
- `etiquette_ges` (VARCHAR)
- `type_batiment` (VARCHAR)
- `periode_construction` (VARCHAR)

`annee_construction` : **reporté à #15** (aucun consommateur dans #23 — pas dans la clé de
dédup, pas dans la logique, pas de dashboard).

## 8. Plan de mesure (étape 1 de l'implémentation) + gate

Script jetable (scratchpad, **non versionné**) sur le jeu courant, **avant** de figer quoi
que ce soit. Sweep :

- clé dédup : `periode_construction` vs `annee_construction` vs sans → lignes retirées,
  estimation des fusions de logements réellement distincts
- consensus : `etiquette` seule vs `etiquette + GES` → ambigus basculés sous chaque règle
- filtre C : nb mutations départagées, nb « pool vidé » (D1), nb `trouve` à type contradictoire
- cumul : ambigus récupérés par B seul / +C / +A2, et résidu

Résultats reportés dans `NOTES.md` + commentaire de l'issue #23. Sert de test de
non-régression sur données réelles (les taux attendus deviennent connus).

**Gate — décision explicite après le spike :**

| brique | garde si | sinon |
|---|---|---|
| B | ≤ ~200 fusions de logements distincts estimées | rediscuter la clé |
| C | départage ≥ ~1 % des mutations (~570) **ou** ≥ ~2 pts d'ambigu | couper C |
| A2 | ≥ ~2 pts d'ambigu → `resolu_consensus` | pas de 4e état, s'arrêter à B(+C) |

## 9. Fichiers touchés (~11, hors dashboard)

| fichier | changement |
|---|---|
| `pipeline/lib/clean_dpe.py` | `build_clean_record` : ajouter `periode_construction` (`type_batiment`, `etiquette_ges` déjà présents) |
| `pipeline/03_clean_dpe.py` | `_CLEAN_COLUMNS` : + `periode_construction` |
| `pipeline/lib/match_dvf_dpe.py` | `dedup_dpe()` (B, pure) ; filtre `type_batiment` (C, pool > 1) dans `_resolve` ; passe 4 `consensus_etiquette` (A2) ; `MatchResult.status` 4 valeurs ; `MatchResult` porte `methode`, `filtre_type_applique`, `etiquette_dpe`, `etiquette_ges`, `type_batiment`, `periode_construction` ; dédup appliquée dans `classify_match` **et** `build_dpe_index` |
| `pipeline/04_join.py` | lire `etiquette_ges`, `type_batiment`, `periode_construction` du DPE ; `dedup_dpe` + comptage ; `_OUTPUT_COLUMNS` + `match_status`, `filtre_type_applique`, `etiquette_ges`, `type_batiment`, `periode_construction` ; rapport 4 états + dont-consensus + dont-dédup ; abandonne le dict `etiquette_by_numero` (contexte porté par `MatchResult`) |
| `pipeline/05_aggregate.py` | `impact_dpe_rows` : `match_status in ("trouve", "resolu_consensus")` ; compteur consensus dans le résumé (« dont N ») |
| `tests/lib/test_match_dvf_dpe.py` | dédup, filtre type (pool > 1, narrow-only, `immeuble` gardé), consensus étiquette (oui/non/nulle), 4e état, sous-ensemble passe 4, test différentiel étendu à des candidats redondants, `match_all()` : 4 états présents + somme == total |
| `tests/lib/test_clean_dpe.py` | présence de `periode_construction` |
| `docs/adr/0003-*.md` | section « Récupération des ambigus (2026-08-27) » : B, C, A2, 4e état, mesures du spike |
| `NOTES.md` | entrée datée : résultats du spike, nouveaux taux mesurés, justification du gate |
| `CONTEXT.md` | terme `Résolu par consensus` ; amender `Ambigu` ; amender `Taux d'appariement` |
| cette spec | statut, décisions figées |

Pas dans #23 : `dashboard/` (→ #15, note d'annonce ajoutée), `README.md` (aucun tableau de
taux), infra de test d'intégration (test au niveau `match_all()` suffit).

## 10. Tests (TDD)

Logique pure, `tests/lib/test_match_dvf_dpe.py`, avant implémentation :

- **dédup** : 3 DPE même adresse/surface/étiquette/GES/période → 1 gardé (le plus récent) ;
  période différente → 2 gardés ; surface à 0,05 près → même bucket (arrondi 0,1) ; adresse
  vide → non dédupliqué.
- **filtre type** : mutation Appartement + candidats {appartement, maison} (pool > 1) →
  maison retirée, `filtre_type_applique == true` ; {maison} seul + mutation Appartement →
  D1 narrow-only, pool inchangé ; `immeuble` toujours gardé ; pool == 1 de type contradictoire
  → `trouve` inchangé, `filtre_type_applique == false`.
- **consensus** : within = {D, D} → `resolu_consensus` étiquette D ; within = {D, E} →
  `ambigu` ; within vide + pool {D, D} → `resolu_consensus` ; étiquette nulle sur un candidat
  → `ambigu` ; GES divergent mais étiquette unanime → `resolu_consensus`, `etiquette_ges` NULL.
- **sous-ensemble passe 4** : within ≥ 2 → consensus sur within (pas sur le pool) ;
  within == 1 → `trouve` (pas de passe 4).
- **non-régression** : cas trouvé/non_trouvé/ambigu existants inchangés ;
  `classify_match` ≡ `classify_match_indexed` étendu à des candidats redondants (dédup vue
  identiquement des deux côtés).

`match_all()` (pure, dans `04_join.py`) : petite liste mutations + DPE en dur → 4 états
présents, `sum(status_counts) == len(mutations)`, dédup + consensus se combinent. Pas de
parquet, pas de sous-process.

## 11. Décisions figées (grilling 2026-08-27)

- **D1** — filtre `type_batiment` : *narrow-only* (le spike compte les « pool vidé »).
- **D2** — clé de dédup avec `periode_construction` (100 % de couverture), pas
  `annee_construction` (48 %) ; grouping sur `adresse_normalisee` exacte ; DPE ↔ DPE.
- **D3** — `agg_dpe` inclut `resolu_consensus` (c'est le but), avec « dont N » obligatoire
  dans le rapport `05_aggregate.py` et, plus tard, sur la vue dashboard (#15).
- **D4** — nom du 4e état : `resolu_consensus`.
- **D5** — consensus sur `etiquette_dpe` **seule** ; méthode `consensus_etiquette` ; GES et
  contexte portés seulement si unanimes.
- Dédup dans la couche matching (`match_dvf_dpe.py` / `04_join.py`), pas dans
  `03_clean_dpe.py` : `dpe_clean.parquet` garde tous les diagnostics.
- `match_methode` reste simple + colonne `filtre_type_applique` (BOOLEAN).
- C = départageur pool > 1 uniquement, jamais d'exclusion.
- Passe 4 : repli sur le pool si `within` < 2.
- Nouvelle issue #23 ; dashboard reste #15 ; `README.md` non touché ;
  `annee_construction` reporté à #15.
- Pas de nouvelle infra d'intégration ; test au niveau `match_all()`.
- `match_mutation` : vocabulaire → 4 états ; changement de contrat assumé vs #11.
