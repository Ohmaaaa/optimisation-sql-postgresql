"""
queries.py — Source de vérité UNIQUE des cas de benchmark.

Chaque cas décrit :
  - id / titre / technique   : métadonnées pour le rapport
  - probleme / diagnostic    : explication pédagogique (reprise dans le README)
  - baseline                 : la requête LENTE de départ
  - optimise                 : la requête APRÈS optimisation (réécriture éventuelle)
  - setup                    : DDL à appliquer pour la version optimisée
                               (index, vue matérialisée...). Tous les objets sont
                               nommés idx_* ou mv_* pour pouvoir être supprimés
                               automatiquement entre deux cas (isolation des mesures).

NB : les scripts SQL 03/04/05 du dossier sql/ reprennent ces mêmes requêtes en
version « lisible à la main » (avec EXPLAIN ANALYZE) ; ce fichier reste la
référence exécutée par le benchmark.
"""

QUERIES = [
    # -------------------------------------------------------------------------
    {
        "id": "q1",
        "titre": "Détail d'un client : clé étrangère non indexée",
        "technique": "Index B-tree sur clé étrangère",
        "probleme": (
            "On récupère les commandes d'un client et leur montant. client_id "
            "n'étant pas indexé, PostgreSQL parcourt TOUTE la table commandes "
            "(Seq Scan) pour n'en garder que quelques lignes."
        ),
        "diagnostic": (
            "Parallel Seq Scan sur commandes (250k lignes lues pour ~2 utiles) "
            "puis Hash Join avec lignes_commande."
        ),
        "baseline": """
            SELECT co.id,
                   sum(lc.quantite * lc.prix_unitaire * (1 - lc.remise)) AS montant
            FROM commandes co
            JOIN lignes_commande lc ON lc.commande_id = co.id
            WHERE co.client_id = 12345
            GROUP BY co.id
        """,
        "optimise": """
            SELECT co.id,
                   sum(lc.quantite * lc.prix_unitaire * (1 - lc.remise)) AS montant
            FROM commandes co
            JOIN lignes_commande lc ON lc.commande_id = co.id
            WHERE co.client_id = 12345
            GROUP BY co.id
        """,
        "setup": [
            "CREATE INDEX idx_commandes_client_id ON commandes(client_id)",
            "CREATE INDEX idx_lignes_commande_id  ON lignes_commande(commande_id)",
        ],
    },
    # -------------------------------------------------------------------------
    {
        "id": "q2",
        "titre": "Nb de commandes par client VIP : sous-requête corrélée",
        "technique": "Réécriture : sous-requête corrélée → jointure + agrégat",
        "probleme": (
            "Pour chaque client VIP de Paris, une sous-requête corrélée recompte "
            "les commandes. La sous-requête est ré-exécutée une fois PAR client → "
            "des centaines de parcours complets de commandes."
        ),
        "diagnostic": (
            "Le plan montre un SubPlan répété (loops = nb de clients) ; coût "
            "quadratique. La réécriture en LEFT JOIN + GROUP BY ne lit commandes "
            "qu'UNE fois (Hash Join)."
        ),
        "baseline": """
            SELECT c.id, c.nom,
                   (SELECT count(*) FROM commandes co WHERE co.client_id = c.id) AS nb_commandes
            FROM clients c
            WHERE c.segment = 'vip' AND c.ville = 'Paris'
        """,
        "optimise": """
            SELECT c.id, c.nom, count(co.id) AS nb_commandes
            FROM clients c
            LEFT JOIN commandes co ON co.client_id = c.id
            WHERE c.segment = 'vip' AND c.ville = 'Paris'
            GROUP BY c.id, c.nom
        """,
        "setup": [
            "CREATE INDEX idx_commandes_client_id ON commandes(client_id)",
        ],
    },
    # -------------------------------------------------------------------------
    {
        "id": "q3",
        "titre": "Commandes d'un mois : prédicat non-sargable",
        "technique": "Prédicat sargable + index B-tree (date)",
        "probleme": (
            "Le filtre EXTRACT(YEAR/MONTH FROM date_commande) applique une "
            "fonction à CHAQUE ligne : aucun index ne peut être utilisé, et le "
            "Seq Scan est obligatoire."
        ),
        "diagnostic": (
            "Réécrit en intervalle [début, fin) sur la colonne brute, le prédicat "
            "devient sargable : l'index B-tree sur date_commande est exploité "
            "(Index Scan sur un sous-ensemble sélectif)."
        ),
        "baseline": """
            SELECT count(*)
            FROM commandes
            WHERE EXTRACT(YEAR  FROM date_commande) = 2024
              AND EXTRACT(MONTH FROM date_commande) = 6
        """,
        "optimise": """
            SELECT count(*)
            FROM commandes
            WHERE date_commande >= DATE '2024-06-01'
              AND date_commande <  DATE '2024-07-01'
        """,
        "setup": [
            "CREATE INDEX idx_commandes_date ON commandes(date_commande)",
        ],
    },
    # -------------------------------------------------------------------------
    {
        "id": "q4",
        "titre": "Produits jamais commandés : NOT IN",
        "technique": "NOT IN → NOT EXISTS (anti-jointure) + index",
        "probleme": (
            "NOT IN (sous-requête sur ~1M lignes) est coûteux et piégeux (gestion "
            "des NULL). Le planificateur ne peut pas en faire une anti-jointure "
            "efficace."
        ),
        "diagnostic": (
            "NOT EXISTS permet une véritable anti-jointure (Hash Anti Join). "
            "Avec un index sur produit_id, la recherche d'existence est immédiate."
        ),
        "baseline": """
            SELECT count(*)
            FROM produits
            WHERE id NOT IN (SELECT produit_id FROM lignes_commande)
        """,
        "optimise": """
            SELECT count(*)
            FROM produits p
            WHERE NOT EXISTS (
                SELECT 1 FROM lignes_commande lc WHERE lc.produit_id = p.id
            )
        """,
        "setup": [
            "CREATE INDEX idx_lignes_produit_id ON lignes_commande(produit_id)",
        ],
    },
    # -------------------------------------------------------------------------
    {
        "id": "q5",
        "titre": "Top 10 produits par chiffre d'affaires : agrégation lourde",
        "technique": "Vue matérialisée (pré-agrégation) + index",
        "probleme": (
            "Le classement recalcule le CA en agrégeant ~1M lignes à CHAQUE appel "
            "(Hash Join + HashAggregate sur toute la table)."
        ),
        "diagnostic": (
            "Une vue matérialisée pré-calcule le CA par produit. La requête se "
            "réduit alors à lire 10 lignes via un index sur ca DESC."
        ),
        "baseline": """
            SELECT p.id, p.nom,
                   sum(lc.quantite * lc.prix_unitaire * (1 - lc.remise)) AS ca
            FROM lignes_commande lc
            JOIN produits p ON p.id = lc.produit_id
            GROUP BY p.id, p.nom
            ORDER BY ca DESC
            LIMIT 10
        """,
        "optimise": """
            SELECT id, nom, ca
            FROM mv_ca_produit
            ORDER BY ca DESC
            LIMIT 10
        """,
        "setup": [
            """CREATE MATERIALIZED VIEW mv_ca_produit AS
               SELECT p.id, p.nom,
                      sum(lc.quantite * lc.prix_unitaire * (1 - lc.remise)) AS ca
               FROM lignes_commande lc
               JOIN produits p ON p.id = lc.produit_id
               GROUP BY p.id, p.nom""",
            "CREATE INDEX idx_mv_ca_produit_ca ON mv_ca_produit(ca DESC)",
        ],
    },
    # -------------------------------------------------------------------------
    {
        "id": "q6",
        "titre": "CA mensuel d'une catégorie sur une période : jointure 3 tables",
        "technique": "Index composite + index couvrant (INCLUDE)",
        "probleme": (
            "Jointure produits × commandes × lignes_commande avec filtres sur la "
            "catégorie et un mois précis. Sans index, PostgreSQL parcourt la "
            "totalité de lignes_commande (~1M) avant de filtrer."
        ),
        "diagnostic": (
            "Index sur produits.categorie et commandes.date_commande pour filtrer "
            "tôt ; index COUVRANT sur lignes_commande(commande_id) INCLUDE(...) "
            "pour servir la jointure et l'agrégat sans retour à la table (heap)."
        ),
        "baseline": """
            SELECT date_trunc('month', co.date_commande) AS mois,
                   sum(lc.quantite * lc.prix_unitaire * (1 - lc.remise)) AS ca
            FROM lignes_commande lc
            JOIN commandes co ON co.id = lc.commande_id
            JOIN produits  p  ON p.id  = lc.produit_id
            WHERE p.categorie = 'Informatique'
              AND co.date_commande >= DATE '2024-06-01'
              AND co.date_commande <  DATE '2024-07-01'
            GROUP BY 1
            ORDER BY 1
        """,
        "optimise": """
            SELECT date_trunc('month', co.date_commande) AS mois,
                   sum(lc.quantite * lc.prix_unitaire * (1 - lc.remise)) AS ca
            FROM lignes_commande lc
            JOIN commandes co ON co.id = lc.commande_id
            JOIN produits  p  ON p.id  = lc.produit_id
            WHERE p.categorie = 'Informatique'
              AND co.date_commande >= DATE '2024-06-01'
              AND co.date_commande <  DATE '2024-07-01'
            GROUP BY 1
            ORDER BY 1
        """,
        "setup": [
            "CREATE INDEX idx_produits_categorie ON produits(categorie)",
            "CREATE INDEX idx_commandes_date ON commandes(date_commande)",
            """CREATE INDEX idx_lignes_couvrant ON lignes_commande(commande_id)
               INCLUDE (produit_id, quantite, prix_unitaire, remise)""",
        ],
    },
    # -------------------------------------------------------------------------
    {
        "id": "q7",
        "titre": "Commandes annulées par mois : sous-ensemble rare",
        "technique": "Index partiel (WHERE statut = 'annulee')",
        "probleme": (
            "Seules ~5 % des commandes sont annulées, mais la requête parcourt "
            "les 250k commandes pour les retrouver (Seq Scan)."
        ),
        "diagnostic": (
            "Un index PARTIEL ne contient que les lignes 'annulee' : il est "
            "minuscule et permet de cibler directement ce sous-ensemble."
        ),
        "baseline": """
            SELECT date_trunc('month', date_commande) AS mois, count(*) AS nb
            FROM commandes
            WHERE statut = 'annulee'
            GROUP BY 1
            ORDER BY 1
        """,
        "optimise": """
            SELECT date_trunc('month', date_commande) AS mois, count(*) AS nb
            FROM commandes
            WHERE statut = 'annulee'
            GROUP BY 1
            ORDER BY 1
        """,
        "setup": [
            """CREATE INDEX idx_commandes_annulee ON commandes(date_commande)
               WHERE statut = 'annulee'""",
        ],
    },
]
