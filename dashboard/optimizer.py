"""
optimizer.py — Moteur d'optimisation interactif.

Reçoit une requête SELECT arbitraire et :
  1. la valide (lecture seule, une seule instruction) ;
  2. la mesure (EXPLAIN ANALYZE, médiane) et récupère son plan ;
  3. détecte les pistes d'optimisation :
       - INDEX (mesuré) : un Seq Scan filtré sur une colonne non indexée → on
         CRÉE réellement l'index dans une transaction ANNULÉE ensuite, on
         re-mesure, et on rapporte le gain réel sur LA requête de l'utilisateur ;
       - CONSEILS (détectés) : NOT IN, prédicat non-sargable, sous-requête
         corrélée, SELECT * → explication + reformulation recommandée.

Fonctions pures (prennent une connexion psycopg) → réutilisables et testables
hors Streamlit.
"""
from __future__ import annotations

import re
import statistics

import psycopg
from psycopg import sql

RUNS = 3                 # exécutions mesurées (médiane)
MAX_CANDIDATS = 3        # nb max d'index testés (borne le temps de réponse)


class RequeteInvalide(Exception):
    """Requête rejetée par la validation de sécurité."""


# ---------------------------------------------------------------------------
#  Sécurité : on n'autorise QU'UNE requête de lecture
# ---------------------------------------------------------------------------
_MOTS_INTERDITS = (
    "insert", "update", "delete", "drop", "alter", "create", "truncate",
    "grant", "revoke", "copy", "merge", "call", "do", "vacuum", "reindex",
)


def valider_requete(brut: str) -> str:
    """Renvoie la requête nettoyée ou lève RequeteInvalide."""
    q = (brut or "").strip().rstrip(";").strip()
    if not q:
        raise RequeteInvalide("Requête vide.")
    if ";" in q:
        raise RequeteInvalide("Une seule requête à la fois (pas de « ; » multiples).")
    bas = q.lower()
    if not (bas.startswith("select") or bas.startswith("with")):
        raise RequeteInvalide("Seules les requêtes SELECT (ou WITH … SELECT) sont autorisées.")
    # mots-clés d'écriture détectés comme tokens entiers
    tokens = set(re.findall(r"[a-z_]+", bas))
    interdits = tokens.intersection(_MOTS_INTERDITS)
    if interdits:
        raise RequeteInvalide(f"Mot-clé non autorisé : {', '.join(sorted(interdits))}.")
    return q


# ---------------------------------------------------------------------------
#  Mesure
# ---------------------------------------------------------------------------
def _mesurer(cur: psycopg.Cursor, q: str, runs: int = RUNS) -> tuple[float, dict]:
    temps, plan = [], None
    for _ in range(runs):
        cur.execute("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + q)
        plan = cur.fetchone()[0][0]
        temps.append(plan["Execution Time"])
    return round(statistics.median(temps), 3), plan


def _plan_texte(cur: psycopg.Cursor, q: str) -> str:
    cur.execute("EXPLAIN (ANALYZE, BUFFERS) " + q)
    return "\n".join(r[0] for r in cur.fetchall())


# ---------------------------------------------------------------------------
#  Analyse du plan : détection des Seq Scans filtrés
# ---------------------------------------------------------------------------
def _parcourir(noeud: dict):
    yield noeud
    for sous in noeud.get("Plans", []):
        yield from _parcourir(sous)


def _colonnes_du_filtre(filtre: str) -> list[str]:
    """Extrait les colonnes comparées (égalité d'abord, puis intervalles)."""
    egalites, intervalles = [], []
    for m in re.finditer(r"\(?([a-z_][a-z0-9_]*)\)?\s*(=|>=|<=|>|<)\s*", filtre):
        col, op = m.group(1), m.group(2)
        if col.lower() in ("any", "all", "null"):
            continue
        (egalites if op == "=" else intervalles).append(col)
    ordonne = egalites + intervalles
    vus: list[str] = []
    for c in ordonne:
        if c not in vus:
            vus.append(c)
    return vus


def _colonne_indexable(cur, relation: str, colonne: str) -> bool:
    """La colonne existe-t-elle et n'est-elle pas déjà en tête d'un index ?"""
    cur.execute(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_schema='public' AND table_name=%s AND column_name=%s",
        (relation, colonne),
    )
    if cur.fetchone() is None:
        return False
    cur.execute(
        """
        SELECT 1
        FROM pg_index i
        JOIN pg_class t      ON t.oid = i.indrelid
        JOIN pg_attribute a  ON a.attrelid = t.oid AND a.attnum = i.indkey[0]
        WHERE t.relname = %s AND a.attname = %s
        LIMIT 1
        """,
        (relation, colonne),
    )
    return cur.fetchone() is None  # True si AUCUN index en tête sur cette colonne


def _candidats_index(cur, plan: dict) -> list[tuple[str, str]]:
    candidats, vus = [], set()
    for n in _parcourir(plan["Plan"]):
        if "Seq Scan" in n.get("Node Type", "") and n.get("Filter") and n.get("Relation Name"):
            rel = n["Relation Name"]
            for col in _colonnes_du_filtre(n["Filter"]):
                cle = (rel, col)
                if cle in vus:
                    continue
                vus.add(cle)
                if _colonne_indexable(cur, rel, col):
                    candidats.append(cle)
    return candidats[:MAX_CANDIDATS]


def _tester_index(conn: psycopg.Connection, q: str, relation: str, colonne: str) -> tuple[float, dict]:
    """Crée l'index dans une transaction, mesure, puis ANNULE tout (rollback)."""
    capture: dict = {}

    class _Annuler(Exception):
        pass

    try:
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL("CREATE INDEX idx_tmp_optimiseur ON {} ({})").format(
                        sql.Identifier(relation), sql.Identifier(colonne)
                    )
                )
                opt_ms, plan = _mesurer(cur, q)
                capture["opt_ms"], capture["plan"] = opt_ms, plan
            raise _Annuler  # force le ROLLBACK → l'index temporaire disparaît
    except _Annuler:
        pass
    return capture["opt_ms"], capture["plan"]


