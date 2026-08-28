// Synthèse PDF recruteurs -- rendu (pipeline/07_report.py fournit les données).
//
// Entrée : sys.inputs.data = chaîne JSON produite par pipeline/07_report.py
// (_build_data). Aucun calcul ici, uniquement la mise en page.
//
// Reproductibilité bit-à-bit (comme data/dashboard/) :
//   - polices : uniquement celles embarquées dans le binaire typst
//     (compile avec ignore_system_fonts=True) -- Libertinus Serif ;
//   - `set document(date: none)` : aucune date dans le PDF ;
//   - lilaq épinglé à une version exacte ;
//   - la version du paquet pip `typst` est épinglée dans pyproject.toml.

#import "@preview/lilaq:0.5.0" as lq

#let d = json(bytes(sys.inputs.at("data")))
#let meta = d.meta

#let ACCENT = rgb("#1f6feb")
#let INK = rgb("#1b1f24")
#let MUTED = rgb("#57606a")
#let HAIR = rgb("#d0d7de")
#let PANEL = rgb("#f6f8fa")
#let VERT = rgb("#1a7f37")
#let ROUGE = rgb("#cf222e")

#set document(title: "Synthèse Pays Basque -- marché immobilier & DPE", date: none)
#set text(font: "Libertinus Serif", size: 10.5pt, fill: INK, lang: "fr")
#set par(justify: true, leading: 0.62em, spacing: 1.1em)

#set page(
  paper: "a4",
  margin: (x: 2.3cm, top: 2.5cm, bottom: 2.2cm),
  header: context {
    if counter(page).get().first() == 1 { return }
    set text(size: 8pt, fill: MUTED)
    grid(columns: (1fr, auto), [Synthèse Pays Basque], [Marché immobilier & performance énergétique])
    v(-0.4em)
    line(length: 100%, stroke: 0.5pt + HAIR)
  },
  footer: context {
    if counter(page).get().first() == 1 { return }
    set text(size: 8pt, fill: MUTED)
    align(center, [#counter(page).display() / #counter(page).final().first()])
  },
)

#show heading.where(level: 1): it => block(below: 0.9em, text(size: 19pt, weight: "bold", it.body))
#show heading.where(level: 2): it => block(above: 1.05em, below: 0.5em, text(size: 12pt, weight: "bold", fill: ACCENT, it.body))

#let m2 = [m#super[2]]
#let source = [Sources : DVF (DGFiP, fichier brut) + DPE post-réforme (ADEME, #raw("dpe-v2-logements-existants")). Prix/#m2 calculé par mutation (ADR 0006).]
#let titre_ville(v) = upper(v.at(0)) + lower(v.slice(1))

#let callout(body) = block(
  width: 100%, fill: PANEL, inset: 11pt, radius: 2pt,
  stroke: (left: 2pt + ACCENT), body,
)

// Entier avec espace fine insécable comme séparateur de milliers.
#let group(x) = {
  let s = str(calc.round(x))
  let neg = s.starts-with("-")
  if neg { s = s.slice(1) }
  let chunks = ()
  for (i, c) in s.clusters().rev().enumerate() {
    if i > 0 and calc.rem(i, 3) == 0 { chunks.push(sym.space.nobreak.narrow) }
    chunks.push(c)
  }
  (if neg { sym.minus } else { "" }) + chunks.rev().join()
}
#let eur(x) = [#group(x)#sym.space.nobreak.narrow#sym.euro]
#let serie_couleur(s) = rgb(s.couleur)
#let pastille(s) = box(baseline: 0.15em, square(size: 0.72em, fill: serie_couleur(s), stroke: none))


// --------------------------------------------------------------------- couverture

