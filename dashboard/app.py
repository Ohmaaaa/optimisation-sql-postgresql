"""
app.py — Dashboard Streamlit du projet d'optimisation SQL.

Deux onglets :
  - ⚡ Optimiseur : l'utilisateur colle une requête SELECT, l'app la mesure,
    détecte les pistes d'optimisation et TESTE réellement un index (transaction
    annulée ensuite) pour chiffrer le gain sur SA requête.
  - 📊 Benchmark : les 7 cas pré-mesurés (lecture de results/benchmarks.json).

La connexion à PostgreSQL est résolue dans l'ordre :
  1. st.secrets["DATABASE_URL"]   (déploiement Streamlit Cloud → base Neon)
  2. variable d'environnement DATABASE_URL
  3. variables PG* d'un fichier .env  (développement local)

Lancement : streamlit run dashboard/app.py
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pandas as pd
import psycopg
import streamlit as st
from dotenv import load_dotenv

import optimizer  # module local (même dossier)

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "results"
PLANS = RESULTS / "plans"
FIGURES = RESULTS / "figures"

st.set_page_config(page_title="Optimisation SQL — PostgreSQL",
                   page_icon="⚡", layout="wide")


# ===========================================================================
#  Connexion à la base
# ===========================================================================
def _resolve_conninfo() -> str | None:
    try:
        if "DATABASE_URL" in st.secrets:
            return st.secrets["DATABASE_URL"]
    except Exception:
        pass
    if os.getenv("DATABASE_URL"):
        return os.getenv("DATABASE_URL")
    load_dotenv(ROOT / ".env")
    host = os.getenv("PGHOST")
    if host:
        return (f"host={host} port={os.getenv('PGPORT', '5432')} "
                f"dbname={os.getenv('PGDATABASE', 'ecommerce')} "
                f"user={os.getenv('PGUSER', 'postgres')} "
                f"password={os.getenv('PGPASSWORD', '')}")
    return None


@st.cache_resource(show_spinner=False)
def _connect(conninfo: str) -> psycopg.Connection:
    conn = psycopg.connect(conninfo, connect_timeout=10)
    conn.autocommit = True
    return conn


def get_connection() -> tuple[psycopg.Connection | None, str | None]:
    conninfo = _resolve_conninfo()
    if not conninfo:
        return None, "Aucune base de données configurée."
    try:
        conn = _connect(conninfo)
        if conn.closed:
            _connect.clear()
            conn = _connect(conninfo)
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
        return conn, None
    except Exception as exc:
        _connect.clear()
        return None, str(exc)


# ===========================================================================
#  Données du benchmark
# ===========================================================================
@st.cache_data
def charger_benchmarks() -> dict:
    f = RESULTS / "benchmarks.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}


def lire_plan(nom: str) -> str:
    f = PLANS / nom
    return f.read_text(encoding="utf-8") if f.exists() else "(plan non disponible)"


# ===========================================================================
#  Onglet 1 — Optimiseur interactif
# ===========================================================================
EXEMPLES = {
    "Filtre sur clé étrangère (index manquant)":
        "SELECT count(*)\nFROM commandes\nWHERE client_id = 500",
    "Grosse table + SELECT *":
        "SELECT *\nFROM lignes_commande\nWHERE produit_id = 42",
    "Anti-pattern NOT IN":
        "SELECT count(*)\nFROM produits\nWHERE id NOT IN (SELECT produit_id FROM lignes_commande)",
    "Prédicat non-sargable (EXTRACT)":
        "SELECT count(*)\nFROM commandes\nWHERE EXTRACT(YEAR FROM date_commande) = 2024",
}


def page_optimiseur() -> None:
    st.subheader("⚡ Optimiseur de requête")
    st.markdown(
        "Colle une requête **SELECT** sur la base e-commerce "
        "(`clients`, `produits`, `commandes`, `lignes_commande`). "
        "L'outil mesure son temps, lit son plan, détecte les pistes "
        "d'optimisation et **teste réellement un index** pour chiffrer le gain."
    )

    conn, err = get_connection()
    if conn is None:
        st.warning(
            "🔌 L'optimiseur a besoin d'une connexion PostgreSQL.\n\n"
            "- **En local** : copie `.env.example` en `.env` et lance la base "
            "(voir le README).\n"
            "- **En ligne** : la base Neon doit être configurée dans les *secrets*.\n\n"
            f"_Détail technique : {err}_"
        )
        return

    if "requete_sql" not in st.session_state:
        st.session_state.requete_sql = list(EXEMPLES.values())[0]

    st.caption("Exemples (clique pour charger) :")
    cols = st.columns(len(EXEMPLES))
    for col, (label, req) in zip(cols, EXEMPLES.items()):
        if col.button(label, use_container_width=True):
            st.session_state.requete_sql = req

    requete = st.text_area("Requête SQL", key="requete_sql", height=160)
    lancer = st.button("Analyser & optimiser", type="primary")

    if not lancer:
        return

    try:
        with st.spinner("Mesure du plan et test des index…"):
            rapport = optimizer.analyser(conn, requete)
    except optimizer.RequeteInvalide as e:
        st.error(f"Requête refusée : {e}")
        return
    except Exception as e:  # erreur SQL, timeout…
        st.error(f"Erreur à l'exécution : {e}")
        return

    # Verdict + temps de référence
    st.divider()
    if rapport["pistes"]:
        st.success(f"✅ {rapport['verdict']}")
    else:
        st.info(f"ℹ️ {rapport['verdict']}")
    st.metric("Temps de référence (baseline)", f"{rapport['base_ms']:.3f} ms")

    # Pistes mesurées (index)
    if rapport["pistes"]:
        st.markdown("#### Index testés (gain réel mesuré sur ta requête)")
        for p in rapport["pistes"]:
            with st.container(border=True):
                st.markdown(f"**Index sur `{p['relation']}({p['colonne']})`**")
                m1, m2, m3 = st.columns(3)
                m1.metric("Avant", f"{rapport['base_ms']:.3f} ms")
                m2.metric("Après", f"{p['opt_ms']:.3f} ms")
                m3.metric("Gain", f"{p['gain_pct']:.1f} %", f"×{p['acceleration']:.0f}")
                st.code(p["ddl"], language="sql")

    # Conseils (réécritures)
    if rapport["conseils"]:
        st.markdown("#### Réécritures recommandées")
        for c in rapport["conseils"]:
            with st.expander(f"💡 {c['titre']}"):
                st.markdown(c["detail"])

    # Plan baseline
    with st.expander("Voir le plan EXPLAIN ANALYZE (baseline)"):
        st.code(rapport["plan_texte"], language="text")


# ===========================================================================
#  Onglet 2 — Benchmark pré-mesuré
# ===========================================================================
def page_benchmark() -> None:
    data = charger_benchmarks()
    if not data:
        st.warning("Aucun résultat. Lance d'abord :  `python benchmark/bench.py`")
        return

    resultats = data["resultats"]
    df = pd.DataFrame(resultats)

    total_avant = df["baseline_ms"].sum()
    total_apres = df["optimise_ms"].sum()
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Requêtes optimisées", len(df))
    c2.metric("Accélération médiane", f"×{df['acceleration'].median():.0f}")
    c3.metric("Accélération max", f"×{df['acceleration'].max():,.0f}".replace(",", " "))
    c4.metric("Temps cumulé", f"{total_avant/1000:.1f} s → {total_apres:.0f} ms")
    st.caption(f"Benchmark généré le {data.get('genere_le', '?')} (UTC).")
    st.divider()

    st.subheader("Récapitulatif")
    recap = df[["id", "titre", "technique", "baseline_ms", "optimise_ms",
                "gain_pct", "acceleration"]].copy()
    recap.columns = ["#", "Requête", "Technique", "Avant (ms)", "Après (ms)",
                     "Gain %", "Accél."]
    recap["#"] = recap["#"].str.upper()
    st.dataframe(
        recap, hide_index=True, use_container_width=True,
        column_config={
            "Avant (ms)": st.column_config.NumberColumn(format="%.2f"),
            "Après (ms)": st.column_config.NumberColumn(format="%.3f"),
            "Gain %": st.column_config.NumberColumn(format="%.1f %%"),
            "Accél.": st.column_config.NumberColumn(format="×%.1f"),
        },
    )

    g1, g2 = st.columns(2)
    with g1:
        st.subheader("Temps avant / après")
        cd = df.set_index("id")[["baseline_ms", "optimise_ms"]]
        cd.columns = ["Avant", "Après"]
        st.bar_chart(cd, color=["#8A8A8E", "#34C759"])
    with g2:
        st.subheader("Facteur d'accélération")
        ad = df.set_index("id")[["acceleration"]]
        ad.columns = ["Accélération (×)"]
        st.bar_chart(ad, color="#0A84FF")

    fig1 = FIGURES / "benchmark_avant_apres.png"
    if fig1.exists():
        with st.expander("Figures haute résolution (échelle log)"):
            st.image(str(fig1), use_container_width=True)
            fig2 = FIGURES / "acceleration.png"
            if fig2.exists():
                st.image(str(fig2), use_container_width=True)

    st.divider()
    st.subheader("Détail par requête")
    for r in resultats:
        with st.expander(f"{r['id'].upper()} — {r['titre']}  ·  ×{r['acceleration']:.0f}"):
            st.markdown(f"**Technique :** {r['technique']}")
            st.markdown(f"**Problème.** {r['probleme']}")
            st.markdown(f"**Diagnostic.** {r['diagnostic']}")
            m1, m2, m3 = st.columns(3)
            m1.metric("Avant", f"{r['baseline_ms']:.2f} ms")
            m2.metric("Après", f"{r['optimise_ms']:.3f} ms")
            m3.metric("Gain", f"{r['gain_pct']:.1f} %", f"×{r['acceleration']:.0f}")
            if r["setup"]:
                st.code(";\n".join(s.strip() for s in r["setup"]) + ";", language="sql")
            t1, t2 = st.tabs(["Plan baseline", "Plan optimisé"])
            t1.code(lire_plan(f"{r['id']}_baseline.txt"), language="text")
            t2.code(lire_plan(f"{r['id']}_optimise.txt"), language="text")


# ===========================================================================
#  Mise en page
# ===========================================================================
st.title("⚡ Optimisation de requêtes SQL — PostgreSQL")
st.caption("Projet portfolio data engineering — Nael Benchalal · "
           "base e-commerce de ~1,35 M de lignes.")

onglet_opt, onglet_bench = st.tabs(["⚡ Optimiseur interactif", "📊 Benchmark (7 cas)"])
with onglet_opt:
    page_optimiseur()
with onglet_bench:
    page_benchmark()