# ---------------------------------------------------------------------------
#  Détections textuelles (conseils non mesurés)
# ---------------------------------------------------------------------------
def _conseils_texte(q: str, plan: dict) -> list[dict]:
    conseils = []
    bas = q.lower()

    if re.search(r"\bnot\s+in\s*\(\s*select", bas):
        conseils.append({
            "type": "NOT IN",
            "titre": "Remplacer `NOT IN (SELECT …)` par `NOT EXISTS (…)`",
            "detail": "`NOT IN` empêche une anti-jointure efficace et se comporte mal "
                      "avec les valeurs NULL. `NOT EXISTS` permet un *Hash Anti Join* "
                      "et reste correct face aux NULL.",
        })

    if re.search(r"(extract|date_part)\s*\(", bas) or re.search(r"\b\w+\s*::\s*date\b", bas) \
            or re.search(r"\b(lower|upper)\s*\(\s*\w+\s*\)", bas):
        conseils.append({
            "type": "Prédicat non-sargable",
            "titre": "Éviter d'appliquer une fonction à une colonne filtrée",
            "detail": "Un filtre comme `EXTRACT(YEAR FROM d) = 2024` ou `col::date = …` "
                      "interdit l'usage d'un index. Réécris-le en intervalle sur la "
                      "colonne brute : `d >= '2024-01-01' AND d < '2025-01-01'` "
                      "(ou crée un index d'expression).",
        })

    # sous-requête corrélée : repérée via un SubPlan répété dans le plan.
    # On l'ignore si un IN/NOT IN est présent (son SubPlan répété relève d'un
    # autre diagnostic, déjà couvert par le conseil NOT IN ci-dessus).
    a_in_subquery = bool(re.search(r"\bin\s*\(\s*select", bas))
    for n in (() if a_in_subquery else _parcourir(plan["Plan"])):
        if n.get("Parent Relationship") == "SubPlan" and (n.get("Actual Loops", 1) or 1) > 1:
            conseils.append({
                "type": "Sous-requête corrélée",
                "titre": "Décorréler la sous-requête en jointure + agrégat",
                "detail": f"Une sous-requête est ré-exécutée {n.get('Actual Loops')} fois "
                          "(une par ligne externe). Une réécriture en `JOIN … GROUP BY` "
                          "ne lit la table qu'une seule fois.",
            })
            break

    if re.search(r"select\s+\*", bas):
        conseils.append({
            "type": "SELECT *",
            "titre": "Sélectionner uniquement les colonnes nécessaires",
            "detail": "`SELECT *` empêche les *index couvrants* et transfère des données "
                      "inutiles. Liste explicitement les colonnes utiles.",
        })

    return conseils


# ---------------------------------------------------------------------------
#  Point d'entrée
# ---------------------------------------------------------------------------
def analyser(conn: psycopg.Connection, requete_brute: str) -> dict:
    """Analyse complète : renvoie un rapport prêt à afficher."""
    q = valider_requete(requete_brute)

    with conn.cursor() as cur:
        cur.execute("SET statement_timeout = '8s'")
        base_ms, plan = _mesurer(cur, q)
        plan_txt = _plan_texte(cur, q)
        candidats = _candidats_index(cur, plan)

    pistes = []
    for rel, col in candidats:
        opt_ms, _ = _tester_index(conn, q, rel, col)
        gain = 100.0 * (base_ms - opt_ms) / base_ms if base_ms else 0.0
        pistes.append({
            "type": "index",
            "relation": rel,
            "colonne": col,
            "ddl": f"CREATE INDEX idx_{rel}_{col} ON {rel}({col});",
            "opt_ms": opt_ms,
            "gain_pct": round(gain, 1),
            "acceleration": round(base_ms / opt_ms, 1) if opt_ms else None,
        })

    # on ne garde que les index réellement utiles (> 10 % de gain)
    pistes_utiles = [p for p in pistes if p["gain_pct"] > 10]
    conseils = _conseils_texte(q, plan)

    if pistes_utiles:
        meilleur = max(pistes_utiles, key=lambda p: p["gain_pct"])
        verdict = (f"Index sur `{meilleur['relation']}({meilleur['colonne']})` : "
                   f"−{meilleur['gain_pct']:.0f} % (×{meilleur['acceleration']:.0f}).")
    elif conseils:
        verdict = "Pas d'index évident à ajouter, mais des réécritures sont recommandées."
    else:
        verdict = "Requête déjà efficace : aucun Seq Scan filtré ni anti-pattern détecté."

    return {
        "requete": q,
        "base_ms": base_ms,
        "plan_texte": plan_txt,
        "pistes": pistes_utiles,
        "conseils": conseils,
        "verdict": verdict,
    }
