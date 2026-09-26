---
title: Méthode
---

```js
import {meta, communes, nombre, pourcent} from "./components/donnees.js";
const depot = "https://github.com/Alex6460064/Immo";
const adr = (n, slug) => `${depot}/blob/main/docs/adr/${n}-${slug}.md`;
const decision = (n, slug) => html`<a href=${adr(n, slug)}>décision</a>`;
```

# Méthode et limites

<p class="chapeau">Tout est reproductible depuis les données publiques : un pipeline Python et DuckDB, étape par étape, testé en intégration continue. Cette page résume les choix qui changent la lecture des chiffres.</p>

## Les sources

- **DVF**, fichier brut de la DGFiP : toutes les ventes immobilières, sans l'identité des parties. Les millésimes 2016-2020, sortis de la fenêtre glissante officielle, viennent du miroir communautaire cquest, chacun pris dans la dernière édition qui le contient : la première publication d'un millésime est incomplète (${decision("0005", "source-historique-dvf-2016-2020")}).
- **DPE** de l'ADEME, logements existants, **uniquement la méthode post-réforme** (depuis le ${meta.cutoff.split("-").reverse().join("/")}) : l'ancienne méthode ne donne pas des étiquettes comparables.
- **Contours IRIS** de l'INSEE et de l'IGN pour la carte (${decision("0004", "carte-choroplethe-iris")}).
- **Périmètre** : ${communes.length} communes du littoral et de l'agglomération Bayonne-Anglet-Biarritz, dont Tarnos et Ondres dans les Landes (${decision("0001", "communes-hors-dept-64")}).

Le fichier DVF brut n'a pas de coordonnées. Les adresses sont géocodées par l'API Adresse (BAN), pour les ventes comme pour les diagnostics, afin que les deux partagent la même précision (${decision("0002", "dvf-brut-plus-geocodage-ban")}).

## Le prix au m²

Il est calculé **par vente**, jamais par ligne du fichier : le prix total divisé par la somme des surfaces habitables. Le fichier DGFiP recopie le montant total sur chaque lot ; diviser par la surface d'un seul lot ferait monter une vente d'immeuble à 100 000 €/m² et fausserait tout un quartier. Seules les ventes d'un seul type de bien sont gardées, et les prix hors de 200 à 30 000 €/m² sont écartés, comptés, jamais supprimés en silence (${decision("0006", "repli-mutation-prix-m2")}).

## Rapprocher une vente et un diagnostic

<ol class="etapes">
  <li><strong>Même adresse</strong>Adresses normalisées des deux côtés, comparées à l'identique.</li>
  <li><strong>Même endroit</strong>Sinon, points géocodés à moins de 15 m l'un de l'autre.</li>
  <li><strong>Même surface</strong>S'il reste plusieurs diagnostics, on garde ceux à ± 2 m² et du même type de bâtiment.</li>
  <li><strong>Même étiquette</strong>Si les candidats restants ont tous la même lettre, la lettre est certaine même si le diagnostic exact ne l'est pas : c'est l'état « résolu par consensus ».</li>
</ol>

Chaque lot vendu reçoit l'un des quatre états. Aucun cas ambigu n'est tranché au hasard (${decision("0003", "algorithme-appariement-dvf-dpe")}).

<div class="tableau-conteneur" style="max-width:640px">
<table class="donnees">
  <thead><tr><th scope="col">État</th><th scope="col" class="num">Lots</th><th scope="col" class="num">Part</th></tr></thead>
  <tbody>${meta.appariement.statuses.map((s) => html`<tr><th scope="row">${s.label[0].toUpperCase() + s.label.slice(1)}</th><td class="num">${nombre(s.n)}</td><td class="num">${pourcent(s.pct, 1)}</td></tr>`)}</tbody>
</table>
</div>

## Ce que les chiffres ne disent pas

- **L'effet propre de l'étiquette.** Les logements F et G sont surtout anciens, en centre-ville et près de l'océan. Sans modèle qui neutralise l'emplacement, l'âge et la taille, l'écart entre étiquettes mêle tout cela.
- **Le décalage de dates.** Une vente de 2021 peut être rapprochée d'un DPE de 2024 : l'étiquette décrit le bien, pas forcément ce que l'acheteur avait sous les yeux. D'où la restriction aux ventes postérieures à la réforme.
- **Les ventes anciennes.** Avant juillet 2021, presque aucune vente ne trouve de diagnostic post-réforme : le taux de rapprochement est bas par construction.
- **Les immeubles.** Environ un lot sur trois reste ambigu : dans un immeuble, plusieurs appartements partagent l'adresse et souvent la surface.
- **Les valeurs extrêmes.** Le site affiche le prix moyen au m². La moyenne réagit davantage aux ventes exceptionnelles que la médiane, qui reste proposée en option sur la courbe de prix (page Marché) et dans l'infobulle des barres Impact DPE.

## Pour aller plus loin

- <a href="https://github.com/Alex6460064/Immo">Code source, tests et décisions d'architecture</a>
- <a href="https://github.com/Alex6460064/Immo/blob/main/reports/synthese-pays-basque.pdf">Synthèse PDF (Bayonne, Anglet, Biarritz)</a>
- <a href="https://github.com/Alex6460064/Immo/blob/main/NOTES.md">Journal des arbitrages méthodologiques</a>
