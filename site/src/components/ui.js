// Contrôles de filtre. Inputs Observable quand ils suffisent (habillés en CSS),
// composant maison pour la sélection de communes : l'ordre de sélection fixe la
// couleur, qui ne change plus tant que la commune reste cochée (skill dataviz :
// la couleur suit l'entité, jamais son rang).
import * as Inputs from "npm:@observablehq/inputs";
import {html} from "npm:htl";

/** Contrôle segmenté (quelques options exclusives). */
export function segment(options, {label, value, format} = {}) {
  const input = Inputs.radio(options, {label, value: value ?? options[0], format});
  input.classList.add("segment");
  return input;
}

export function liste(options, {label, value, format} = {}) {
  return Inputs.select(options, {label, value, format});
}

/** Plage d'années : deux listes liées (début ≤ fin). Valeur : [début, fin]. */
export function periode(annees, {label = "Période", value} = {}) {
  let [lo, hi] = value ?? [annees[0], annees[annees.length - 1]];
  const opt = (a, sel) => html`<option value=${a} selected=${a === sel}>${a}</option>`;
  const debut = html`<select aria-label="Année de début">${annees.map((a) => opt(a, lo))}</select>`;
  const fin = html`<select aria-label="Année de fin">${annees.map((a) => opt(a, hi))}</select>`;
  const root = html`<form class="periode"><label>${label}</label><div style="display:flex;align-items:center;gap:.4rem">${debut}<span aria-hidden="true">à</span>${fin}</div></form>`;
  const sync = (event) => {
    lo = debut.value;
    hi = fin.value;
    if (lo > hi) {
      if (event.target === debut) hi = fin.value = lo;
      else lo = debut.value = hi;
    }
    root.value = [lo, hi];
    root.dispatchEvent(new Event("input", {bubbles: true}));
  };
  debut.onchange = fin.onchange = sync;
  root.onsubmit = (e) => e.preventDefault();
  root.value = [lo, hi];
  return root;
}

/**
 * Pastilles de sélection multiple, `max` au plus. Valeur : [{valeur, couleur}]
 * dans l'ordre de sélection ; chaque commune garde sa couleur (emplacement
 * libre le plus bas) tant qu'elle reste sélectionnée.
 */
export function pastilles(options, {label, max = 5, couleurs, format = String, value = []} = {}) {
  const emplacement = new Map(); // valeur -> index de couleur
  for (const v of value) emplacement.set(v, emplacement.size);
  const boutons = options.map((o) => {
    const b = html`<button type="button" class="pastille" aria-pressed="false"><span class="pastille-couleur" aria-hidden="true"></span>${format(o)}</button>`;
    b.onclick = () => {
      if (emplacement.has(o)) emplacement.delete(o);
      else if (emplacement.size < max) {
        const pris = new Set(emplacement.values());
        let i = 0;
        while (pris.has(i)) i++;
        emplacement.set(o, i);
      }
      rendre();
      root.dispatchEvent(new Event("input", {bubbles: true}));
    };
    return b;
  });
  const aide = html`<span class="remarque" style="font-size:.82rem"></span>`;
  const root = html`<div class="pastilles" role="group" aria-label=${label}>
    <span class="pastilles-titre">${label}</span>
    <div class="pastilles-liste">${boutons}</div>
    ${aide}
  </div>`;
  function rendre() {
    options.forEach((o, i) => {
      const on = emplacement.has(o);
      const b = boutons[i];
      b.setAttribute("aria-pressed", String(on));
      b.disabled = !on && emplacement.size >= max;
      b.firstChild.style.background = on ? couleurs[emplacement.get(o)] : "";
    });
    aide.textContent = emplacement.size >= max ? `${max} communes au plus : retirez-en une pour en ajouter une autre.` : "";
    root.value = [...emplacement].map(([valeur, i]) => ({valeur, couleur: couleurs[i]}));
  }
  rendre();
  return root;
}
