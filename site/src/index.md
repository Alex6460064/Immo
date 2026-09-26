---
title: Prix et étiquette énergie sur la côte basque
---

```js
import {meta, communes, nombre, pourcent, echelle, serieGlobale, annees} from "./components/donnees.js";
import {echelleDPE, etatsAppariement} from "./components/graphiques.js";
import {segment, liste} from "./components/ui.js";
```

```js
const choixType = segment(["Appartement", "Maison"], {label: "Type de bien"});
const choixTerritoire = liste([null, ...communes.map((c) => c.dvf_nom)], {
  label: "Territoire",
  format: (v) => (v == null ? `Les ${communes.length} communes` : communes.find((c) => c.dvf_nom === v).nom)
});
const typeBien = Generators.input(choixType);
const territoire = Generators.input(choixTerritoire);
```

```js
const premiere = annees[0];
const derniere = annees[annees.length - 1];
const evo = (t) => {
  const s = serieGlobale(t, premiere, derniere);
  return s.length > 1 ? s[s.length - 1].moyenne / s[0].moyenne - 1 : null;
};
const certaine = meta.appariement.etiquette_certaine;
const ecartF = (() => {
  const c = communes.find((d) => d.nom === "Bayonne");
  const par = new Map(echelle(c.dvf_nom, "Appartement").map((d) => [d.etiquette_dpe, d.moyenne]));
  const r = par.get("F") / par.get("C") - 1;
  return {nom: c.nom, texte: isFinite(r) ? `${Math.abs(Math.round(r * 100))} % ${r < 0 ? "moins cher" : "plus cher"}` : "à un prix non comparable"};
})();
```

<div class="ouverture">
<div>

# Sur la côte basque, l'étiquette énergie ne se voit pas dans le prix de vente

<p class="chapeau">Chaque vente immobilière de ${communes.length} communes, de Tarnos à Hendaye, rapprochée une à une de son diagnostic de performance énergétique. Résultat : un appartement classé G ne se vend pas moins cher au m² qu'un appartement classé A.</p>

Ce n'est pas que l'étiquette ne compte pas. Les logements F et G sont surtout de l'ancien, en centre-ville et près de l'océan, là où le mètre carré est le plus cher. **L'emplacement masque l'étiquette.** Comparer des biens comparables demanderait un modèle « toutes choses égales par ailleurs », que ce projet ne prétend pas faire : il montre la donnée brute et dit ce qu'elle ne permet pas de conclure.

À l'intérieur d'une seule commune, un écart apparaît : à ${ecartF.nom}, les appartements F se vendent ${ecartF.texte} au m² que les C. Il reste bruité, et c'est pourquoi l'étiquette ci-contre se lit aussi commune par commune.

[Explorer l'impact du DPE commune par commune](./impact-dpe)

</div>
<div class="echelle">
  <p class="echelle-titre">Prix moyen au m² selon l'étiquette DPE</p>
  <p class="echelle-sous-titre">Ventes depuis juillet 2021, rapprochées d'un diagnostic certain</p>
  <div class="filtres">${choixType}${choixTerritoire}</div>
  ${echelleDPE(echelle(territoire, typeBien), {})}
  <p class="echelle-pied">Un point évidé signale moins de 30 ventes : moyenne fragile.</p>
</div>
</div>

<div class="faits">
  <div><span class="fait-valeur">${nombre(meta.appariement.total)}</span><span class="fait-texte">lots vendus (lignes DVF) entre ${premiere} et ${derniere}</span></div>
  <div><span class="fait-valeur">${evo("Appartement") == null ? "–" : `+${Math.round(evo("Appartement") * 100)} %`}</span><span class="fait-texte">prix moyen au m² des appartements, ${premiere} → ${derniere}, toutes communes</span></div>
  <div><span class="fait-valeur">${pourcent(certaine.pct, 0)}</span><span class="fait-texte">des lots vendus rattachés à une étiquette DPE certaine (${nombre(certaine.n)})</span></div>
</div>

## Rapprocher une vente et un diagnostic

Aucun identifiant commun ne relie une vente à un DPE. L'algorithme compare l'adresse, puis la distance entre points géocodés (15 m au plus), puis la surface. Quand plusieurs diagnostics restent possibles, il ne tire pas au sort : la vente reste ambiguë. Les quatre issues sont publiées telles quelles.

```js
display(etatsAppariement(meta.appariement.statuses, {total: meta.appariement.total}));
```

<p class="remarque">Beaucoup d'ambigus : dans un immeuble, plusieurs appartements partagent l'adresse et souvent la surface. Le détail est dans la <a href="./methode">méthode</a>.</p>

## Explorer

<nav class="rubriques" aria-label="Rubriques du site">
  <a href="./marche"><strong>Marché</strong><span>Prix au m² année par année et carte des quartiers</span></a>
  <a href="./impact-dpe"><strong>Impact DPE</strong><span>Prix par étiquette énergie, commune par commune</span></a>
  <a href="./communes"><strong>Communes</strong><span>Les ${communes.length} communes comparées dans un tableau</span></a>
  <a href="./methode"><strong>Méthode</strong><span>Sources, nettoyage, rapprochement et limites</span></a>
</nav>
