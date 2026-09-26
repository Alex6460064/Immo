---
title: Impact DPE
---

```js
import {meta, annees, communes, types, groupes, nombre, impactAgregat, impactComptages, appariementCommune, echelle, anneeReforme} from "./components/donnees.js";
import {barresImpact, etatsAppariement, echelleDPE, avertissement} from "./components/graphiques.js";
import {segment, liste, periode} from "./components/ui.js";
```

# Le prix au m² selon l'étiquette énergie

<p class="chapeau">Pour une commune à la fois : comparer une passoire de Biarritz à un logement économe d'Hasparren mesurerait l'écart entre les deux villes, pas l'effet de l'étiquette.</p>

```js
const choixCommune = liste(communes.map((c) => c.dvf_nom), {
  label: "Commune",
  value: communes.find((c) => c.nom === "Anglet")?.dvf_nom,
  format: (v) => communes.find((c) => c.dvf_nom === v).nom
});
const choixType = segment(["Tous", ...types], {label: "Type de bien"});
const choixGroupe = liste([null, ...groupes], {label: "Étiquettes", format: (g) => (g == null ? "A à G" : g)});
const choixPeriode = periode(annees, {value: [anneeReforme, annees[annees.length - 1]]});
const commune = Generators.input(choixCommune);
const typeBien = Generators.input(choixType);
const groupe = Generators.input(choixGroupe);
const plage = Generators.input(choixPeriode);
```

<div class="filtres">${choixCommune}${choixType}${choixGroupe}${choixPeriode}</div>

```js
const [lo, hi] = plage;
const nom = communes.find((c) => c.dvf_nom === commune).nom;
const typeFiltre = typeBien === "Tous" ? null : typeBien;
const typesAffiches = typeFiltre ? [typeFiltre] : types;
const lignes = impactAgregat(commune, lo, hi).filter(
  (d) => typesAffiches.includes(d.type_local) && (groupe == null || d.groupe === groupe)
);
const compo = impactComptages(commune, typeFiltre, groupe, lo, hi);
```

```js
display(avertissement(html`<p>${meta.note_decalage}</p>`));
```

<h2 style="margin-top:1.5rem">${nom} : prix moyen au m² par groupe d'étiquettes</h2>

<figure class="graphe">
  ${lignes.length ? resize((width) => barresImpact(lignes, {width, types: typesAffiches})) : html`<p class="vide">Aucune vente rapprochée d'un DPE après la réforme pour cette sélection. Élargissez la période ou choisissez « Tous » les types.</p>`}
  <figcaption><strong>${nombre(compo.retenues)} ventes retenues</strong>, dont ${nombre(compo.resolu_consensus)} résolues par consensus d'étiquette.${compo.pre_reforme_exclus ? ` ${nombre(compo.pre_reforme_exclus)} ventes à étiquette certaine mais antérieures à juillet ${anneeReforme} sont exclues (voir l'avertissement).` : ""} Étiquettes regroupées en A-C, D, E et F-G : l'échantillon est trop petit pour chaque lettre séparée. Une barre pâle compte moins de 30 ventes.</figcaption>
</figure>

## Le détail lettre par lettre

<p class="chapeau">Même tranche de ventes, sans regroupement, toutes années post-réforme confondues. Plus fin, donc plus bruité.</p>

```js
const choixTypeEchelle = segment(types, {label: "Type de bien"});
const typeEchelle = Generators.input(choixTypeEchelle);
```

<div class="echelle" style="max-width:640px">
  <div class="filtres">${choixTypeEchelle}</div>
  ${echelleDPE(echelle(commune, typeEchelle), {})}
  <p class="echelle-pied">Un point évidé signale moins de 30 ventes : moyenne fragile.</p>
</div>

## Rapprochement dans cette commune

```js
const app = appariementCommune(commune);
display(etatsAppariement(app.etats, {total: app.total}));
```

<p class="remarque">Tous les lots vendus à ${nom} depuis ${annees[0]}. Seuls les états « trouvé » et « résolu par consensus » portent une étiquette certaine et alimentent le graphique ci-dessus.</p>
