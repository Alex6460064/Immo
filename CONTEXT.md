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
Proportion de mutations DVF pour lesquelles une étiquette DPE certaine a été établie — Vente
appariée (`trouvé`) **ou** Résolu par consensus. Donnée du projet à afficher/logger
systématiquement, avec les 4 états séparés (`trouvé` / `resolu_consensus` / `non trouvé` /
`ambigu`), jamais masquée — attendu structurellement bas sur les mutations antérieures à 2021
du fait du périmètre DPE post-réforme.
_Avoid_: Taux de matching (garder Taux d'appariement en français dans les docs projet).

**Ambigu**:
Résultat d'appariement pour une mutation ayant plusieurs DPE candidats que ni la surface ni le
type de bien ne départagent, **et** dont les étiquettes DPE divergent (sinon → Résolu par
consensus). Voir [ADR 0003](docs/adr/0003-algorithme-appariement-dvf-dpe.md), section
« Récupération des ambigus ». Distinct de "non trouvé" — toujours compté et affiché
séparément, jamais fusionné ni matché au hasard.
_Avoid_: Non trouvé, échec (l'ambigu a un sens propre : le DPE existe, mais lequel des
candidats est incertain).

**Résolu par consensus**:
Résultat d'appariement (`resolu_consensus`) pour une mutation à plusieurs DPE candidats
indistinguables qui portent **tous la même étiquette DPE** : l'identité du DPE reste inconnue
(`numero_dpe` NULL) mais l'étiquette — seule dimension consommée par la vue Impact DPE — est
certaine. Se lit « ambigu sauvé », pas « trouvé dégradé » : listé après `trouvé`, avant
`ambigu`. Entre dans l'agrégat Impact DPE avec la mention « dont N résolus par consensus »
([ADR 0003](docs/adr/0003-algorithme-appariement-dvf-dpe.md), [#23](https://github.com/Alex6460064/Immo/issues/23)).
_Avoid_: Trouvé (l'identité du DPE n'est pas connue), Ambigu (la réponse analytique, elle, est certaine).

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
