// Graphiques du site : Observable Plot pour les courbes et barres, HTML/CSS pour
// l'étiquette énergie et la barre des états d'appariement (formes où la
// typographie compte plus que l'axe).
import * as Plot from "npm:@observablehq/plot";
import {html} from "npm:htl";
import {EFFECTIF_FAIBLE, euros, nombre, pourcent} from "./donnees.js";

export const COULEURS_SERIES = [1, 2, 3, 4, 5].map((i) => `var(--serie-${i})`);
export const COULEUR_DPE = Object.fromEntries("ABCDEFG".split("").map((l) => [l, `var(--dpe-${l})`]));
// Regroupements : couleur de l'étiquette centrale du groupe.
export const COULEUR_GROUPE = {"A-C": "var(--dpe-B)", D: "var(--dpe-D)", E: "var(--dpe-E)", "F-G": "var(--dpe-F)"};
const ETIQUETTES_CLAIRES = new Set(["C", "D", "E"]);
const COULEUR_ETAT = {
  trouve: "var(--etat-trouve)",
  resolu_consensus: "var(--etat-consensus)",
  non_trouve: "var(--etat-non-trouve)",
  ambigu: "var(--etat-ambigu)"
};
const DETAIL_ETAT = {
  trouve: "un seul diagnostic correspond",
  resolu_consensus: "plusieurs candidats, même étiquette",
  non_trouve: "aucun diagnostic à cette adresse",
  ambigu: "plusieurs candidats, étiquettes différentes"
};

const formatAxeEuros = (d) => `${nombre(d)} €`;

/**
 * Courbes de prix/m² par année. `series` : [{nom, couleur, points, reference, tirets}]
 * où points = [{annee, n, valeur}].
 */
export function courbePrix(series, {width, stat}) {
  const lignes = series.flatMap((s) => s.points.map((p) => ({...p, serie: s.nom, x: +p.annee})));
  const parSerie = new Map(series.map((s) => [s.nom, s]));
  const marques = series.map((s) =>
    Plot.line(lignes.filter((d) => d.serie === s.nom), {
      x: "x",
      y: "valeur",
      stroke: s.couleur,
      strokeWidth: s.reference ? 3 : 2,
      strokeDasharray: s.tirets ? "5,4" : null,
      curve: "monotone-x"
    })
  );
  return Plot.plot({
    width,
    height: Math.max(280, Math.min(400, width * 0.42)),
    marginLeft: 64,
    marginRight: 16,
    x: {label: null, tickFormat: (d) => String(d), ticks: [...new Set(lignes.map((d) => d.x))], inset: 12},
    y: {label: `Prix au m², ${stat === "mediane" ? "médiane" : "moyenne"}`, grid: true, tickFormat: formatAxeEuros, nice: true},
    style: {color: "var(--encre-2)"},
    marks: [
      Plot.gridY({stroke: "var(--grille)", strokeOpacity: 1}),
      ...marques,
      Plot.dot(lignes, {
        x: "x",
        y: "valeur",
        r: (d) => (parSerie.get(d.serie).reference ? 3.5 : 3),
        fill: (d) => parSerie.get(d.serie).couleur,
        stroke: "var(--papier)",
        strokeWidth: 1.5
      }),
      Plot.ruleX(lignes, Plot.pointerX({x: "x", stroke: "var(--encre-3)", strokeDasharray: "2,3"})),
      Plot.tip(
        lignes,
        Plot.pointer({
          x: "x",
          y: "valeur",
          title: (d) => `${d.serie}\n${d.annee} · ${euros(d.valeur)}\n${nombre(d.n)} ventes${d.n < EFFECTIF_FAIBLE ? " (effectif faible)" : ""}`
        })
      )
    ]
  });
}

/** Légende HTML des courbes (toujours présente dès 2 séries). */
export function legendeSeries(series) {
  return html`<div class="legende-series">${series.map(
    (s) => html`<span><svg width="26" height="10" aria-hidden="true"><line x1="1" x2="25" y1="5" y2="5" stroke=${s.couleur} stroke-width=${s.reference ? 3 : 2} stroke-dasharray=${s.tirets ? "5,4" : null}/></svg>${s.nom}</span>`
  )}</div>`;
}

