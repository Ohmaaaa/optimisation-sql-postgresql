"""
plots.py — Génération des graphiques avant/après à partir de results/benchmarks.json.

Produit deux figures (échelle logarithmique, car les temps s'étalent de
~0,01 ms à plusieurs secondes) :
  - results/figures/benchmark_avant_apres.png : temps baseline vs optimisé
  - results/figures/acceleration.png          : facteur d'accélération (×)

Usage :
  python benchmark/plots.py
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")  # pas d'affichage interactif : on écrit des fichiers
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "results"
FIGURES = RESULTS / "figures"

# Palette sobre
GRIS = "#8A8A8E"      # "avant"
VERT = "#34C759"      # "après"
BLEU = "#0A84FF"      # accents
TEXTE = "#1D1D1F"


def charger() -> list[dict]:
    data = json.loads((RESULTS / "benchmarks.json").read_text(encoding="utf-8"))
    return data["resultats"]


def _style_axes(ax):
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#D2D2D7")
    ax.spines["bottom"].set_color("#D2D2D7")
    ax.tick_params(colors=TEXTE, labelsize=9)
    ax.set_axisbelow(True)
    ax.grid(axis="y", color="#E5E5EA", linewidth=0.8)


def graphe_avant_apres(resultats: list[dict]) -> Path:
    ids = [r["id"].upper() for r in resultats]
    avant = [r["baseline_ms"] for r in resultats]
    apres = [r["optimise_ms"] for r in resultats]

    x = range(len(ids))
    largeur = 0.38

    fig, ax = plt.subplots(figsize=(11, 5.5), dpi=130)
    b1 = ax.bar([i - largeur / 2 for i in x], avant, largeur,
                label="Avant", color=GRIS)
    b2 = ax.bar([i + largeur / 2 for i in x], apres, largeur,
                label="Après", color=VERT)

    ax.set_yscale("log")
    ax.set_ylabel("Temps d'exécution (ms, échelle log)", color=TEXTE, fontsize=10)
    ax.set_title("Optimisation SQL — temps d'exécution avant / après",
                 color=TEXTE, fontsize=14, fontweight="bold", pad=14)
    ax.set_xticks(list(x))
    ax.set_xticklabels(ids)
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:g}"))
    _style_axes(ax)

    # Annoter le gain au-dessus de chaque paire
    for r, xi, a in zip(resultats, x, avant):
        ax.annotate(f"−{r['gain_pct']:.0f}%",
                    xy=(xi, a), xytext=(0, 6), textcoords="offset points",
                    ha="center", fontsize=8.5, color=BLEU, fontweight="bold")

    ax.legend(frameon=False, fontsize=10, loc="upper right")
    fig.tight_layout()

    FIGURES.mkdir(parents=True, exist_ok=True)
    chemin = FIGURES / "benchmark_avant_apres.png"
    fig.savefig(chemin, bbox_inches="tight")
    plt.close(fig)
    return chemin


def graphe_acceleration(resultats: list[dict]) -> Path:
    # Trié par accélération décroissante
    rs = sorted(resultats, key=lambda r: r["acceleration"], reverse=True)
    labels = [f"{r['id'].upper()}  ·  {r['technique'].split(' (')[0]}" for r in rs]
    accel = [r["acceleration"] for r in rs]

    fig, ax = plt.subplots(figsize=(11, 5.5), dpi=130)
    y = range(len(rs))
    ax.barh(list(y), accel, color=BLEU, height=0.6)
    ax.set_xscale("log")
    ax.set_yticks(list(y))
    ax.set_yticklabels(labels, fontsize=9)
    ax.invert_yaxis()
    ax.set_xlabel("Facteur d'accélération (×, échelle log)", color=TEXTE, fontsize=10)
    ax.set_title("Gain par technique d'optimisation",
                 color=TEXTE, fontsize=14, fontweight="bold", pad=14)
    ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: f"×{v:g}"))

    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#D2D2D7")
    ax.spines["bottom"].set_color("#D2D2D7")
    ax.tick_params(colors=TEXTE)
    ax.set_axisbelow(True)
    ax.grid(axis="x", color="#E5E5EA", linewidth=0.8)

    for yi, a in zip(y, accel):
        ax.annotate(f"×{a:.0f}", xy=(a, yi), xytext=(6, 0),
                    textcoords="offset points", va="center",
                    fontsize=9, color=TEXTE, fontweight="bold")

    fig.tight_layout()
    FIGURES.mkdir(parents=True, exist_ok=True)
    chemin = FIGURES / "acceleration.png"
    fig.savefig(chemin, bbox_inches="tight")
    plt.close(fig)
    return chemin


def main() -> None:
    resultats = charger()
    p1 = graphe_avant_apres(resultats)
    p2 = graphe_acceleration(resultats)
    print(f"→ {p1}")
    print(f"→ {p2}")


if __name__ == "__main__":
    main()
