"""Dashboard DVF x DPE Pays Basque -- Streamlit + Plotly (issues #14, #15).

    streamlit run dashboard/app.py

Deux vues :
  - "Marche" (#14) : courbe de reference "toutes communes" (prix/m2 par annee,
    re-agregee depuis les mutations) + une courbe par commune cochee ; toggle
    "Statistique" moyenne / mediane qui pilote la courbe ET la carte choroplethe
    IRIS. Defaut : moyenne.
  - "Impact DPE" (#15) : prix/m2 par regroupement d'etiquette DPE (A-C / D / E /
    F-G) pour UNE commune (obligatoire -- comparer entre communes n'est pas
    pertinent), sur le sous-ensemble apparie post-reforme, avec le taux
    d'appariement (4 etats) et l'avertissement sur le decalage temporel DVF / DPE.

Toute la logique de chargement / filtrage / agregation est dans
`dashboard/data.py` (seam teste). Ce fichier ne fait que le cablage UI + Plotly,
verifie manuellement en lancant le dashboard (CLAUDE.md : pas de test visuel
automatise).

La carte utilise `go.Choroplethmap` (trace MapLibre, sans jeton) : le
`px.choropleth_mapbox` mentionne dans l'issue #14 est deprecie depuis Plotly 6.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dashboard import data  # noqa: E402

TOUTES_COMMUNES = "Toutes les communes"
TOUS_TYPES = "Tous"
TOUS_GROUPES = "Tous"

# Carte : centre de repli si le recadrage sur la selection echoue.
_MAP_CENTER = {"lat": 43.44, "lon": -1.52}
_GROUP_COLORS = {"A-C": "#1a9850", "D": "#f9d057", "E": "#fc8d59", "F-G": "#d73027"}

_HOVER = "%{x} · %{y:,.0f} €/m² · n=%{customdata}<extra></extra>"
_HOVER_NAMED = "%{x} · %{y:,.0f} €/m² · n=%{customdata}<extra>%{fullData.name}</extra>"

st.set_page_config(page_title="DVF x DPE Pays Basque", layout="wide")


def _n(value: float) -> str:
    return format(int(round(value)), ",").replace(",", " ")


@dataclass(frozen=True)
class Filters:
    """Selection de la barre laterale, partagee par les deux vues."""

    vue: str
    commune: dict | None  # vue Marche : pilote la carte IRIS (None = toutes).
    #   vue Impact DPE : commune obligatoire (jamais None).
    annee_min: str
    annee_max: str
    type_local: str | None  # None = tous types de bien
    groupe: str | None  # regroupement DPE (vue Impact DPE), None = tous
    stat: str = "moyenne"  # "moyenne" | "mediane" -- courbe + carte de la vue Marche
    communes_compare: tuple[str, ...] = ()  # noms casse DVF a superposer (vue Marche)

    @property
    def date_min(self) -> str:
        return f"{self.annee_min}-01-01"

    @property
    def date_max(self) -> str:
        return f"{self.annee_max}-12-31"

    @property
    def commune_dvf(self) -> str | None:
        """Nom casse DVF (`agg_marche`, `dvf_dpe_matched`)."""
        return self.commune["dvf_nom"] if self.commune else None

    @property
    def code_commune(self) -> str | None:
        return self.commune["code_insee"] if self.commune else None


@st.cache_data
def _agg_marche() -> list[dict]:
    return data.load_agg_marche()


@st.cache_data
def _agg_iris() -> list[dict]:
    return data.load_agg_iris()


@st.cache_data
def _matched() -> list[dict]:
    return data.load_matched()


@st.cache_data
def _matching_counts() -> dict[str, int]:
    return data.load_matching_counts()


@st.cache_data
def _geojson() -> dict:
    return data.load_iris_geojson()


def _sidebar(annees: list[str]) -> Filters:
    st.sidebar.title("DVF × DPE Pays Basque")
    vue = st.sidebar.radio("Vue", ["Marché", "Impact DPE"])

    choices = data.commune_choices()
    noms = sorted(c["nom"] for c in choices)
    annee_min, annee_max = st.sidebar.select_slider(
        "Période", options=annees, value=(annees[0], annees[-1])
    )

    if vue == "Marché":
        # Courbe de référence = toutes communes ; les communes cochées se
        # superposent. Une stat (moyenne / médiane) n'a de sens que sur une
        # population homogène -> un type de bien est obligatoire (pas de "Tous").
        stat_sel = st.sidebar.radio("Statistique", ["Moyenne", "Médiane"], horizontal=True)
        stat = "moyenne" if stat_sel == "Moyenne" else "mediane"
        type_local = st.sidebar.selectbox("Type de bien", list(data.TYPES_BIEN))
        sel = st.sidebar.multiselect("Communes à comparer", noms)
        communes_compare = tuple(c["dvf_nom"] for c in choices if c["nom"] in sel)
        # Selectbox distinct : pilote uniquement la carte IRIS (comportement
        # inchangé -- global par défaut, zoom commune par commune).
        nom_carte = st.sidebar.selectbox("Carte — commune", [TOUTES_COMMUNES, *noms])
        commune = next((c for c in choices if c["nom"] == nom_carte), None)
        return Filters(
            vue=vue,
            commune=commune,
            annee_min=annee_min,
            annee_max=annee_max,
            type_local=type_local,
            groupe=None,
            stat=stat,
            communes_compare=communes_compare,
        )

    # Vue Impact DPE : commune obligatoire. Mélanger les communes n'est pas
    # comparable (un bien F à Biarritz front de mer reste plus cher qu'un bien A
    # à Hasparren) -> pas d'option "Toutes". "Tous" types reste autorisé, les
    # barres restent séparées par type.
    default_idx = noms.index("Anglet") if "Anglet" in noms else 0
    nom_sel = st.sidebar.selectbox("Commune", noms, index=default_idx)
    commune = next(c for c in choices if c["nom"] == nom_sel)
    type_sel = st.sidebar.selectbox("Type de bien", [TOUS_TYPES, *data.TYPES_BIEN])
    type_local = None if type_sel == TOUS_TYPES else type_sel
    groupe_sel = st.sidebar.selectbox("Regroupement DPE", [TOUS_GROUPES, *data.DPE_GROUPS])
    groupe = None if groupe_sel == TOUS_GROUPES else groupe_sel
    return Filters(
        vue=vue,
        commune=commune,
        annee_min=annee_min,
        annee_max=annee_max,
        type_local=type_local,
        groupe=groupe,
        stat="mediane",
    )


def _vue_marche(f: Filters) -> None:
    stat_label = f.stat.capitalize()
    st.header("Marché — prix au m²")
    st.caption(
        f"Ventes officielles DVF (DGFiP). Prix/m² calculé par mutation "
        f"(prix ÷ surface habitation totale, ADR 0006). Statistique affichée : "
        f"**{f.stat}** (toggle sidebar) ; `n` = nombre de transactions."
    )

    rows = _agg_marche()

    # Courbe de référence : toutes communes confondues, ré-agrégée depuis les
    # mutations (moyenne / médiane d'ensemble, pas une moyenne de moyennes).
    glob = data.market_trend_global(
        _matched(),
        type_local=f.type_local,
        annee_min=f.annee_min,
        annee_max=f.annee_max,
    )

    fig = go.Figure()
    if glob:
        fig.add_trace(
            go.Scatter(
                x=[r["annee"] for r in glob],
                y=[r[f.stat] for r in glob],
                mode="lines+markers",
                name="Toutes communes",
                line={"color": "#111111", "width": 3},
                customdata=[r["n"] for r in glob],
                hovertemplate=_HOVER_NAMED,
            )
        )
    for com in f.communes_compare:
        serie = data.market_trend(
            rows,
            commune=com,
            type_local=f.type_local,
            annee_min=f.annee_min,
            annee_max=f.annee_max,
        )
        if not serie:
            continue
        fig.add_trace(
            go.Scatter(
                x=[r["annee"] for r in serie],
                y=[r[f.stat] for r in serie],
                mode="lines+markers",
                name=com.title(),
                customdata=[r["n"] for r in serie],
                hovertemplate=_HOVER_NAMED,
            )
        )
    fig.update_layout(
        yaxis_title=f"{stat_label} €/m²",
        xaxis_title="Année de mutation",
        legend_title="Série",
        height=430,
        margin={"t": 30, "r": 10, "l": 10, "b": 10},
    )
    st.metric("Mutations toutes communes (période)", _n(sum(r["n"] for r in glob)))
    if glob:
        st.plotly_chart(fig, width="stretch")
    else:
        st.info("Aucune mutation pour cette sélection.")

    st.subheader(f"Carte — prix {f.stat}/m² par IRIS")
    st.caption(
        f"{stat_label} cumulée toutes années, pour le type de bien sélectionné "
        "(ADR 0004). Les communes à IRIS unique (zone = commune entière) "
        "apparaissent comme une seule zone. Le filtre *Période* n'agit pas sur "
        "la carte."
    )
    iris_vals = data.iris_map_values(
        _agg_iris(), type_local=f.type_local, stat=f.stat, code_commune=f.code_commune
    )
    if not iris_vals:
        st.info("Aucune zone IRIS pour cette sélection.")
        return

    codes = {r["code_iris"] for r in iris_vals}
    center = data.geojson_center(_geojson(), codes) or _MAP_CENTER
    zmin, zmax = data.color_range([r["valeur"] for r in iris_vals])
    map_fig = go.Figure(
        go.Choroplethmap(
            geojson=_geojson(),
            featureidkey="properties.code_iris",
            locations=[r["code_iris"] for r in iris_vals],
            z=[r["valeur"] for r in iris_vals],
            zmin=zmin,
            zmax=zmax,
            text=[r["nom_iris"] for r in iris_vals],
            customdata=[r["n"] for r in iris_vals],
            colorscale="Viridis",
            colorbar_title="€/m²",
            marker_line_width=0.4,
            marker_line_color="white",
            hovertemplate="%{text} · %{z:,.0f} €/m² · n=%{customdata}<extra></extra>",
        )
    )
    map_fig.update_layout(
        map_style="open-street-map",
        map_zoom=12 if f.code_commune else 9.3,
        map_center=center,
        height=520,
        margin={"t": 10, "r": 10, "l": 10, "b": 10},
    )
    # scrollZoom désactivé : sinon un défilement de page au-dessus de la carte
    # la zoome par accident.
    st.plotly_chart(map_fig, width="stretch", config={"scrollZoom": False})


def _matching_rate_block() -> None:
    rate = data.matching_rate(_matching_counts())
    st.subheader("Taux d'appariement DVF ↔ DPE")
    st.caption(
        f"Sur l'ensemble du périmètre ({_n(rate['total'])} mutations) — les 4 "
        "états sont affichés séparément, jamais fusionnés (CONTEXT.md)."
    )
    for col, s in zip(st.columns(4), rate["statuses"], strict=True):
        col.metric(s["label"].capitalize(), f"{s['pct']:.1f} %")
        col.caption(f"{_n(s['n'])} mutations")
    cert = rate["etiquette_certaine"]
    st.markdown(
        "**Étiquette DPE certaine** (trouvé + résolu par consensus) : "
        f"{_n(cert['n'])} mutations ({cert['pct']:.1f} %)."
    )


def _impact_breakdown_line(f: Filters, matched: list[dict]) -> None:
    b = data.impact_dpe_breakdown(
        matched,
        commune=f.commune_dvf,
        type_local=f.type_local,
        date_min=f.date_min,
        date_max=f.date_max,
        groupe=f.groupe,
    )
    phrase = (
        f"**{_n(b['retenues'])} mutations retenues** dans cette sélection, dont "
        f"{_n(b['resolu_consensus'])} résolues par consensus d'étiquette."
    )
    if b["pre_reforme_exclus"]:
        phrase += (
            f" {_n(b['pre_reforme_exclus'])} mutations à étiquette certaine mais "
            "antérieures à juillet 2021 sont exclues de ce graphique "
            "(cf. avertissement ci-dessus)."
        )
    st.markdown(phrase)


def _vue_impact_dpe(f: Filters) -> None:
    st.header(f"Impact DPE — {f.commune['nom']} — prix au m² par regroupement d'étiquette")

    _matching_rate_block()
    st.warning(data.TEMPORAL_GAP_NOTE)

    matched = _matched()
    _impact_breakdown_line(f, matched)

    agg = data.impact_dpe_aggregate(
        matched,
        commune=f.commune_dvf,
        type_local=f.type_local,
        date_min=f.date_min,
        date_max=f.date_max,
        groupe=f.groupe,
    )
    if not agg:
        st.info("Aucune mutation appariée post-réforme pour cette sélection.")
        return

    groupes = [g for g in data.DPE_GROUPS if any(r["groupe"] == g for r in agg)]
    fig = go.Figure()
    if f.type_local is None:
        for typ in data.TYPES_BIEN:
            sub = {r["groupe"]: r for r in agg if r["type_local"] == typ}
            if not sub:
                continue
            fig.add_trace(
                go.Bar(
                    name=typ,
                    x=groupes,
                    y=[sub[g]["mediane"] if g in sub else None for g in groupes],
                    customdata=[sub[g]["n"] if g in sub else 0 for g in groupes],
                    hovertemplate=_HOVER_NAMED,
                )
            )
        fig.update_layout(barmode="group", legend_title="Type de bien")
    else:
        by = {r["groupe"]: r for r in agg}
        fig.add_trace(
            go.Bar(
                x=groupes,
                y=[by[g]["mediane"] for g in groupes],
                marker_color=[_GROUP_COLORS.get(g, "#888") for g in groupes],
                customdata=[by[g]["n"] for g in groupes],
                hovertemplate=_HOVER,
            )
        )
    fig.update_layout(
        xaxis_title="Regroupement d'étiquette DPE",
        yaxis_title="Médiane €/m²",
        height=440,
        margin={"t": 30, "r": 10, "l": 10, "b": 10},
    )
    st.plotly_chart(fig, width="stretch")
    st.caption(
        "Regroupé en A–C / D / E / F–G faute d'un `n` suffisant par étiquette "
        "exacte sur l'échantillon apparié ; `n` par barre au survol. Écarts à "
        "lire comme un ordre de grandeur (cf. avertissement)."
    )


def main() -> None:
    try:
        annees = sorted({r["annee"] for r in _agg_marche() if r.get("annee")})
    except FileNotFoundError:
        st.error(
            "Agrégats introuvables dans `data/processed/`. Lancer le pipeline "
            "d'abord : `python pipeline/05_aggregate.py` (et les étapes amont)."
        )
        return

    f = _sidebar(annees)
    if f.vue == "Marché":
        _vue_marche(f)
    else:
        _vue_impact_dpe(f)


main()
