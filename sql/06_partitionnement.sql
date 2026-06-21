-- =============================================================================
--  06_partitionnement.sql — Bonus : partitionnement par plage de dates
-- =============================================================================
--
--  Démonstration AUTONOME (hors benchmark principal) du partitionnement
--  déclaratif PostgreSQL. On construit une copie partitionnée de `commandes`
--  par ANNÉE sur date_commande, puis on observe le "partition pruning" :
--  une requête filtrée sur une période ne lit QUE les partitions concernées.
--
--  Quand partitionner ? Quand une grande table est presque toujours interrogée
--  sur une dimension (souvent temporelle), et que la purge/archivage par
--  période est utile (DROP d'une partition = instantané vs DELETE massif).
-- =============================================================================

\timing on

DROP TABLE IF EXISTS commandes_part CASCADE;

-- Table partitionnée par plage. La colonne de partition doit faire partie
-- de la clé primaire → PK composite (id, date_commande).
CREATE TABLE commandes_part (
    id            INTEGER   NOT NULL,
    client_id     INTEGER   NOT NULL,
    date_commande TIMESTAMP NOT NULL,
    statut        TEXT      NOT NULL,
    canal         TEXT      NOT NULL,
    PRIMARY KEY (id, date_commande)
) PARTITION BY RANGE (date_commande);

-- Une partition par année.
CREATE TABLE commandes_2023 PARTITION OF commandes_part
    FOR VALUES FROM ('2023-01-01') TO ('2024-01-01');
CREATE TABLE commandes_2024 PARTITION OF commandes_part
    FOR VALUES FROM ('2024-01-01') TO ('2025-01-01');
CREATE TABLE commandes_2025 PARTITION OF commandes_part
    FOR VALUES FROM ('2025-01-01') TO ('2026-01-01');
CREATE TABLE commandes_2026 PARTITION OF commandes_part
    FOR VALUES FROM ('2026-01-01') TO ('2027-01-01');

-- Chargement depuis la table d'origine (PostgreSQL route chaque ligne vers
-- la bonne partition automatiquement).
INSERT INTO commandes_part (id, client_id, date_commande, statut, canal)
SELECT id, client_id, date_commande, statut, canal FROM commandes;

ANALYZE commandes_part;

\echo '>>> Répartition des lignes par partition :'
SELECT tableoid::regclass AS partition, count(*)
FROM commandes_part
GROUP BY 1 ORDER BY 1;

-- ---------------------------------------------------------------------------
--  Partition pruning : ce filtre ne doit toucher QUE la partition 2024.
--  Chercher "commandes_2024" dans le plan, et l'absence des autres années.
-- ---------------------------------------------------------------------------
\echo '>>> Plan AVEC partition pruning (seule la partition 2024 est lue) :'
EXPLAIN (ANALYZE, BUFFERS)
SELECT count(*)
FROM commandes_part
WHERE date_commande >= DATE '2024-06-01'
  AND date_commande <  DATE '2024-07-01';

-- Atout opérationnel : archiver une année = détacher/supprimer une partition,
-- opération quasi instantanée (métadonnées) au lieu d'un DELETE de masse.
--   ALTER TABLE commandes_part DETACH PARTITION commandes_2023;
--   DROP TABLE commandes_2023;
