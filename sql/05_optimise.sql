-- =============================================================================
--  05_optimise.sql — Les 7 requêtes APRÈS optimisation
-- =============================================================================
--
--  À exécuter APRÈS 04_optimisations.sql (les index et la vue matérialisée
--  doivent exister). Comparer les plans à ceux de 03_baseline.sql.
--
--  Deux types d'optimisation illustrés :
--    - même requête + index (Q1, Q6, Q7) ;
--    - requête RÉÉCRITE (Q2 corrélée→jointure, Q3 sargable, Q4 NOT EXISTS, Q5 vue).
-- =============================================================================

\timing on

-- -----------------------------------------------------------------------------
--  Q1 — identique, mais les index FK donnent Index Scan + Nested Loop
-- -----------------------------------------------------------------------------
EXPLAIN (ANALYZE, BUFFERS)
SELECT co.id,
       sum(lc.quantite * lc.prix_unitaire * (1 - lc.remise)) AS montant
FROM commandes co
JOIN lignes_commande lc ON lc.commande_id = co.id
WHERE co.client_id = 12345
GROUP BY co.id;

-- -----------------------------------------------------------------------------
--  Q2 — RÉÉCRITE : sous-requête corrélée → LEFT JOIN + GROUP BY
--  commandes n'est plus lue qu'une seule fois (Hash Join au lieu de N SubPlans).
-- -----------------------------------------------------------------------------
EXPLAIN (ANALYZE, BUFFERS)
SELECT c.id, c.nom, count(co.id) AS nb_commandes
FROM clients c
LEFT JOIN commandes co ON co.client_id = c.id
WHERE c.segment = 'vip' AND c.ville = 'Paris'
GROUP BY c.id, c.nom;

-- -----------------------------------------------------------------------------
--  Q3 — RÉÉCRITE : prédicat SARGABLE (intervalle sur la colonne brute)
--  → Index Scan sur idx_commandes_date.
-- -----------------------------------------------------------------------------
EXPLAIN (ANALYZE, BUFFERS)
SELECT count(*)
FROM commandes
WHERE date_commande >= DATE '2024-06-01'
  AND date_commande <  DATE '2024-07-01';

-- -----------------------------------------------------------------------------
--  Q4 — RÉÉCRITE : NOT IN → NOT EXISTS (Hash Anti Join + index produit_id)
-- -----------------------------------------------------------------------------
EXPLAIN (ANALYZE, BUFFERS)
SELECT count(*)
FROM produits p
WHERE NOT EXISTS (
    SELECT 1 FROM lignes_commande lc WHERE lc.produit_id = p.id
);

-- -----------------------------------------------------------------------------
--  Q5 — RÉÉCRITE : lecture directe de la vue matérialisée (10 lignes via index)
-- -----------------------------------------------------------------------------
EXPLAIN (ANALYZE, BUFFERS)
SELECT id, nom, ca
FROM mv_ca_produit
ORDER BY ca DESC
LIMIT 10;

-- -----------------------------------------------------------------------------
--  Q6 — identique, mais index composite + couvrant → Index Scans ciblés
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
--  Q7 — identique, mais l'index partiel cible directement les annulées
-- -----------------------------------------------------------------------------
EXPLAIN (ANALYZE, BUFFERS)
SELECT date_trunc('month', date_commande) AS mois, count(*) AS nb
FROM commandes
WHERE statut = 'annulee'
GROUP BY 1
ORDER BY 1;
