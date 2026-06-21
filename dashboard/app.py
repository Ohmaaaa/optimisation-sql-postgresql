"""
app.py — Dashboard Streamlit des benchmarks d'optimisation SQL.

Lit results/benchmarks.json (généré par benchmark/bench.py) et présente les
résultats de façon interactive : KPI, tableau, graphe avant/après et détail
par requête (problème, diagnostic, technique, plans EXPLAIN ANALYZE).

Lancement :
    streamlit run dashboard/app.py
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "results"
PLANS = RESULTS / "plans"
FIGURES = RESULTS / "figures"

st.set_page_config(page_title="Optimisation SQL — Benchmarks",
                   page_icon="⚡", layout="wide")


@st.cache_data
def charger() -> dict:
    chemin = RESULTS / "benchmarks.json"
    if not chemin.exists():
        return {}
    return json.loads(chemin.read_text(encoding="utf-8"))


def lire_plan(nom: str) -> str:
    f = PLANS / nom
    return f.read_text(encoding="utf-8") if f.exists() else "(plan non disponible)"


data = charger()

st.title("⚡ Optimisation de requêtes SQL — PostgreSQL")
st.caption("Mesures avant / après reproductibles sur une base e-commerce de ~1,35 M de lignes. "
           "Projet portfolio data engineering — Nael Benchalal.")

if not data:
    st.warning("Aucun résultat trouvé. Lance d'abord :  `python benchmark/bench.py`")
    st.stop()

resultats = data["resultats"]
df = pd.DataFrame(resultats)

# --- KPI -------------------------------------------------------------------
total_avant = df["baseline_ms"].sum()
total_apres = df["optimise_ms"].sum()
accel_max = df["acceleration"].max()
accel_med = df["acceleration"].median()

c1, c2, c3, c4 = st.columns(4)
c1.metric("Requêtes optimisées", len(df))
c2.metric("Accélération médiane", f"×{accel_med:.0f}")
c3.metric("Accélération max", f"×{accel_max:,.0f}".replace(",", " "))
c4.metric("Temps cumulé", f"{total_avant/1000:.1f} s → {total_apres:.0f} ms")

st.caption(f"Benchmark généré le {data.get('genere_le', '?')} (UTC).")
st.divider()

# --- Tableau récapitulatif -------------------------------------------------
st.subheader("Récapitulatif")
recap = df[["id", "titre", "technique", "baseline_ms", "optimise_ms",
            "gain_pct", "acceleration"]].copy()
recap.columns = ["#", "Requête", "Technique", "Avant (ms)", "Après (ms)",
                 "Gain %", "Accél."]
recap["#"] = recap["#"].str.upper()
st.dataframe(
    recap,
    hide_index=True,
    use_container_width=True,
    column_config={
        "Avant (ms)": st.column_config.NumberColumn(format="%.2f"),
        "Après (ms)": st.column_config.NumberColumn(format="%.3f"),
        "Gain %": st.column_config.NumberColumn(format="%.1f %%"),
        "Accél.": st.column_config.NumberColumn(format="×%.1f"),
    },
)

# --- Graphes ---------------------------------------------------------------
col_g1, col_g2 = st.columns(2)
with col_g1:
    st.subheader("Temps avant / après")
    chart_df = df.set_index("id")[["baseline_ms", "optimise_ms"]]
    chart_df.columns = ["Avant", "Après"]
    st.bar_chart(chart_df, color=["#8A8A8E", "#34C759"])
    st.caption("Astuce : les écarts sont énormes — voir l'échelle log dans le PNG du repo.")
with col_g2:
    st.subheader("Facteur d'accélération")
    accel_df = df.set_index("id")[["acceleration"]]
    accel_df.columns = ["Accélération (×)"]
    st.bar_chart(accel_df, color="#0A84FF")

# Figures haute résolution (échelle log) générées par plots.py
fig1 = FIGURES / "benchmark_avant_apres.png"
if fig1.exists():
    with st.expander("Voir les figures haute résolution (échelle log)"):
        st.image(str(fig1), use_container_width=True)
        fig2 = FIGURES / "acceleration.png"
        if fig2.exists():
            st.image(str(fig2), use_container_width=True)

st.divider()

# --- Détail par requête ----------------------------------------------------
st.subheader("Détail par requête")
for r in resultats:
    titre = f"{r['id'].upper()} — {r['titre']}  ·  ×{r['acceleration']:.0f}"
    with st.expander(titre):
        st.markdown(f"**Technique :** {r['technique']}")
        st.markdown(f"**Problème.** {r['probleme']}")
        st.markdown(f"**Diagnostic.** {r['diagnostic']}")

        m1, m2, m3 = st.columns(3)
        m1.metric("Avant", f"{r['baseline_ms']:.2f} ms")
        m2.metric("Après", f"{r['optimise_ms']:.3f} ms")
        m3.metric("Gain", f"{r['gain_pct']:.1f} %", f"×{r['acceleration']:.0f}")

        if r["setup"]:
            st.markdown("**Optimisation appliquée :**")
            st.code(";\n".join(s.strip() for s in r["setup"]) + ";", language="sql")

        tab1, tab2 = st.tabs(["Plan baseline", "Plan optimisé"])
        tab1.code(lire_plan(f"{r['id']}_baseline.txt"), language="text")
        tab2.code(lire_plan(f"{r['id']}_optimise.txt"), language="text")
