"""
db.py — Connexion PostgreSQL et primitives de mesure.

La mesure s'appuie sur `EXPLAIN (ANALYZE, FORMAT JSON)` : on récupère ainsi le
temps d'exécution mesuré CÔTÉ SERVEUR ("Execution Time"), indépendant de la
latence réseau et du temps de transfert des résultats — c'est la métrique
pertinente pour comparer deux plans.
"""
from __future__ import annotations

import os
import statistics
from pathlib import Path

import psycopg
from dotenv import load_dotenv

# Charge le .env situé à la racine du projet (PGHOST, PGUSER, ...).
load_dotenv(Path(__file__).resolve().parent.parent / ".env")


def get_conninfo() -> str:
    """Construit la chaîne de connexion libpq depuis les variables d'environnement."""
    return (
        f"host={os.getenv('PGHOST', 'localhost')} "
        f"port={os.getenv('PGPORT', '5432')} "
        f"dbname={os.getenv('PGDATABASE', 'ecommerce')} "
        f"user={os.getenv('PGUSER', 'postgres')} "
        f"password={os.getenv('PGPASSWORD', 'postgres')}"
    )


def connect() -> psycopg.Connection:
    """Ouvre une connexion (autocommit pour enchaîner DDL et mesures simplement)."""
    conn = psycopg.connect(get_conninfo())
    conn.autocommit = True
    return conn


def _explain_json(cur: psycopg.Cursor, sql: str) -> tuple[float, float]:
    """Exécute la requête sous EXPLAIN ANALYZE et renvoie (exec_ms, planning_ms)."""
    cur.execute("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + sql)
    plan = cur.fetchone()[0][0]            # psycopg renvoie déjà du JSON désérialisé
    return plan["Execution Time"], plan["Planning Time"]


def explain_text(cur: psycopg.Cursor, sql: str) -> str:
    """Renvoie le plan EXPLAIN ANALYZE au format texte (pour archivage/lecture)."""
    cur.execute("EXPLAIN (ANALYZE, BUFFERS, VERBOSE) " + sql)
    return "\n".join(row[0] for row in cur.fetchall())


def mesurer(cur: psycopg.Cursor, sql: str, runs: int = 5, warmup: int = 1) -> dict:
    """
    Mesure le temps d'exécution d'une requête sur plusieurs exécutions.

    - `warmup` exécutions ignorées (remplissage du cache / des buffers),
    - `runs` exécutions mesurées dont on garde la MÉDIANE (robuste aux pics).
    """
    for _ in range(warmup):
        _explain_json(cur, sql)

    execs: list[float] = []
    plannings: list[float] = []
    for _ in range(runs):
        e, p = _explain_json(cur, sql)
        execs.append(e)
        plannings.append(p)

    return {
        "exec_ms_median": round(statistics.median(execs), 3),
        "exec_ms_min": round(min(execs), 3),
        "exec_ms_max": round(max(execs), 3),
        "planning_ms_median": round(statistics.median(plannings), 3),
        "runs": runs,
        "exec_ms_all": [round(x, 3) for x in execs],
    }
