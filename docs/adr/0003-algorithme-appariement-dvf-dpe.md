# Algorithme d'appariement DVF↔DPE : texte exact → distance géocodée → départage surface

Pas de clé commune fiable entre DVF et DPE. Décision : algorithme en 3 passes, chaque mutation
DVF aboutit à exactement un de ces 3 états (jamais un choix forcé au hasard) :

1. **Texte exact** — adresse normalisée (numéro + voie + code postal) identique des deux
   côtés → apparié.
2. **Repli distance géocodée** — si texte non exact, DVF et DPE sont tous deux géocodés via
   l'API BAN (voir [ADR 0002](0002-dvf-brut-plus-geocodage-ban.md)) ; si un unique DPE candidat
   est à ≤ seuil de distance (calibré sur échantillon réel, ~15-20m) → apparié.
3. **Départage par surface** — si plusieurs DPE candidats dans le seuil de distance (cas
   fréquent : immeuble collectif, plusieurs logements géocodés au même point bâtiment), on
   compare la surface DVF à la surface de chaque DPE candidat ; si un seul candidat a une
   surface à ± 2m² → apparié sur ce candidat. Sinon → **ambigu**, non apparié.

Résultat final par mutation : **trouvé** / **non trouvé** / **ambigu**. Les trois taux sont
affichés dans le rapport de matching (jamais uniquement "trouvé vs non trouvé" — l'ambigu doit
rester visible et distinct, principe CLAUDE.md d'exactitude des données).

**Alternative rejetée** : fuzzy matching texte (Levenshtein/rapidfuzz) — seuil de similarité %
moins interprétable/défendable qu'un seuil de distance physique ou un écart de surface en m².

**Pourquoi documenté** : c'est le cœur méthodologique du projet portfolio — démontre la
capacité à exploiter toute l'étendue des données disponibles (adresse, géocodage, surface) pour
résoudre un problème d'appariement ambigu sans sacrifier la fiabilité.

---

## Calibration du seuil de distance (passe 2) — 2026-08-27

Mesuré par `pipeline/calibrate_distance.py` sur **5 733 paires** d'adresses normalisées
identiques entre DVF et DPE (celles qui passent déjà la passe 1), chacune géocodée des deux
côtés : distance entre le point BAN côté DVF et le point BAN côté DPE.

| distance | paires | cumul |
|---|---|---|
| exactement 0 m | 5 495 | 95,85 % |
| 0–100 m | 3 | 95,90 % |
| > 200 m (échec géocodage : repli centroïde commune) | 235 | 100 % |

La distribution est **dégénérée** : quand l'API BAN aboutit des deux côtés, elle renvoie le
même point (mêmes coordonnées) pour une adresse normalisée identique — pas de bande de
« jitter » intermédiaire. Les 4,1 % restants sont des échecs de géocodage à l'échelle du
kilomètre, hors de tout seuil raisonnable (→ classés *non trouvé* par la passe 2, ce qui est
correct).

**Seuil retenu : `DISTANCE_THRESHOLD_M = 15`** (`pipeline/lib/match_distance.py`). Il ne
couvre pas un écart-type mesuré (il n'y en a pas) mais fixe la marge pour un texte proche mais
non identique — suffixe *BIS/TER*, numéro manquant — que BAN interpole vers un point voisin :
≈ un pas d'interpolation de numéro de voirie en tissu urbain dense (BAB), sans atteindre la
parcelle mitoyenne. Toute la plage 10–30 m donne le même comportement réel sur l'échantillon
(95,87 % des paires couvertes). L'estimation « ~15-20 m » du texte ci-dessus est confirmée ;
15 m est retenu comme borne basse défendable.

---

## Précisions d'implémentation (T10, `pipeline/04_join.py`, 2026-08-27)

**Passe 1 — clé texte + scoping commune.** L'algorithme ci-dessus décrit la passe 1 comme
« numéro + voie + code postal identiques ». `adresse_normalisee` (produite par
`pipeline/lib/normalize_address.py`) est en pratique une clé *rue seule* (sans CP ni commune —
choix documenté dans `clean_dvf.py` / `clean_dpe.py` pour ne pas polluer la clé de comparaison
textuelle). Le rôle du code postal est tenu à la place par un **scoping commune** : pour
chaque mutation, seuls les DPE de la même commune (`code_insee` == `code_insee_ban`) sont
candidats. Sur le périmètre du projet c'est équivalent-ou-plus-strict que le CP (communes
quasi toutes mono-CP) et ça évite un faux appariement inter-communes sur une rue homonyme.

**Passes 1 & 2 — plusieurs candidats → départage surface.** Quand la passe 1 trouve *plusieurs*
DPE à adresse identique (immeuble collectif), on enchaîne directement sur le départage par
surface ± 2 m² sur ce sous-ensemble (méthode `texte_exact_surface`), au lieu de déclarer
« ambigu » d'emblée — même logique que pour plusieurs candidats dans le seuil de distance
(`distance_surface`).

**Résultat mesuré (jeu courant, 56 929 mutations)** : trouvé 34,6 % / non trouvé 18,4 % /
**ambigu 46,9 %**. L'ambigu élevé est réel, pas un bug : en habitat collectif dense (BAB),
plusieurs logements d'un immeuble partagent adresse + surface à ± 2 m² près, et l'algorithme
refuse de trancher au hasard (principe de cet ADR). Parmi les 19 721 « trouvé », **10 448
portent sur une mutation antérieure à juillet 2021** — appariées à un DPE forcément
post-réforme donc établi après la vente ; conservées dans `dvf_dpe_matched.parquet` mais
exclues de l'agrégat « Impact DPE » (voir `NOTES.md`).

---

## Récupération des ambigus (2026-08-27, [#23](https://github.com/Alex6460064/Immo/issues/23))

L'ambigu de la passe 3 est une ambiguïté **d'identité de l'enregistrement DPE**, pas
forcément une ambiguïté **de la réponse analytique** : `agg_dpe` (vue Impact DPE) ne consomme
que `etiquette_dpe` + `type_local`. Trois causes traitables **sans jamais trancher au
hasard** — spike de mesure d'abord, puis gate (détail chiffré dans `NOTES.md`).

**B — Déduplication des DPE redondants** (`dedup_dpe`, appelée par `classify_match` *et*
`build_dpe_index` → les deux chemins voient la même liste). Au sein d'une commune et d'une
`adresse_normalisee` exacte identique, les DPE partageant la signature
`(surface arrondie 0,1 ; etiquette_dpe ; etiquette_ges ; periode_construction ; type_batiment)`
sont le même logement diagnostiqué plusieurs fois (renouvellement, correction, DPE de vente).
On garde le plus récent (`date_etablissement_dpe` max, puis `numero_dpe` max). Adresse vide →
jamais groupée. La clé fige `etiquette_dpe` + `etiquette_ges` : **fusionner ne change jamais
une réponse analytique**. Risque assumé : deux logements réellement distincts d'un même
immeuble, identiques sur toute la signature (immeuble neuf, plans identiques), fusionnés en un
— sans effet sur `agg_dpe`, seul un `numero_dpe` devient l'un de deux enregistrements
indistinguables.

**C — Filtre `type_batiment`** : sur un pool > 1 candidats, retire les DPE dont le
`type_batiment` contredit le `type_local` DVF (`Appartement` ↔ `maison`). `immeuble` (DPE
collectif) toujours conservé. **Départageur, jamais validateur** : ne s'applique pas à un
candidat unique, et si le filtre viderait le pool on garde le pool d'origine (*narrow-only*,
D1) — C ne crée jamais un non-appariement. Colonne de sortie `filtre_type_applique` quand le
filtre a effectivement retiré ≥ 1 candidat.

