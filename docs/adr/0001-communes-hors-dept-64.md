# Inclure Tarnos et Ondres (dept. 40) malgré périmètre "Pays Basque"

Le projet cible administrativement le Pays Basque (dept. 64), mais l'utilisateur veut comparer
les prix du BAB (Bayonne, Anglet, Biarritz) aux communes limitrophes de l'autre côté de
l'Adour — Tarnos et Ondres, qui sont dans les Landes (dept. 40). Décision : télécharger DVF
pour dept. 40 en plus de dept. 64, filtrer uniquement ces deux communes côté 40 via
`config/communes.py`. Le téléchargement et le filtrage se font par code INSEE de commune, pas
par département entier.

**Alternative rejetée** : exclure Tarnos/Ondres pour garder un périmètre "Pays Basque" pur —
rejetée car la comparaison BAB / rive gauche de l'Adour est une valeur analytique explicitement
demandée, pas un accident de scope.
