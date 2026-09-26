---
title: Marché
---

```js
import {annees, communes, types, nombre, euros, serieGlobale, serieCommune, irisValeurs, contours, EFFECTIF_FAIBLE} from "./components/donnees.js";
import {courbePrix, legendeSeries, COULEURS_SERIES} from "./components/graphiques.js";
import {segment, liste, periode, pastilles} from "./components/ui.js";
```

# Prix au m² depuis ${annees[0]}

<p class="chapeau">Ventes officielles DVF (DGFiP). Le prix au m² est calculé pour chaque vente, prix total divisé par la surface habitable totale, puis résumé par année. La courbe noire réunit les ${communes.length} communes ; ajoutez des communes pour les comparer.</p>

```js
const choixStat = segment(["moyenne", "mediane"], {label: "Statistique", format: (d) => (d === "mediane" ? "Médiane" : "Moyenne")});
const choixType = segment([...types, "Les deux"], {label: "Type de bien"});
const choixPeriode = periode(annees);
const choixCommunes = pastilles(communes.map((c) => c.dvf_nom), {
  label: "Communes à comparer",
  couleurs: COULEURS_SERIES,
  max: COULEURS_SERIES.length,
  format: (v) => communes.find((c) => c.dvf_nom === v).nom
});
const stat = Generators.input(choixStat);
const typeBien = Generators.input(choixType);
const plage = Generators.input(choixPeriode);
const comparees = Generators.input(choixCommunes);
```

<div class="filtres">${choixStat}${choixType}${choixPeriode}</div>
<div class="filtres">${choixCommunes}</div>

```js
const [lo, hi] = plage;
const typesAffiches = typeBien === "Les deux" ? types : [typeBien];
const deux = typesAffiches.length > 1;
const suffixe = (t) => (deux ? ` · ${t === "Appartement" ? "appartements" : "maisons"}` : "");
const pts = (rows) => rows.map((d) => ({annee: d.annee, n: d.n, valeur: d[stat]}));
const series = typesAffiches.flatMap((t) => [
  {nom: `${communes.length} communes${suffixe(t)}`, couleur: "var(--encre)", reference: true, tirets: t === "Maison" && deux, points: pts(serieGlobale(t, lo, hi))},
  ...comparees.map(({valeur, couleur}) => ({
    nom: `${communes.find((c) => c.dvf_nom === valeur).nom}${suffixe(t)}`,
    couleur,
    tirets: t === "Maison" && deux,
    points: pts(serieCommune(valeur, t, lo, hi))
  }))
]).filter((s) => s.points.length);
const totalVentes = typesAffiches.reduce((s, t) => s + serieGlobale(t, lo, hi).reduce((a, d) => a + d.n, 0), 0);
```

<figure class="graphe">
  ${series.length > 1 ? legendeSeries(series) : ""}
  ${series.length ? resize((width) => courbePrix(series, {width, stat})) : html`<p class="vide">Aucune vente pour cette sélection.</p>`}
  <figcaption>${nombre(totalVentes)} ventes sur la période, toutes communes${deux ? " ; trait plein : appartements, tirets : maisons" : ""}. Survolez un point pour l'effectif ; sous ${EFFECTIF_FAIBLE} ventes, une valeur annuelle bouge beaucoup. ${annees.at(-1)} est une première publication DGFiP : les ventes enregistrées tardivement s'y ajouteront aux éditions suivantes, son effectif est donc légèrement sous-estimé.</figcaption>
</figure>

## Prix au m² par quartier

<p class="chapeau">Découpage IRIS de l'INSEE : environ 2 000 habitants par zone. Prix moyen au m² sur la période choisie plus haut, pour le type de bien sélectionné. Une commune à zone unique apparaît d'un seul bloc.</p>

```js
import {carteIris} from "./components/carte.js";
```

```js
const choixTypeCarte = segment(types, {label: "Type de bien"});
const choixZoom = liste([null, ...communes.map((c) => c.code_insee)], {
  label: "Centrer sur",
  format: (v) => (v == null ? `Les ${communes.length} communes` : communes.find((c) => c.code_insee === v).nom)
});
const typeCarte = Generators.input(choixTypeCarte);
const zoom = Generators.input(choixZoom);
const carte = carteIris(contours, invalidation);
```

<div class="filtres">${choixTypeCarte}${choixZoom}</div>

```js
carte.mettreAJour(irisValeurs(typeCarte, lo, hi), zoom);
```

<figure class="graphe">
  ${carte.element}
  ${carte.legende}
  <figcaption>Couleurs par classes d'effectifs égaux (quantiles) : chaque teinte regroupe le même nombre de quartiers, pour que les écarts restent lisibles hors du front de mer. Période : ${lo === hi ? lo : `${lo}–${hi}`}.</figcaption>
</figure>

<link rel="stylesheet" href="npm:maplibre-gl@4.7.1/dist/maplibre-gl.css">
