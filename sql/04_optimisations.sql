-- =============================================================================
--  04_optimisations.sql — Catalogue des optimisations (index, vues mat.)
-- =============================================================================
--
--  Regroupe TOUS les objets créés pour accélérer les requêtes de 03_baseline.sql.
--  Chaque bloc rappelle la technique et la requête concernée.
--
--  /!\ Le benchmark (bench.py) crée et supprime ces objets UN PAR UN pour
--  mesurer chaque technique isolément. Ce script-ci les crée tous d'un coup,
--  pour explorer la base « optimisée » à la main puis lancer 05_optimise.sql.
--
--  Penser à ANALYZE après création pour des statistiques à jour.
-- =============================================================================

-- -----------------------------------------------------------------------------
--  Q1 — Index B-tree sur les clés étrangères
--  Transforme le Seq Scan en Index Scan, et le Hash Join en Nested Loop ciblé.
-- -----------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_commandes_client_id ON commandes(client_id);
CREATE INDEX IF NOT EXISTS idx_lignes_commande_id  ON lignes_commande(commande_id);

-- -----------------------------------------------------------------------------
--  Q3 — Index B-tree sur la date (exploité une fois le prédicat rendu sargable)
--  Voir 05_optimise.sql : EXTRACT(...) réécrit en intervalle [début, fin).
-- -----------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_commandes_date ON commandes(date_commande);

-- -----------------------------------------------------------------------------
--  Q4 — Index sur produit_id (sert l'anti-jointure du NOT EXISTS)
-- -----------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_lignes_produit_id ON lignes_commande(produit_id);

-- -----------------------------------------------------------------------------
--  Q5 — Vue matérialisée : pré-agrégation du CA par produit
--  La requête de classement se réduit alors à lire 10 lignes via l'index ca DESC.
--  (À rafraîchir après un nouveau chargement : REFRESH MATERIALIZED VIEW mv_ca_produit;)
-- -----------------------------------------------------------------------------
DROP MATERIALIZED VIEW IF EXISTS mv_ca_produit;
CREATE MATERIALIZED VIEW mv_ca_produit AS
SELECT p.id, p.nom,
       sum(lc.quantite * lc.prix_unitaire * (1 - lc.remise)) AS ca
FROM lignes_commande lc
JOIN produits p ON p.id = lc.produit_id
GROUP BY p.id, p.nom;
CREATE INDEX IF NOT EXISTS idx_mv_ca_produit_ca ON mv_ca_produit(ca DESC);

-- -----------------------------------------------------------------------------
--  Q6 — Index composite (filtres) + index COUVRANT (INCLUDE)
--  - filtre catégorie et filtre date servis par des index dédiés ;
--  - l'index couvrant porte les colonnes du calcul du CA → la jointure et
--    l'agrégat sont servis sans retour à la table (pas de heap fetch).
-- -----------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_produits_categorie ON produits(categorie);
-- idx_commandes_date est déjà créé plus haut (réutilisé ici).
CREATE INDEX IF NOT EXISTS idx_lignes_couvrant
    ON lignes_commande(commande_id)
    INCLUDE (produit_id, quantite, prix_unitaire, remise);

-- -----------------------------------------------------------------------------
--  Q7 — Index PARTIEL : ne contient que les commandes annulées (~5 %)
--  Index minuscule, ciblant directement le sous-ensemble interrogé.
-- -----------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_commandes_annulee
    ON commandes(date_commande)
    WHERE statut = 'annulee';

-- Statistiques à jour après création des objets.
ANALYZE;

\echo '>>> Optimisations appliquées. Index présents :'
SELECT indexname FROM pg_indexes
WHERE schemaname = 'public' AND indexname LIKE 'idx_%'
ORDER BY indexname;
