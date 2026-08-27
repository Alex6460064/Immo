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
