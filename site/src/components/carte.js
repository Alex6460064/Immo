// Carte choroplèthe IRIS : MapLibre GL JS + fond OpenFreeMap (libre, sans jeton).
// Classes par quantiles (7 paliers d'une rampe bleue unique, skill dataviz) :
// les prix IRIS sont très asymétriques, une échelle linéaire écraserait tout sauf
// le front de mer.
// v4 : build UMD avec worker intégré (le worker ESM séparé de v5+ ne se charge pas via le CDN du build).
import maplibregl from "npm:maplibre-gl@4.7.1";
import {html} from "npm:htl";
import {euros, nombre, EFFECTIF_FAIBLE} from "./donnees.js";

// Sur fond sombre, la rampe s'inverse : les faibles valeurs se fondent dans le fond,
// les fortes ressortent (même logique « peu = discret » que sur fond clair).
const RAMPE_CLAIR = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"];
const RAMPE_SOMBRE = ["#104281", "#184f95", "#1c5cab", "#2a78d6", "#5598e7", "#86b6ef", "#cde2fb"];
const K = RAMPE_CLAIR.length;
const STYLES = {
  clair: "https://tiles.openfreemap.org/styles/positron",
  sombre: "https://tiles.openfreemap.org/styles/dark"
};

const themeSombre = () => {
  const t = document.documentElement.dataset.theme;
  return t ? t === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
};

/** Bornes de quantiles (k classes) sur les valeurs. */
function quantiles(valeurs, k = K) {
  const v = [...valeurs].sort((a, b) => a - b);
  const bornes = [];
  for (let i = 1; i < k; i++) bornes.push(v[Math.min(v.length - 1, Math.floor((i * v.length) / k))]);
  return [...new Set(bornes)];
}

function emprise(features) {
  let [x0, y0, x1, y1] = [Infinity, Infinity, -Infinity, -Infinity];
  const visiter = (c) => {
    if (typeof c[0] === "number") {
      x0 = Math.min(x0, c[0]);
      x1 = Math.max(x1, c[0]);
      y0 = Math.min(y0, c[1]);
      y1 = Math.max(y1, c[1]);
    } else c.forEach(visiter);
  };
  features.forEach((f) => visiter(f.geometry.coordinates));
  return [
    [x0, y0],
    [x1, y1]
  ];
}

/**
 * Crée la carte une fois ; renvoie {element, legende, mettreAJour(valeurs, codeCommune)}.
 * `invalidation` : promesse Observable pour libérer le contexte WebGL.
 */
