# Backtest Jev sur les mutations `trouve` (#36)

Echantillon : 400 cas juges (200 isoles, 200 multi-candidats), modele `jev-1.13.0`, questions `v1`.
Genere par `python pipeline/jev_backtest.py --limit-par-regime 200`, cache versionne dans
`data/jev/backtest_verdicts.parquet`.

## Methode

Chaque mutation `trouve` porte un `numero_dpe` connu avec certitude. On reconstruit le pool de
candidats que la desambiguisation Jev (#35) verrait si cette identite etait masquee
(`classify_with_backtest_pool`), on le soumet a Jev sans jamais lui donner la reponse, et on
compare le candidat qu'il prefere (`best_candidate`, calcule AVANT tout seuil) a la reponse
connue. Deux regimes, jamais melanges (cf. la note de calibration dans `jev_decision.decide`) :

- **isole** (pool a 1 candidat -- `texte_exact` / `distance` singuliers) : pas de second score,
  `marge == score`.
- **multi** (pool a >= 2 candidats -- departage `*_surface`) : structure identique a un vrai
  cas `ambigu` reel -- c'est la SEULE population que `04c_jev_disambiguate.py` soumet
  effectivement a Jev aujourd'hui (un pool `ambigu` a toujours >= 2 candidats,
  `pipeline/lib/match_dvf_dpe.py`).

## Conclusion et seuils retenus

**Le regime `multi` -- celui que la production utilise reellement -- ne peut pas etre resolu
de facon fiable par Jev a partir du seul texte d'adresse, quel que soit le seuil choisi.**

- Exactitude top-1 (avant tout seuil) : **30,0 %** sur 200 cas -- proche ou en-dessous du hasard
  pour la taille de pool observee (moyenne ~3 candidats/mutation), alors que ces candidats
  partagent la meme adresse normalisee ou sont a <= 15 m les uns des autres (c'est justement
  pourquoi l'algorithme n'a pas pu les departager par le texte + la distance).
- Le score et la confiance Jev ne discriminent PAS le bon candidat du mauvais : score moyen
  1,19 sur les cas corrects contre 1,17 sur les cas faux (n=43 vs 139), confiance moyenne 0,51
  contre 0,54. La courbe exactitude x confiance est plate (27 % a 100 % de confiance ne monte
  jamais durablement au-dessus de ~35 %, cf. tableau ci-dessous) -- la confiance annoncee par Jev
  n'est pas un signal utilisable ici.
- La marge reste quasi nulle sur tout l'echantillon (moyenne 0,02, 200/200 cas dans
  `[0, 0,25)`) : aucun seuil de marge entre 0,05 et 2,0 ne changerait la population retenue.
  `MARGE_MIN = 0.5` bloque donc DEJA, de fait, toute resolution automatique du regime multi --
  ce n'est pas un defaut a corriger, c'est la lecture correcte de cette courbe.

**Decision : `SCORE_MIN`, `MARGE_MIN`, `CONFIANCE_MIN` restent inchanges (1.5 / 0.5 / 0.5).**
Le backtest ne trouve aucune fenetre de seuils qui rendrait une resolution automatique du regime
`multi` a la fois utile (un volume non nul de cas resolus) et sure (une exactitude nettement
superieure a 30 %) -- les deux exigences sont incompatibles sur cette population. Baisser
`MARGE_MIN` ferait resoudre des cas avec un taux d'erreur residuel attendu proche de **70 %**
(1 - 30,0 %), ce qui n'est pas publiable. Les seuils actuels, qui bloquent la resolution
automatique (0/200 cas `multi` resolus sur cet echantillon, donc 0 % de couverture et 0 erreur
introduite), sont donc VALIDES par la mesure et non plus choisis a la main -- c'est le livrable
methodologique de ce ticket : la normalisation d'adresse et le texte brut d'un DPE ne portent
pas assez d'information pour departager des logements du meme immeuble sans la surface, que le
spec interdit explicitement de donner a Jev.

Le regime `isole` (100 % d'exactitude, 200/200, a toute tranche de confiance -- y compris
`[0, 0,25)`) n'a AUCUN consommateur en production aujourd'hui : un pool `ambigu` reel a toujours
>= 2 candidats (voir Methode). Il documente une piste pour #40 (repli Jev sur `non_trouve`, qui
pourrait produire des pools a 1 candidat) mais ne justifie pas de creer un seuil separe par
regime dans `decide` tant qu'aucun code de production ne consomme cette distinction -- hors
perimetre de #36.

## Regime isole (pool a 1 candidat)

- n = 200
- exactitude top-1 (avant tout seuil) : 100.0%
- au seuil courant : aucun cas resolu.

**Exactitude x tranche de confiance**
```
    tranche              n    exactitude top-1
    [0.00, 0.25)       6             100.0%
    [0.25, 0.50)      79             100.0%
    [0.50, 0.70)      76             100.0%
    [0.70, 0.85)      20             100.0%
    [0.85, 0.95)      11             100.0%
    [0.95, 1.00)       8             100.0%
```

## Regime multi (pool a >= 2 candidats)

- n = 200
- exactitude top-1 (avant tout seuil) : 30.0%
- au seuil courant : aucun cas resolu.

**Exactitude x tranche de confiance**
```
    tranche              n    exactitude top-1
    [0.00, 0.25)      11              27.3%
    [0.25, 0.50)      80              37.5%
    [0.50, 0.70)      61              31.1%
    [0.70, 0.85)      39              15.4%
    [0.85, 0.95)       8              25.0%
    [0.95, 1.00)       1               0.0%
```

**Exactitude x tranche de marge**
```
    tranche              n    exactitude top-1
    [0.00, 0.25)     200              30.0%
    [0.25, 0.50)       0               0.0%
    [0.50, 0.70)       0               0.0%
    [0.70, 0.85)       0               0.0%
    [0.85, 0.95)       0               0.0%
    [0.95, 1.00)       0               0.0%
```
