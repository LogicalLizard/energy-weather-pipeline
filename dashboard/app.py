from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

DB_PATH = Path(__file__).resolve().parents[1] / "data" / "processed" / "energy.duckdb"

# stack order (bottom to top) and colors validated for adjacency and CVD safety
MIX_COLORS = {
    "Coal": "#4a3aa7",
    "Other": "#e87ba4",
    "Biomass": "#008300",
    "Hydro": "#1baf7a",
    "Natural gas": "#eb6834",
    "Wind": "#2a78d6",
    "Solar": "#eda100",
}
TECH_GROUPS = {
    "lignite": "Coal",
    "hard_coal": "Coal",
    "pumped_storage": "Other",
    "other_conventional": "Other",
    "other_renewables": "Other",
    "biomass": "Biomass",
    "hydro": "Hydro",
    "natural_gas": "Natural gas",
    "wind_onshore": "Wind",
    "wind_offshore": "Wind",
    "solar": "Solar",
}
BLUE = "#2a78d6"
ORANGE = "#eb6834"
SURFACE = "#fcfcfb"
GRID = "#e1e0d9"
INK = "#52514e"

st.set_page_config(page_title="German Energy & Weather", layout="wide")


@st.cache_data(ttl=600)
def load_table(query: str) -> pd.DataFrame:
    # short-lived read-only connection: duckdb allows only one writer,
    # a held connection would block every dbt run
    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        df = con.sql(query).df()
    finally:
        con.close()
    df["ts"] = df["ts_utc"].dt.tz_convert("Europe/Berlin")
    return df


def styled(fig: go.Figure, y_title: str, hovermode: str = "x unified") -> go.Figure:
    fig.update_layout(
        template="plotly_white",
        margin=dict(l=0, r=0, t=10, b=0),
        height=380,
        font=dict(family="system-ui, -apple-system, Segoe UI, sans-serif", color=INK),
        plot_bgcolor=SURFACE,
        paper_bgcolor="rgba(0,0,0,0)",
        hovermode=hovermode,
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
    )
    fig.update_xaxes(gridcolor=GRID, linecolor="#c3c2b7", zeroline=False)
    fig.update_yaxes(gridcolor=GRID, linecolor="#c3c2b7", zeroline=False, title=y_title)
    return fig


if not DB_PATH.exists():
    st.error(
        "No database found. Run the pipeline first:\n\n"
        "`python -m src.ingestion.smard && python -m src.ingestion.open_meteo && "
        "dbt run --project-dir dbt --profiles-dir dbt`"
    )
    st.stop()

try:
    ew = load_table("select * from mart_energy_weather order by ts_utc")
    mix = load_table("select * from mart_generation_mix order by ts_utc")
except duckdb.CatalogException:
    st.error("Database exists but the mart tables are missing. Run: "
             "`dbt run --project-dir dbt --profiles-dir dbt`")
    st.stop()
except duckdb.IOException:
    st.warning("The database is currently being updated by the pipeline. Reload in a minute.")
    st.stop()
mix["group"] = mix["technology"].map(TECH_GROUPS)

st.title("German Energy & Weather")
st.caption(
    "Day-ahead electricity prices, generation mix and weather for Germany. "
    "Data: SMARD (Bundesnetzagentur) and Open-Meteo, updated daily."
)

range_days = {"Last 7 days": 7, "Last 30 days": 30, "Last 90 days": 90}
pick = st.radio("Time range", list(range_days), index=1, horizontal=True)
# anchor the window at the current hour, not at the newest timestamp in the data -
# day-ahead prices already extend into tomorrow and would shift every window forward
now = pd.Timestamp.now(tz="Europe/Berlin")
cutoff = now - pd.Timedelta(days=range_days[pick])
ew_v = ew[ew["ts"] >= cutoff]  # still includes tomorrow's day-ahead prices
ew_past = ew_v[ew_v["ts"] <= now]  # KPIs and correlations use elapsed hours only
mix_v = mix[mix["ts"] >= cutoff]

if ew_past.empty:
    st.warning("No data in the selected window. Run the ingestion scripts to refresh.")
    st.stop()

renewable_share = (
    100 * mix_v.loc[mix_v["is_renewable"], "generation_mwh"].sum() / mix_v["generation_mwh"].sum()
)
current_price = ew_past.dropna(subset=["price_eur_mwh"]).iloc[-1]
c1, c2, c3, c4 = st.columns(4)
c1.metric(
    "Current price",
    f"{current_price['price_eur_mwh']:.2f} €/MWh",
    help=f"Delivery hour starting {current_price['ts']:%Y-%m-%d %H:%M}",
)
c2.metric("Average price", f"{ew_past['price_eur_mwh'].mean():.2f} €/MWh")
c3.metric("Renewable share", f"{renewable_share:.0f} %")
c4.metric("Average wind speed", f"{ew_past['wind_speed_ms'].mean():.1f} m/s")

