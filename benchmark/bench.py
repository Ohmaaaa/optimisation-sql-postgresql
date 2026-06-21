"""
bench.py — Orchestrateur du benchmark avant/après.

Pour chaque cas défini dans queries.py :
  1. on remet la base à l'état "baseline" (suppression de tous les index idx_*
     et vues mv_* créés précédemment) → mesure honnête, sans interférence ;
  2. on mesure la requête baseline (warmup + N exécutions, médiane) ;
  3. on applique le DDL d'optimisation (index, vue matérialisée) ;
  4. on mesure la requête optimisée ;
  5. on calcule le gain et on archive les plans EXPLAIN ANALYZE.

Sorties :
  - results/benchmarks.json     (toutes les mesures, pour les graphes / le dashboard)
  - results/plans/qN_*.txt       (plans EXPLAIN ANALYZE baseline & optimisé)

Usage :
  python benchmark/bench.py [--runs N]
"""
from __future__ import annotations

import argparse
import json
import textwrap
from datetime import datetime, timezone
from pathlib import Path

from tabulate import tabulate

import db
from queries import QUERIES

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "results"
PLANS = RESULTS / "plans"


def reset_baseline(cur) -> None:
    """Supprime tous les objets d'optimisation pour repartir d'une base nue."""
    cur.execute("SELECT matviewname FROM pg_matviews "
                "WHERE schemaname = 'public' AND matviewname LIKE 'mv_%'")
    for (name,) in cur.fetchall():
        cur.execute(f'DROP MATERIALIZED VIEW IF EXISTS "{name}" CASCADE')

    cur.execute("SELECT indexname FROM pg_indexes "
                "WHERE schemaname = 'public' AND indexname LIKE 'idx_%'")
    for (name,) in cur.fetchall():
        cur.execute(f'DROP INDEX IF EXISTS "{name}"')


def run(runs: int) -> list[dict]:
    resultats: list[dict] = []
    PLANS.mkdir(parents=True, exist_ok=True)

    with db.connect() as conn, conn.cursor() as cur:
        for q in QUERIES:
            print(f"\n=== {q['id'].upper()} — {q['titre']} ===")

            # 1) État baseline propre + statistiques à jour
            reset_baseline(cur)
            cur.execute("ANALYZE")

            # 2) Mesure baseline
            base = db.mesurer(cur, q["baseline"], runs=runs)
            base_plan = db.explain_text(cur, q["baseline"])
            print(f"  baseline  : {base['exec_ms_median']:>10.3f} ms (médiane)")

            # 3) Application des optimisations
            for ddl in q["setup"]:
                cur.execute(ddl)
            cur.execute("ANALYZE")

            # 4) Mesure optimisée
            opt = db.mesurer(cur, q["optimise"], runs=runs)
            opt_plan = db.explain_text(cur, q["optimise"])
            print(f"  optimisé  : {opt['exec_ms_median']:>10.3f} ms (médiane)")

            # 5) Gain + archivage
            b, o = base["exec_ms_median"], opt["exec_ms_median"]
            gain_pct = 100.0 * (b - o) / b if b else 0.0
            acceleration = b / o if o else float("inf")
            print(f"  gain      : {gain_pct:>10.1f} %   (×{acceleration:.1f})")

            (PLANS / f"{q['id']}_baseline.txt").write_text(base_plan, encoding="utf-8")
            (PLANS / f"{q['id']}_optimise.txt").write_text(opt_plan, encoding="utf-8")

            reset_baseline(cur)  # on nettoie pour le cas suivant

            resultats.append({
                "id": q["id"],
                "titre": q["titre"],
                "technique": q["technique"],
                "probleme": q["probleme"],
                "diagnostic": q["diagnostic"],
                "setup": q["setup"],
                "baseline_ms": b,
                "optimise_ms": o,
                "gain_pct": round(gain_pct, 1),
                "acceleration": round(acceleration, 1),
                "baseline_detail": base,
                "optimise_detail": opt,
            })

    return resultats


def sauvegarder(resultats: list[dict]) -> None:
    RESULTS.mkdir(parents=True, exist_ok=True)
    payload = {
        "genere_le": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "resultats": resultats,
    }
    (RESULTS / "benchmarks.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # Tableau récapitulatif lisible (console + utile pour le README)
    table = [[
        r["id"].upper(),
        textwrap.shorten(r["technique"], 38),
        f"{r['baseline_ms']:.2f}",
        f"{r['optimise_ms']:.2f}",
        f"{r['gain_pct']:.1f} %",
        f"×{r['acceleration']:.1f}",
    ] for r in resultats]
    print("\n" + tabulate(
        table,
        headers=["#", "Technique", "Avant (ms)", "Après (ms)", "Gain", "Accél."],
        tablefmt="github",
    ))
    print(f"\n→ Résultats écrits dans {RESULTS / 'benchmarks.json'}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark d'optimisation SQL")
    parser.add_argument("--runs", type=int, default=5,
                        help="Nombre d'exécutions mesurées par requête (défaut : 5)")
    args = parser.parse_args()

    resultats = run(args.runs)
    sauvegarder(resultats)


if __name__ == "__main__":
    main()
