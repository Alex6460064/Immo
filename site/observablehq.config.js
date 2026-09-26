// Site statique (#44). Les données (cubes précalculés, aucune logique métier en JS)
// sont produites par `python pipeline/08_export_site.py` dans src/data avant le build.
const pages = [
  ["Marché", "marche"],
  ["Impact DPE", "impact-dpe"],
  ["Communes", "communes"],
  ["Méthode", "methode"]
];

const favicon =
  "data:image/svg+xml,%3Csvg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 16 16%22%3E" +
  "%3Cpath d=%22M1 3h6l2 2-2 2H1z%22 fill=%22%23009c6d%22/%3E" +
  "%3Cpath d=%22M1 8h10l2 2-2 2H1z%22 fill=%22%23f0b40f%22/%3E" +
  "%3Cpath d=%22M1 13h13l1.5 1.5-1.5 1.5H1z%22 fill=%22%23d7221f%22/%3E%3C/svg%3E";

export default {
  title: "DVF × DPE Pays Basque",
  root: "src",
  output: "dist",
  // Thème clair/sombre maison dans style.css (le thème Observable est alors ignoré).
  style: "style.css",
  lang: "fr",
  search: false,
  toc: false,
  pager: false,
  preserveExtension: true,
  sidebar: false,
  // Le thème choisi est appliqué avant le premier rendu (pas de flash clair en mode sombre).
  head:
    '<script>try{var t=localStorage.getItem("theme");if(t==="light"||t==="dark")document.documentElement.dataset.theme=t}catch(e){}</script>' +
    '<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>' +
    '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Atkinson+Hyperlegible+Next:ital,wght@0,400;0,500;0,700;1,400&family=Bricolage+Grotesque:opsz,wght@12..96,500..800&display=swap">' +
    '<meta name="description" content="Prix de l\'immobilier et étiquettes énergie (DPE) sur la côte basque : ventes officielles DVF rapprochées des diagnostics ADEME, 2016-2025.">' +
    `<link rel="icon" href="${favicon}">`,
  pages: pages.map(([name, path]) => ({name, path: `/${path}`})),
  header: ({path}) => `<a class="marque" href="./"><span class="marque-signe" aria-hidden="true"><i></i><i></i><i></i></span>DVF × DPE <span class="marque-lieu">Pays Basque</span></a>
  <nav class="nav-principale" aria-label="Rubriques">${pages
    .map(([nom, p]) => `<a href="./${p}"${path === `/${p}` ? ' aria-current="page"' : ""}>${nom}</a>`)
    .join("")}</nav>
  <button type="button" class="bascule-theme" aria-label="Basculer entre thème clair et sombre" onclick="(function(){var r=document.documentElement,s=r.dataset.theme||(matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light'),n=s==='dark'?'light':'dark';r.dataset.theme=n;try{localStorage.setItem('theme',n)}catch(e){}})()">
    <svg class="icone-soleil" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>
    <svg class="icone-lune" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/></svg>
  </button>`,
  footer:
    'Données ouvertes DVF (DGFiP), DPE (ADEME), IRIS (INSEE / IGN). Fond de carte © <a href="https://openfreemap.org">OpenFreeMap</a>, données © contributeurs <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>. ' +
    '<a href="https://github.com/Alex6460064/Immo">Code, méthode et décisions sur GitHub</a>.'
};