st.subheader("Day-ahead price")
fig = go.Figure()
fig.add_scatter(
    x=ew_v["ts"], y=ew_v["price_eur_mwh"], mode="lines",
    line=dict(color=BLUE, width=2), name="Price",
    hovertemplate="%{y:.2f} €/MWh<extra></extra>",
)
if ew_v["ts"].max() > now:
    # day-ahead prices for tomorrow are already published
    fig.add_vline(x=now, line_dash="dot", line_color="#898781")
    fig.add_annotation(
        x=now, y=1, yref="paper", text="now", showarrow=False, font=dict(color="#898781")
    )
fig.update_layout(showlegend=False)
fig = styled(fig, "€/MWh")
# negative prices are the interesting event here, make the zero level visible
fig.update_yaxes(zeroline=True, zerolinecolor="#898781", zerolinewidth=1)
st.plotly_chart(fig, width="stretch")

st.subheader("Generation mix")
mix_wide = mix_v.pivot_table(
    index="ts", columns="group", values="generation_mwh", aggfunc="sum"
)
fig = go.Figure()
for group, color in MIX_COLORS.items():
    fig.add_scatter(
        x=mix_wide.index, y=mix_wide[group] / 1000, mode="lines",
        stackgroup="one", name=group,
        line=dict(width=1, color=SURFACE), fillcolor=color,
        hovertemplate="%{y:.1f} GWh<extra>" + group + "</extra>",
    )
st.plotly_chart(styled(fig, "GWh per hour"), width="stretch")
with st.expander("Show as table (daily totals in GWh, complete days only)"):
    # partial days at the window edges would show up as fake generation dips
    hours_per_date = mix_v.groupby(mix_v["ts"].dt.date)["ts"].transform("nunique")
    daily = (
        mix_v[hours_per_date >= 23]  # 23 because of the short DST day
        .assign(date=lambda d: d["ts"].dt.date)
        .pivot_table(index="date", columns="group", values="generation_mwh", aggfunc="sum")
        [list(MIX_COLORS)] / 1000
    )
    st.dataframe(daily.round(1))

left, right = st.columns(2)

with left:
    st.subheader("Wind speed vs. price")
    pts = ew_past.dropna(subset=["wind_speed_ms", "price_eur_mwh"])
    fig = go.Figure()
    fig.add_scatter(
        x=pts["wind_speed_ms"], y=pts["price_eur_mwh"], mode="markers",
        marker=dict(color=BLUE, size=7, opacity=0.35), name="Hourly values",
        hovertemplate="%{x:.1f} m/s, %{y:.2f} €/MWh<extra></extra>",
    )
    if len(pts) > 1:
        slope, intercept = np.polyfit(pts["wind_speed_ms"], pts["price_eur_mwh"], 1)
        xs = np.array([pts["wind_speed_ms"].min(), pts["wind_speed_ms"].max()])
        fig.add_scatter(
            x=xs, y=slope * xs + intercept, mode="lines",
            line=dict(color=ORANGE, width=2), name=f"Trend: {slope:.1f} €/MWh per m/s",
        )
    fig.update_xaxes(title="Wind speed (m/s, national average)")
    st.plotly_chart(styled(fig, "€/MWh", hovermode="closest"), width="stretch")

with right:
    st.subheader("Correlations")
    corr_cols = {
        "price_eur_mwh": "Price",
        "load_mwh": "Load",
        "wind_mwh": "Wind gen.",
        "solar_mwh": "Solar gen.",
        "wind_speed_ms": "Wind speed",
        "radiation_wm2": "Radiation",
        "temperature_c": "Temperature",
    }
    corr = ew_past[list(corr_cols)].corr().rename(index=corr_cols, columns=corr_cols)
    fig = go.Figure(
        go.Heatmap(
            z=corr.values, x=corr.columns, y=corr.index,
            zmin=-1, zmax=1,
            colorscale=[(0, "#104281"), (0.5, "#f0efec"), (1, "#9e2b2b")],
            colorbar=dict(title="r"),
            hovertemplate="%{y} vs %{x}: r = %{z:.2f}<extra></extra>",
        )
    )
    for i, row in enumerate(corr.index):
        for j, col in enumerate(corr.columns):
            r = corr.iloc[i, j]
            fig.add_annotation(
                x=col, y=row, text=f"{r:.2f}", showarrow=False,
                font=dict(size=11, color="#ffffff" if abs(r) > 0.5 else "#0b0b0b"),
            )
    fig.update_yaxes(autorange="reversed", title=None)
    st.plotly_chart(styled(fig, None, hovermode="closest"), width="stretch")

st.caption(
    f"Last data point: {ew.dropna(subset=['price_eur_mwh'])['ts'].max():%Y-%m-%d %H:%M %Z}. "
    "All times Europe/Berlin. Generation values are hourly energy (MWh)."
)
