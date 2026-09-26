---
title: Communes
---

```js
import {annees, communes, tableauCommunes, appariementCommune, nombre, euros, evolution, pourcent, EFFECTIF_FAIBLE} from "./components/donnees.js";
import {miniEtats} from "./components/graphiques.js";
```

```js
const derniere = annees[annees.length - 1];
const base = tableauCommunes[0]?.annee_base ?? annees[0];
const lignes = communes.map((c) => {
  const par = (t) => tableauCommunes.find((d) => d.commune === c.dvf_nom && d.type_local === t);
  const app = appariementCommune(c.dvf_nom);
  const certain = app.etats.filter((s) => s.status === "trouve" || s.status === "resolu_consensus").reduce((s, d) => s + d.pct, 0);
  return {nom: c.nom, appart: par("Appartement"), maison: par("Maison"), app, certain};
});
```

# Les ${communes.length} communes en ${derniere}

<p class="chapeau">Prix moyen au m² de l'année ${derniere}, évolution depuis ${base} et part des lots vendus rattachés à une étiquette DPE certaine. Cliquez un en-tête pour trier.</p>

```js
const colonnes = [
  {cle: "nom", titre: "Commune", val: (d) => d.nom},
  {cle: "pa", titre: "Appart. €/m²", num: true, val: (d) => d.appart?.moyenne},
  {cle: "ea", titre: `Depuis ${base}`, num: true, val: (d) => d.appart?.evolution},
  {cle: "na", titre: "Ventes", num: true, val: (d) => d.appart?.n},
  {cle: "pm", titre: "Maison €/m²", num: true, val: (d) => d.maison?.moyenne},
  {cle: "em", titre: `Depuis ${base}`, num: true, val: (d) => d.maison?.evolution},
  {cle: "nm", titre: "Ventes", num: true, val: (d) => d.maison?.n},
  {cle: "ac", titre: "Étiquette certaine", num: true, val: (d) => d.certain}
];
const tri = Mutable({cle: "pa", sens: -1});
const trier = (cle) => (tri.value = {cle, sens: tri.value.cle === cle ? -tri.value.sens : cle === "nom" ? 1 : -1});
```

```js
const col = colonnes.find((c) => c.cle === tri.cle);
const tries = [...lignes].sort((a, b) => {
  const x = col.val(a), y = col.val(b);
  if (x == null) return 1;
  if (y == null) return -1;
  return (typeof x === "string" ? x.localeCompare(y, "fr") : x - y) * tri.sens;
});
const prix = (r) => (r?.moyenne == null ? html`<span class="faible-effectif">–</span>` : html`<span class=${r.n < EFFECTIF_FAIBLE ? "faible-effectif" : ""}>${nombre(r.moyenne)}</span>`);
const evo = (r) => {
  const v = r?.evolution;
  if (v == null) return html`<span class="faible-effectif">–</span>`;
  // Une des deux moyennes repose sur trop peu de ventes : évolution affichée mais grisée.
  const fragile = r.n < EFFECTIF_FAIBLE || r.n_base < EFFECTIF_FAIBLE;
  return html`<span class=${fragile ? "faible-effectif" : v > 0 ? "hausse" : v < 0 ? "baisse" : ""}>${evolution(v)}</span>`;
};
display(html`<div class="tableau-conteneur"><table class="donnees">
  <caption class="remarque" style="caption-side:bottom;text-align:left;padding-top:.6rem">Valeurs grisées : moins de ${EFFECTIF_FAIBLE} ventes dans l'année (ou l'année de base pour l'évolution), moyenne fragile. Évolution de la moyenne annuelle, sans correction de la composition des ventes.</caption>
  <thead><tr>${colonnes.map(
    (c) => html`<th scope="col" class=${c.num ? "num" : ""} aria-sort=${tri.cle === c.cle ? (tri.sens > 0 ? "ascending" : "descending") : null}><button type="button" onclick=${() => trier(c.cle)}>${c.titre}<span aria-hidden="true">${tri.cle === c.cle ? (tri.sens > 0 ? "↑" : "↓") : ""}</span></button></th>`
  )}</tr></thead>
  <tbody>${tries.map(
    (d) => html`<tr>
      <th scope="row" class="commune">${d.nom}</th>
      <td class="num">${prix(d.appart)}</td><td class="num">${evo(d.appart)}</td><td class="num">${nombre(d.appart?.n)}</td>
      <td class="num">${prix(d.maison)}</td><td class="num">${evo(d.maison)}</td><td class="num">${nombre(d.maison?.n)}</td>
      <td class="num"><span style="display:inline-flex;align-items:center;gap:.6rem">${miniEtats(d.app.etats)}${pourcent(d.certain)}</span></td>
    </tr>`
  )}</tbody>
</table></div>`);
```

<p class="remarque">La mini-barre montre les quatre états de rapprochement dans l'ordre : trouvé, résolu par consensus, non trouvé, ambigu (hachuré). Leur définition est dans la <a href="./methode">méthode</a>.</p>