**A2 — Passe 4, consensus d'étiquette** : après la passe 3, si celle-ci n'a pas isolé
exactement 1 candidat, on regarde le sous-ensemble `within` (candidats à ± 2 m²) s'il en
reste ≥ 2, sinon le pool d'entrée. Si **tous** portent la même `etiquette_dpe` non nulle →
**`resolu_consensus`** : `numero_dpe` reste `NULL` (identité inconnue), l'étiquette est
portée (certaine). `etiquette_ges` / `type_batiment` / `periode_construction` portés
seulement s'ils sont eux aussi unanimes. Consensus sur l'**étiquette seule** (D5) : `agg_dpe`
ne lit pas le GES, exiger un consensus GES rendrait la récupération plus rare sans gain.

**4e état de sortie.** `match_status` passe de `{trouve, non_trouve, ambigu}` à
`{trouve, resolu_consensus, non_trouve, ambigu}`. `resolu_consensus` se lit « ambigu sauvé »,
listé après `trouve` et avant `ambigu` ; il entre dans `agg_dpe` avec la mention « dont N
résolus par consensus ». Changement de contrat assumé vis-à-vis des critères de l'issue #11.

**Résultat mesuré (jeu courant, B + C + A2 étiquette seule)** :
**trouvé 37,8 % / resolu_consensus 12,1 % / non trouvé 18,4 % / ambigu 31,7 %**
(baseline : 34,6 / — / 18,4 / 46,9). Dans le périmètre Impact DPE (mutation ≥ 2021-07) :
+28 % de matière analytique. Détail du spike et du gate dans `NOTES.md`.