#{
  set align(center)
  v(2.6cm)
  text(size: 25pt, weight: "bold")[
    Marché immobilier\
    & performance énergétique
  ]
  v(0.5cm)
  text(size: 13pt, fill: MUTED, meta.villes.map(titre_ville).join([ #sym.space #sym.dot.c #sym.space ]))
  v(0.28cm)
  line(length: 3cm, stroke: 1pt + ACCENT)
  v(0.28cm)
  text(size: 9.5pt, fill: MUTED)[
    Ventes DVF #meta.annee_min#sym.dash.en#meta.annee_max
    #h(0.5em) #sym.dot.c #h(0.5em)
    DPE : méthode en vigueur depuis #meta.post_reforme
  ]
}

#v(1.5cm)

== Contenu

+ Évolution du prix/#m2 moyen par commune (Appartement / Maison), variations sur près de 10 ans, sur 5 ans et sur 1 an.
+ Prix/#m2 moyen par étiquette DPE (A#sym.dash.en#h(0pt)G) et par commune depuis 2021, et ce que ce chiffre brut ne dit pas (biais de localisation).

#v(0.5cm)

#callout[
  *Appariement DVF #sym.arrow.l.r DPE* : #group(d.appariement.certains) / #group(d.appariement.total) mutations
  résidentielles des #meta.villes.len() communes rapprochées d'un DPE d'étiquette certaine
  (#calc.round(d.appariement.taux)#sym.space.nobreak.narrow%).

  Ce taux, structurellement limité par le périmètre DPE post-réforme (une vente d'avant 2021
  n'a de DPE que si un second a été réalisé depuis), est affiché ici comme une donnée du
  projet, pas masqué.
]

#v(1fr)
#text(size: 8pt, fill: MUTED)[
  Généré par #raw("pipeline/07_report.py") à partir de l'instantané versionné #raw("data/dashboard/"). #source
]

#pagebreak()


// ----------------------------------------------------------------- pages communes

#let courbe_commune(c) = lq.diagram(
  width: 15.8cm, height: 10.5cm,
  ylabel: [EUR / #m2],
  yaxis: (exponent: none),
  legend: (position: top + left),
  ..c.series.map(s => lq.plot(
    s.points.map(p => int(p.annee)),
    s.points.map(p => p.prix),
    mark: "o", stroke: serie_couleur(s) + 1.2pt, mark-color: serie_couleur(s), label: s.type,
  )),
)

#let table_evolution(s) = {
  block(above: 0.95em, below: 0.4em)[
    #text(weight: "bold", fill: serie_couleur(s))[#s.type]
    #h(0.7em)
    #text(size: 8.5pt, fill: MUTED)[
      n #s.annee_debut = #s.n_debut #h(0.4em)#sym.dot.c#h(0.4em) n #meta.annee_ref = #s.n_fin
    ]
  ]
  table(
    columns: (7em, 1fr, 1fr, 1fr),
    align: (left, right, right, right),
    stroke: none,
    inset: (x: 6pt, y: 3.5pt),
    fill: (_, row) => if row == 0 { PANEL },
    table.header([Fenêtre], [Départ], [#meta.annee_ref], [Variation]),
    ..s.evolutions.map(e => (
      [#e.libelle], eur(e.prix_debut), eur(e.prix_fin),
      text(fill: if e.variation_pct >= 0 { VERT } else { ROUGE })[#e.variation_txt],
    )).flatten(),
    ..s.sautees.map(x => (
      [#x.libelle], [#sym.dash.em], [#sym.dash.em],
      text(fill: MUTED, size: 9pt)[non calculé : #x.raison],
    )).flatten(),
  )
}

#for c in d.communes {
  heading(level: 1, c.nom_affiche)
  courbe_commune(c)
  for s in c.series { table_evolution(s) }
  pagebreak()
}


// ------------------------------------------------------------------- pages DPE

#let etiquettes = ("A", "B", "C", "D", "E", "F", "G")

#let barres_dpe(pc) = lq.diagram(
  width: 15.8cm, height: 3.8cm,
  title: pc.nom_affiche,
  ylabel: [EUR / #m2],
  yaxis: (exponent: none),
  xaxis: (ticks: range(7).zip(etiquettes)),
  legend: none,
  ..pc.series.enumerate().map(((i, s)) => lq.bar(
    range(7).map(k => k + (i - 0.5) * 0.38),
    s.pm2,
    width: 0.38, fill: serie_couleur(s), label: s.type,
  )),
)

#let table_effectifs(pc) = table(
  columns: (6.5em,) + (1fr,) * 7,
  align: (left,) + (right,) * 7,
  stroke: none,
  inset: (x: 4pt, y: 2.5pt),
  fill: (_, row) => if row == 0 { PANEL },
  table.header(text(size: 8pt, fill: MUTED)[n par classe], ..etiquettes.map(e => text(size: 8.5pt)[#e])),
  ..pc.series.map(s => (text(size: 8.5pt)[#s.type], ..s.n.map(v => text(size: 8.5pt)[#v]))).flatten(),
)

= Prix/#m2 moyen par étiquette DPE

Ventes depuis juillet 2021. Un panneau par commune, chacun à son échelle : les écarts de
niveau entre communes (Biarritz environ 2#sym.times Bayonne) écraseraient tout gradient DPE
sur une échelle partagée -- c'est justement le confondant expliqué page suivante.

#align(center, text(size: 9pt)[
  #d.dpe.par_commune.first().series.map(s => [#pastille(s) #s.type]).join(h(1.6em))
])

#for pc in d.dpe.par_commune {
  block(above: 0.5em, breakable: false)[
    #barres_dpe(pc)
    #table_effectifs(pc)
  ]
}

#v(0.5em)
#text(size: 8.5pt, fill: MUTED, style: "italic")[
  Lecture prudente : ces barres ne mesurent pas une décote DPE -- voir page suivante. #source
]

#pagebreak()

= Impact DPE -- lecture critique

== Ce que le graphe précédent ne dit pas

Attendu : à bien comparable, une étiquette F ou G se vend moins cher qu'une étiquette C ou
D (coût des travaux, contrainte de location). Sur ce périmètre, les barres brutes montrent
souvent l'*inverse*.

== Pourquoi

L'étiquette DPE est corrélée à la localisation. Les logements énergivores (F/G) sont
surtout de l'ancien de centre-ville et de front de mer -- les secteurs les plus chers au
#m2. La classe DPE capte donc surtout l'adresse, pas la performance : le prix/#m2 par
classe mélange deux effets de sens opposés.

== Exemples d'écarts bruts

Classe vs classe D, même commune / même type :

#if d.dpe.exemples_ecarts.len() > 0 {
  list(..d.dpe.exemples_ecarts.map(x => [#x]))
} else [
  #text(fill: MUTED)[(pas assez d'observations F/G exploitables)]
]

== Conclusion

À ce niveau d'agrégation, le signe de l'écart est instable d'une commune et d'un type à
l'autre (les appartements F ressortent légèrement sous la classe D, mais G repart
au-dessus, sur de petits effectifs). Aucune décote DPE robuste ne se dégage : l'effet
énergétique, s'il existe, est du même ordre que le bruit et dominé par la localisation. Le
mesurer proprement demande de comparer à quartier comparable (écart par classe calculé
*dans* chaque IRIS puis moyenné) -- extension identifiée, non traitée ici.

#callout[
  C'est une limite assumée, pas un résultat caché : le dashboard applique la même prudence
  (comparaison DPE par commune uniquement).
]
