// Accès aux données publiées par `pipeline/08_export_site.py`. Aucun calcul
// statistique ici : les médianes, moyennes et comptages viennent de Python
// (dashboard/site_export.py, testé). Ce module ne fait que sélectionner des lignes
// et additionner des comptages annuels (additifs par construction).
import {FileAttachment} from "observablehq:stdlib";

export const meta = await FileAttachment("../data/meta.json").json();
const marche = await FileAttachment("../data/marche.json").json();
const impact = await FileAttachment("../data/impact.json").json();
const communesData = await FileAttachment("../data/communes.json").json();
export const iris = await FileAttachment("../data/iris.json").json();
export const contours = await FileAttachment("../data/iris.geojson").json();

export const annees = meta.annees;
export const types = meta.types;
export const groupes = meta.groupes;
export const anneeReforme = meta.cutoff.slice(0, 4);

/** Communes triées par nom d'affichage : {nom, code_insee, dvf_nom}. */
export const communes = [...meta.communes].sort((a, b) => a.nom.localeCompare(b.nom, "fr"));
const parDvf = new Map(communes.map((c) => [c.dvf_nom, c]));
export const nomCommune = (dvf) => parDvf.get(dvf)?.nom ?? dvf;

// ---------- Formats ----------
const nf = new Intl.NumberFormat("fr-FR", {maximumFractionDigits: 0});
export const nombre = (v) => (v == null ? "–" : nf.format(v));
export const euros = (v) => (v == null ? "–" : `${nf.format(v)} €/m²`);
export const pourcent = (v, d = 0) =>
  v == null || !isFinite(v) ? "–" : `${v.toLocaleString("fr-FR", {maximumFractionDigits: d, minimumFractionDigits: d})} %`;
export const evolution = (v) =>
  v == null ? "–" : `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v * 100).toLocaleString("fr-FR", {maximumFractionDigits: 0})} %`;

/** Seuil sous lequel une valeur (moyenne ou médiane) est signalée comme fragile (effectif faible). */
export const EFFECTIF_FAIBLE = 30;

// ---------- Marché ----------
const dans = (a, lo, hi) => a >= lo && a <= hi;

/** Courbe « toutes communes » (ré-agrégée depuis les mutations, pas une moyenne de moyennes). */
export const serieGlobale = (type, lo, hi) =>
  marche.global.filter((d) => d.type_local === type && dans(d.annee, lo, hi));

export const serieCommune = (dvf, type, lo, hi) =>
  marche.communes
    .filter((d) => d.commune === dvf && d.type_local === type && dans(d.annee, lo, hi))
    .sort((a, b) => a.annee.localeCompare(b.annee));

// ---------- Impact DPE ----------
/**
 * Agrégat par regroupement × type pour une commune et une plage d'années.
 * Le cube n'exporte que les plages commençant après la réforme : une plage
 * [2016, 2023] contient exactement les mêmes points que [2021, 2023]
 * (cube_start_year, testé côté Python).
 */
export function impactAgregat(dvf, lo, hi) {
  if (hi < anneeReforme) return [];
  const debut = lo > anneeReforme ? lo : anneeReforme;
  return impact.cube.filter((d) => d.commune === dvf && d.annee_min === debut && d.annee_max === hi);
}

/** Composition du sous-ensemble (retenues, consensus, pré-réforme exclus) : somme des années. */
export function impactComptages(dvf, type, groupe, lo, hi) {
  const t = type ?? null;
  const g = groupe ?? null;
  const total = {retenues: 0, resolu_consensus: 0, pre_reforme_exclus: 0};
  for (const d of impact.comptages) {
    if (d.commune !== dvf || d.type_local !== t || d.groupe !== g || !dans(d.annee, lo, hi)) continue;
    total.retenues += d.retenues;
    total.resolu_consensus += d.resolu_consensus;
    total.pre_reforme_exclus += d.pre_reforme_exclus;
  }
  return total;
}

/** Prix/m² par étiquette exacte A–G ; `dvf` null = tout le périmètre. */
export const echelle = (dvf, type) =>
  impact.echelle.filter((d) => d.commune === (dvf ?? null) && d.type_local === type);

// ---------- Carte IRIS ----------
/**
 * Prix/m² moyen par IRIS sur une plage d'années : somme des prix/m² ÷ nombre de
 * ventes, les deux additifs par année (iris_year_sums, testé côté Python).
 */
export function irisValeurs(type, lo, hi) {
  const par = new Map();
  for (const d of iris) {
    if (d.type_local !== type || !dans(d.annee, lo, hi)) continue;
    const z = par.get(d.code_iris) ?? {code_iris: d.code_iris, nom_iris: d.nom_iris, somme: 0, n: 0};
    z.somme += d.somme;
    z.n += d.n;
    par.set(d.code_iris, z);
  }
  return [...par.values()].map(({somme, ...z}) => ({...z, valeur: somme / z.n}));
}

// ---------- Communes ----------
export const tableauCommunes = communesData.tableau;

/** Effectifs par état d'appariement pour une commune (ordre canonique). */
export function appariementCommune(dvf) {
  const lignes = communesData.appariement.filter((d) => d.commune === dvf);
  const total = lignes.reduce((s, d) => s + d.n, 0);
  return {
    total,
    etats: meta.appariement.statuses.map(({status, label}) => {
      const n = lignes.find((d) => d.match_status === status)?.n ?? 0;
      return {status, label, n, pct: total ? (100 * n) / total : 0};
    })
  };
}