/** Barres prix/m² médian par regroupement d'étiquette (et par type si deux types). */
export function barresImpact(lignes, {width, types}) {
  const deuxTypes = types.length > 1;
  const donnees = lignes.map((d) => ({...d, faible: d.n < EFFECTIF_FAIBLE}));
  return Plot.plot({
    width,
    height: 400,
    marginLeft: 64,
    marginBottom: 36,
    marginTop: deuxTypes ? 40 : 20,
    fx: deuxTypes
      ? {label: null, padding: 0.18, axis: "top", tickSize: 0, tickPadding: 14, tickFormat: (g) => (g.includes("-") ? `Étiquettes ${g}` : `Étiquette ${g}`)}
      : undefined,
    x: deuxTypes
      ? {domain: types, label: null, axis: "bottom", tickSize: 0, padding: 0.12, tickFormat: (t) => (t === "Appartement" ? "Appart." : t)}
      : {label: "Regroupement d'étiquette DPE", padding: 0.3, tickSize: 0},
    y: {label: "Prix au m², médiane", grid: true, tickFormat: formatAxeEuros, nice: true},
    style: {color: "var(--encre-2)"},
    marks: [
      Plot.gridY({stroke: "var(--grille)", strokeOpacity: 1}),
      Plot.barY(donnees, {
        fx: deuxTypes ? "groupe" : undefined,
        x: deuxTypes ? "type_local" : "groupe",
        y: "mediane",
        fill: (d) => COULEUR_GROUPE[d.groupe],
        fillOpacity: (d) => (d.faible ? 0.45 : 1),
        rx: 4,
        insetLeft: 1,
        insetRight: 1
      }),
      Plot.ruleY([0], {stroke: "var(--encre-3)"}),
      Plot.text(donnees, {
        fx: deuxTypes ? "groupe" : undefined,
        x: deuxTypes ? "type_local" : "groupe",
        y: "mediane",
        text: (d) => nombre(d.mediane),
        dy: -9,
        fill: "var(--encre)",
        fontWeight: 700
      }),
      Plot.tip(
        donnees,
        Plot.pointerX({
          fx: deuxTypes ? "groupe" : undefined,
          x: deuxTypes ? "type_local" : "groupe",
          y: "mediane",
          title: (d) =>
            `${d.groupe} · ${d.type_local}\nMédiane ${euros(d.mediane)}\nMoyenne ${euros(d.moyenne)}\n${nombre(d.n)} ventes${d.faible ? " (effectif faible)" : ""}`
        })
      )
    ]
  });
}

/** Étiquette énergie : une flèche par étiquette, prix médian sur une échelle commune. */
export function echelleDPE(lignes, {reference}) {
  const par = new Map(lignes.map((d) => [d.etiquette_dpe, d]));
  const valeurs = lignes.map((d) => d.mediane);
  if (!valeurs.length) return html`<p class="vide">Aucune vente appariée pour cette sélection.</p>`;
  const pas = 500;
  const min = Math.floor((Math.min(...valeurs, reference ?? Infinity) * 0.97) / pas) * pas;
  const max = Math.ceil((Math.max(...valeurs, reference ?? -Infinity) * 1.03) / pas) * pas;
  const pos = (v) => `${(100 * (v - min)) / (max - min)}%`;
  return html`<div class="echelle-lignes" role="list">${"ABCDEFG".split("").map((l, i) => {
    const d = par.get(l);
    const faible = d && d.n < EFFECTIF_FAIBLE;
    const label = d ? `Étiquette ${l} : ${euros(d.mediane)}, ${nombre(d.n)} ventes` : `Étiquette ${l} : aucune vente`;
    return html.fragment`<div class=${`fleche${ETIQUETTES_CLAIRES.has(l) ? " claire" : ""}`} style=${{background: COULEUR_DPE[l], width: `${52 + i * 8}%`}} role="listitem" aria-label=${label}>${l}</div>
      <div class="echelle-piste" aria-hidden="true">${reference != null ? html`<span class="echelle-ref" style=${{left: pos(reference)}}></span>` : null}${
        d ? html`<span class=${`echelle-point${faible ? " faible" : ""}`} style=${{left: pos(d.mediane)}}></span>` : null
      }</div>
      <div class="echelle-valeur" aria-hidden="true">${d ? euros(d.mediane) : "–"}<small>${d ? `${nombre(d.n)} ventes` : "aucune vente"}</small></div>`;
  })}<div></div><div class="echelle-axe" aria-hidden="true"><span>${nombre(min)} €</span><span>${nombre(max)} €</span></div><div></div></div>`;
}

/** Barre empilée des 4 états + liste chiffrée (les 4 taux restent séparés). */
export function etatsAppariement(statuses, {total} = {}) {
  return html`<div class="etats">
    <div class="etats-barre" role="img" aria-label=${statuses.map((s) => `${s.label} ${pourcent(s.pct, 1)}`).join(", ")}>${statuses.map(
      (s) =>
        html`<span class=${s.status === "ambigu" ? "motif-ambigu" : ""} style=${`width:${s.pct}%;background-color:${COULEUR_ETAT[s.status]}`} title=${`${s.label} : ${pourcent(s.pct, 1)}`}></span>`
    )}</div>
    <ul class="etats-liste">${statuses.map(
      (s) => html`<li><span class=${`puce${s.status === "ambigu" ? " motif-ambigu" : ""}`} style=${`background-color:${COULEUR_ETAT[s.status]}`}></span><div>
        <strong>${pourcent(s.pct, 1)}</strong>
        <span class="etat-nom">${s.label[0].toUpperCase() + s.label.slice(1)}</span>
        <span class="etat-detail">${nombre(s.n)} lots · ${DETAIL_ETAT[s.status]}</span>
      </div></li>`
    )}</ul>
    ${total != null ? html`<p class="remarque">Sur ${nombre(total)} lots DVF : une vente compte une ligne par local vendu (logement, commerce, dépendance).</p>` : null}
  </div>`;
}

/** Mini-barre des 4 états (tableau des communes). */
export function miniEtats(etats) {
  return html`<span class="mini-barre" role="img" aria-label=${etats.map((s) => `${s.label} ${pourcent(s.pct)}`).join(", ")}>${etats.map(
    (s) => html`<span class=${s.status === "ambigu" ? "motif-ambigu" : ""} style=${`width:${s.pct}%;background-color:${COULEUR_ETAT[s.status]}`}></span>`
  )}</span>`;
}

/** Encadré d'avertissement méthodologique. */
export function avertissement(contenu) {
  return html`<div class="avertissement" role="note"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/><path d="M12 9v4M12 17h.01"/></svg><div>${contenu}</div></div>`;
}
