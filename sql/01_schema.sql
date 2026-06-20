-- =============================================================================
--  01_schema.sql — Schéma e-commerce (modèle relationnel)
-- =============================================================================
--
--  Modèle volontairement classique (clients → commandes → lignes_commande,
--  produits) pour rester lisible et réaliste.
--
--  POINT CLÉ pour le projet d'optimisation :
--  on ne crée ICI que les CLÉS PRIMAIRES (donc leurs index). Les colonnes de
--  clés étrangères (client_id, commande_id, produit_id) ne sont PAS indexées.
--  PostgreSQL n'indexe jamais automatiquement les colonnes de clés étrangères :
--  c'est exactement ce qui rendra la baseline lente (seq scans, hash joins
--  coûteux, sous-requêtes corrélées en boucle). Les index secondaires seront
--  ajoutés dans 04_optimisations.sql, une fois la baseline mesurée.
--
--  Pour repartir d'une base propre : ce script DROP puis recrée tout.
-- =============================================================================

DROP TABLE IF EXISTS lignes_commande CASCADE;
DROP TABLE IF EXISTS commandes       CASCADE;
DROP TABLE IF EXISTS produits        CASCADE;
DROP TABLE IF EXISTS clients         CASCADE;

-- -----------------------------------------------------------------------------
--  clients : ~100 000 lignes
-- -----------------------------------------------------------------------------
CREATE TABLE clients (
    id               INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    nom              TEXT    NOT NULL,
    prenom           TEXT    NOT NULL,
    email            TEXT    NOT NULL,
    ville            TEXT    NOT NULL,
    code_postal      TEXT    NOT NULL,
    pays             TEXT    NOT NULL DEFAULT 'France',
    segment          TEXT    NOT NULL,           -- 'particulier' | 'pro' | 'vip'
    date_inscription DATE    NOT NULL
);

-- -----------------------------------------------------------------------------
--  produits : ~5 000 lignes
-- -----------------------------------------------------------------------------
CREATE TABLE produits (
    id          INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    nom         TEXT          NOT NULL,
    categorie   TEXT          NOT NULL,          -- 10 catégories
    prix        NUMERIC(10,2) NOT NULL,
    cout        NUMERIC(10,2) NOT NULL,          -- coût d'achat (pour la marge)
    actif       BOOLEAN       NOT NULL DEFAULT TRUE,
    date_ajout  DATE          NOT NULL
);

-- -----------------------------------------------------------------------------
--  commandes : ~250 000 lignes
-- -----------------------------------------------------------------------------
CREATE TABLE commandes (
    id            INTEGER   GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    client_id     INTEGER   NOT NULL REFERENCES clients(id),   -- FK NON indexée
    date_commande TIMESTAMP NOT NULL,
    statut        TEXT      NOT NULL,            -- en_cours|expediee|livree|annulee
    canal         TEXT      NOT NULL             -- web | mobile | magasin
);

-- -----------------------------------------------------------------------------
--  lignes_commande : ~1 000 000 lignes (la grosse table du benchmark)
-- -----------------------------------------------------------------------------
CREATE TABLE lignes_commande (
    id            BIGINT        GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    commande_id   INTEGER       NOT NULL REFERENCES commandes(id),  -- FK NON indexée
    produit_id    INTEGER       NOT NULL REFERENCES produits(id),   -- FK NON indexée
    quantite      INTEGER       NOT NULL,
    prix_unitaire NUMERIC(10,2) NOT NULL,        -- prix au moment de la commande
    remise        NUMERIC(4,3)  NOT NULL DEFAULT 0   -- fraction 0..1 (ex: 0.150 = -15%)
);

-- Récapitulatif des tables créées
\echo '--- Tables créées (sans index secondaires) ---'
