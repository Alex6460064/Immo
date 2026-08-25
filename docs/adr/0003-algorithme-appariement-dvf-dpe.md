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