export function carteIris(contours, invalidation) {
  const element = html`<div class="carte" role="region" aria-label="Carte des prix au m² par quartier IRIS"></div>`;
  const bulle = html`<div class="carte-bulle" hidden></div>`;
  const legende = html`<div class="carte-legende" aria-live="polite"></div>`;
  element.append(bulle);

  let sombre = themeSombre();
  const carte = new maplibregl.Map({
    container: element,
    style: sombre ? STYLES.sombre : STYLES.clair,
    // Centre provisoire ; le recadrage exact attend que le conteneur ait une taille.
    center: [-1.5, 43.45],
    zoom: 9.5,
    attributionControl: {compact: true},
    cooperativeGestures: true,
    maxZoom: 15,
    minZoom: 8
  });
  carte.addControl(new maplibregl.NavigationControl({showCompass: false}), "top-right");

  // `code` indéfini : la première mise à jour recadre toujours (le conteneur n'a
  // pas de taille tant qu'il n'est pas inséré dans la page).
  let etat = {valeurs: [], code: undefined};
  const donnees = () => {
    const par = new Map(etat.valeurs.map((d) => [d.code_iris, d]));
    return {
      ...contours,
      features: contours.features.map((f, i) => {
        const d = par.get(f.properties.code_iris);
        return {...f, id: i, properties: {...f.properties, valeur: d?.valeur ?? null, n: d?.n ?? 0}};
      })
    };
  };
  const rampe = () => (sombre ? RAMPE_SOMBRE : RAMPE_CLAIR);
  const expressionCouleur = (bornes) => {
    const r = rampe();
    const e = ["step", ["get", "valeur"], r[0]];
    bornes.forEach((b, i) => e.push(b, r[i + 1]));
    return ["case", ["==", ["get", "valeur"], null], "rgba(0,0,0,0)", e];
  };

  function couches() {
    if (carte.getSource("iris")) return;
    const bornes = quantiles(etat.valeurs.map((d) => d.valeur));
    carte.addSource("iris", {type: "geojson", data: donnees()});
    const avant = carte.getStyle().layers.find((l) => l.type === "symbol")?.id;
    carte.addLayer(
      {
        id: "iris-fond",
        type: "fill",
        source: "iris",
        paint: {
          "fill-color": expressionCouleur(bornes),
          "fill-opacity": ["case", ["boolean", ["feature-state", "survol"], false], 0.92, 0.78]
        }
      },
      avant
    );
    carte.addLayer(
      {
        id: "iris-contour",
        type: "line",
        source: "iris",
        paint: {
          "line-color": ["case", ["boolean", ["feature-state", "survol"], false], sombre ? "#ffffff" : "#13212b", sombre ? "#0e171e" : "#ffffff"],
          "line-width": ["case", ["boolean", ["feature-state", "survol"], false], 2, 0.7],
          "line-dasharray": ["case", ["==", ["get", "valeur"], null], ["literal", [2, 2]], ["literal", [1, 0]]]
        }
      },
      avant
    );
    appliquer();
  }

  function appliquer() {
    if (!carte.getSource("iris")) return;
    const bornes = quantiles(etat.valeurs.map((d) => d.valeur));
    carte.getSource("iris").setData(donnees());
    carte.setPaintProperty("iris-fond", "fill-color", expressionCouleur(bornes));
    rendreLegende(bornes);
  }

  function rendreLegende(bornes) {
    const v = etat.valeurs.map((d) => d.valeur);
    if (!v.length) {
      legende.replaceChildren(html`<span>Aucun quartier renseigné pour cette sélection.</span>`);
      return;
    }
    const limites = [Math.min(...v), ...bornes, Math.max(...v)];
    legende.replaceChildren(
      html`<span class="carte-legende-rampe">${rampe().slice(0, bornes.length + 1).map(
        (c, i) => html`<span><i style=${{background: c}}></i>${i === 0 ? `${nombre(limites[0])} €` : nombre(limites[i])}</span>`
      )}</span>`,
      html`<span>€/m², ${bornes.length + 1} classes d'effectifs de quartiers égaux · max ${nombre(limites[limites.length - 1])} €</span>`,
      html`<span class="carte-sans-donnee"><i></i>pas de vente de ce type</span>`
    );
  }

  let survol = null;
  const effacer = () => {
    if (survol != null) carte.setFeatureState({source: "iris", id: survol}, {survol: false});
    survol = null;
    bulle.hidden = true;
  };
  carte.on("mousemove", "iris-fond", (e) => {
    const f = e.features?.[0];
    if (!f) return;
    if (survol !== f.id) {
      effacer();
      survol = f.id;
      carte.setFeatureState({source: "iris", id: survol}, {survol: true});
    }
    carte.getCanvas().style.cursor = "pointer";
    const p = f.properties;
    const valeur = p.valeur === "null" || p.valeur == null ? null : +p.valeur;
    bulle.replaceChildren(
      html`<strong>${p.nom_iris}</strong>`,
      html`<span>${p.nom_commune}</span><br>`,
      valeur == null
        ? html`<span>Aucune vente de ce type</span>`
        : html`<span>${euros(valeur)} · ${nombre(+p.n)} ventes${+p.n < EFFECTIF_FAIBLE ? " (effectif faible)" : ""}</span>`
    );
    bulle.hidden = false;
    const {x, y} = e.point;
    const droite = x > element.clientWidth - 250;
    bulle.style.left = `${droite ? x - 12 - bulle.offsetWidth : x + 14}px`;
    bulle.style.top = `${Math.max(8, y - 12)}px`;
  });
  carte.on("mouseleave", "iris-fond", () => {
    carte.getCanvas().style.cursor = "";
    effacer();
  });

  carte.on("load", couches);
  // Changer de fond (thème) efface les couches : on les recrée sur le nouveau style.
  carte.on("style.load", couches);
  const suivreTheme = () => {
    const s = themeSombre();
    if (s === sombre) return;
    sombre = s;
    survol = null;
    carte.setStyle(sombre ? STYLES.sombre : STYLES.clair);
  };
  const observer = new MutationObserver(suivreTheme);
  observer.observe(document.documentElement, {attributes: true, attributeFilter: ["data-theme"]});
  const media = matchMedia("(prefers-color-scheme: dark)");
  media.addEventListener("change", suivreTheme);
  let taille = 0;
  new ResizeObserver(() => {
    carte.resize();
    // Premier affichage réel : recadrer sur la sélection courante.
    if (!taille && element.clientWidth) {
      taille = element.clientWidth;
      recadrer(0);
    }
  }).observe(element);

  invalidation?.then(() => {
    observer.disconnect();
    media.removeEventListener("change", suivreTheme);
    carte.remove();
  });

  function mettreAJour(valeurs, codeCommune) {
    const changeCommune = codeCommune !== etat.code;
    etat = {valeurs, code: codeCommune};
    appliquer();
    if (changeCommune) recadrer(matchMedia("(prefers-reduced-motion: reduce)").matches ? 0 : 700);
  }

  function recadrer(duration) {
    if (!element.clientWidth) return;
    const cible = etat.code ? contours.features.filter((f) => f.properties.code_insee === etat.code) : contours.features;
    if (cible.length) carte.fitBounds(emprise(cible), {padding: 32, duration});
  }

  return {element, legende, mettreAJour};
}
