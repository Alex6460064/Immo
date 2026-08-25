# DVF × DPE Pays Basque

Projet croisant les ventes immobilières officielles (DVF, DGFiP) et les diagnostics de
performance énergétique (DPE, ADEME) sur un périmètre de communes du littoral Pays Basque et
du BAB élargi.

## Language

**Mutation**:
Une vente immobilière individuelle enregistrée dans DVF. Unité de base de l'analyse — une ligne
DVF brute correspond à une mutation (potentiellement plusieurs biens/lots).
_Avoid_: Transaction, vente (utiliser Mutation pour désigner l'enregistrement DVF précis).

**Vente appariée**:
Une mutation DVF pour laquelle un DPE correspondant a été trouvé par rapprochement d'adresse.
Sous-ensemble des mutations, structurellement limité aux ventes proches ou postérieures à
juillet 2021 (voir DPE post-réforme) — une mutation de 2016 n'a quasiment aucune chance d'être
appariée sauf second DPE réalisé après 2021 sur le même bien.
_Avoid_: Vente matchée, vente jointe.

**DPE post-réforme**:
Diagnostic de performance énergétique réalisé selon la méthode de calcul en vigueur depuis
juillet 2021 (jeu ADEME `dpe-v2-logements-existants`). Seule source DPE retenue par le projet —
l'ancienne méthode (avant juillet 2021) n'est pas comparable et est exclue.
_Avoid_: DPE, diagnostic (préciser "post-réforme" quand l'ambiguïté temporelle compte).

**Taux d'appariement**:
Proportion de mutations DVF pour lesquelles une Vente appariée a été trouvée. Donnée du projet
à afficher/logger systématiquement, jamais masquée — attendu structurellement bas sur les
mutations antérieures à 2021 du fait du périmètre DPE post-réforme.
_Avoid_: Taux de matching (garder Taux d'appariement en français dans les docs projet).

**Ambigu**:
Résultat d'appariement pour une mutation ayant plusieurs DPE candidats à distance géocodée
égale et surface non discriminante (voir [ADR 0003](docs/adr/0003-algorithme-appariement-dvf-dpe.md)).
Distinct de "non trouvé" — toujours compté et affiché séparément, jamais fusionné ni matché au
hasard.
_Avoid_: Non trouvé, échec (l'ambigu a un sens propre : le DPE existe, mais lequel des
candidats est incertain).

**IRIS**:
Zonage statistique officiel infra-communal (INSEE/IGN), utilisé comme unité d'agrégation pour
la carte choroplèthe (voir [ADR 0004](docs/adr/0004-carte-choroplethe-iris.md)). Une commune de
petite taille peut n'avoir qu'un seul IRIS couvrant tout son territoire.
_Avoid_: Quartier (IRIS est le terme technique précis utilisé dans le code/data ; "quartier"
reste acceptable dans les textes destinés au grand public, ex. README, post LinkedIn).

**Commune ciblée**:
Une des communes listées dans `config/communes.py` (littoral Pays Basque + Tarnos/Ondres pour
comparaison BAB — voir [ADR 0001](docs/adr/0001-communes-hors-dept-64.md)).
_Avoid_: Zone, périmètre.
