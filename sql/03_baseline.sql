-- =============================================================================
--  03_baseline.sql — Les 7 requêtes analytiques LENTES (état de départ)
-- =============================================================================
--
--  À exécuter après 01_schema.sql + 02_seed.sql, et AVANT toute optimisation
--  (aucun index secondaire ne doit exister). Chaque requête est précédée de son
--  diagnostic et exécutée sous EXPLAIN (ANALYZE, BUFFERS) pour observer le plan.
--
--  Référence des mesures automatisées : benchmark/queries.py + benchmark/bench.py
--  Les plans archivés se trouvent dans results/plans/qN_baseline.txt
-- =============================================================================

\timing on

-- -----------------------------------------------------------------------------
--  Q1 — Détail d'un client (clé étrangère non indexée)
--  Problème : commandes.client_id n'est pas indexé → Seq Scan de toute la table
--  pour ne garder que ~2 commandes.
-- -----------------------------------------------------------------------------
EXPLAIN (ANALYZE, BUFFERS)
SELECT co.id,
       sum(lc.quantite * lc.prix_unitaire * (1 - lc.remise)) AS montant
FROM commandes co
JOIN lignes_commande lc ON lc.commande_id = co.id
WHERE co.client_id = 12345
GROUP BY co.id;

-- -----------------------------------------------------------------------------
--  Q2 — Nb de commandes par client VIP (SOUS-REQUÊTE CORRÉLÉE)
--  Problème : la sous-requête scalaire est ré-exécutée une fois par client
--  (SubPlan, loops = nb de clients) → coût quadratique.
-- -----------------------------------------------------------------------------
EXPLAIN (ANALYZE, BUFFERS)
SELECT c.id, c.nom,
       (SELECT count(*) FROM commandes co WHERE co.client_id = c.id) AS nb_commandes
FROM clients c
WHERE c.segment = 'vip' AND c.ville = 'Paris';

-- -----------------------------------------------------------------------------
--  Q3 — Commandes d'un mois (PRÉDICAT NON-SARGABLE)
--  Problème : EXTRACT(... FROM date_commande) applique une fonction à chaque
--  ligne → aucun index utilisable, Seq Scan obligatoire.
-- -----------------------------------------------------------------------------
EXPLAIN (ANALYZE, BUFFERS)
SELECT count(*)
FROM commandes
WHERE EXTRACT(YEAR  FROM date_commande) = 2024
  AND EXTRACT(MONTH FROM date_commande) = 6;

-- -----------------------------------------------------------------------------
--  Q4 — Produits jamais commandés (NOT IN)
--  Problème : NOT IN sur ~1M lignes, anti-jointure impossible à optimiser,
--  sémantique NULL piégeuse.
-- -----------------------------------------------------------------------------
EXPLAIN (ANALYZE, BUFFERS)
SELECT count(*)
FROM produits
WHERE id NOT IN (SELECT produit_id FROM lignes_commande);

-- -----------------------------------------------------------------------------
--  Q5 — Top 10 produits par chiffre d'affaires (AGRÉGATION LOURDE)
--  Problème : recalcule la somme sur ~1M lignes à chaque appel
--  (Hash Join + HashAggregate complets).
-- -----------------------------------------------------------------------------
EXPLAIN (ANALYZE, BUFFERS)
SELECT p.id, p.nom,
       sum(lc.quantite * lc.prix_unitaire * (1 - lc.remise)) AS ca
FROM lignes_commande lc
JOIN produits p ON p.id = lc.produit_id
GROUP BY p.id, p.nom
ORDER BY ca DESC
LIMIT 10;

-- -----------------------------------------------------------------------------
--  Q6 — CA mensuel d'une catégorie sur un mois (JOINTURE 3 TABLES)
--  Problème : sans index, parcours complet de lignes_commande avant filtrage.
-- -----------------------------------------------------------------------------
EXPLAIN (ANALYZE, BUFFERS)
SELECT date_trunc('month', co.date_commande) AS mois,
       sum(lc.quantite * lc.prix_unitaire * (1 - lc.remise)) AS ca
FROM lignes_commande lc
JOIN commandes co ON co.id = lc.commande_id
JOIN produits  p  ON p.id  = lc.produit_id
WHERE p.categorie = 'Informatique'
  AND co.date_commande >= DATE '2024-06-01'
  AND co.date_commande <  DATE '2024-07-01'
GROUP BY 1
ORDER BY 1;

-- -----------------------------------------------------------------------------
--  Q7 — Commandes annulées par mois (SOUS-ENSEMBLE RARE)
--  Problème : ~5 % des commandes sont annulées mais on parcourt les 250k lignes.
-- -----------------------------------------------------------------------------
EXPLAIN (ANALYZE, BUFFERS)
SELECT date_trunc('month', date_commande) AS mois, count(*) AS nb
FROM commandes
WHERE statut = 'annulee'
GROUP BY 1
ORDER BY 1;
