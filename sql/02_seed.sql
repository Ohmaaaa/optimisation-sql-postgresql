-- =============================================================================
--  02_seed.sql — Génération des données (volumineuse et REPRODUCTIBLE)
-- =============================================================================
--
--  Stratégie : tout est généré côté serveur avec generate_series + random().
--  setseed() fixe la graine du générateur aléatoire pour la session : deux
--  exécutions de ce script produisent EXACTEMENT les mêmes données.
--
--  /!\ PIÈGE POSTGRESQL IMPORTANT (appris à mes dépens) :
--  un random() placé dans une sous-requête NON corrélée — par ex.
--  `... CROSS JOIN LATERAL (SELECT random() AS r) s` — n'est évalué QU'UNE
--  SEULE FOIS pour toute la requête : toutes les lignes reçoivent alors la
--  même valeur (d'où, lors d'une 1re version, 100 % de commandes « livree »).
--  La règle sûre : mettre les random() dans la LISTE SELECT d'une requête qui
--  balaie les lignes (generate_series) → évaluation PAR LIGNE. On calcule donc
--  les colonnes aléatoires dans une sous-requête interne, puis on les réutilise
--  dans la requête externe (ex. l'indice de ville sert à ville ET code_postal).
--
--  Volumes cibles :
--    clients          :   100 000
--    produits         :     5 000
--    commandes        :   250 000
--    lignes_commande  : ~1 000 000  (≈ 4 lignes / commande en moyenne)
--
--  Durée typique : ~10 s à 1 min selon la machine.
-- =============================================================================

\timing on
\echo '>>> Génération des données (seed fixe = reproductible)...'

BEGIN;

-- Repart d'un état propre ET réinitialise les séquences IDENTITY à 1.
-- Indispensable : un ROLLBACK n'annule PAS l'avancement des séquences, donc
-- sans RESTART IDENTITY les ids ne seraient plus 1..N et les clés étrangères
-- générées aléatoirement (client_id 1..100000, etc.) pointeraient dans le vide.
TRUNCATE lignes_commande, commandes, produits, clients RESTART IDENTITY CASCADE;

-- Graine fixe : garantit des données identiques d'une exécution à l'autre.
SELECT setseed(0.4242);

-- -----------------------------------------------------------------------------
--  1) CLIENTS
-- -----------------------------------------------------------------------------
\echo '  - clients (100 000)...'
INSERT INTO clients (nom, prenom, email, ville, code_postal, pays, segment, date_inscription)
SELECT
    nom,
    prenom,
    lower(prenom || '.' || nom || '.' || id || '@example.com'),   -- email unique via id
    (ARRAY['Paris','Lyon','Marseille','Toulouse','Bordeaux','Lille','Nantes',
           'Nice','Strasbourg','Rennes','Grenoble','Montpellier'])[ci]  AS ville,
    (ARRAY['75001','69001','13001','31000','33000','59000','44000',
           '06000','67000','35000','38000','34000'])[ci]               AS code_postal,
    'France',
    segment,
    date_inscription
FROM (
    -- Toutes les colonnes aléatoires sont calculées ICI (liste SELECT) → par ligne.
    SELECT
        g.id,
        (ARRAY['martin','bernard','dubois','thomas','robert','richard','petit',
               'durand','leroy','moreau','simon','laurent','lefebvre','michel',
               'garcia','david','bertrand','roux','vincent','fournier']
        )[1 + floor(random()*20)::int]                          AS nom,
        (ARRAY['jean','marie','pierre','luc','paul','julie','sophie','camille',
               'lucas','emma','nael','hugo','lea','chloe','nathan','manon',
               'enzo','sarah','theo','ines']
        )[1 + floor(random()*20)::int]                          AS prenom,
        1 + floor(random()*12)::int                             AS ci,   -- indice ville/CP
        (ARRAY['particulier','particulier','particulier','pro','vip']
        )[1 + floor(random()*5)::int]                           AS segment,
        DATE '2019-01-01' + (random()*2000)::int                AS date_inscription
    FROM generate_series(1, 100000) AS g(id)
) base;

-- -----------------------------------------------------------------------------
--  2) PRODUITS
-- -----------------------------------------------------------------------------
\echo '  - produits (5 000)...'
INSERT INTO produits (nom, categorie, prix, cout, actif, date_ajout)
SELECT
    categorie || ' modèle ' || id,
    categorie,
    prix,
    round((prix * (0.4 + random()*0.3))::numeric, 2),    -- coût = 40 % à 70 % du prix
    actif,
    date_ajout
FROM (
    SELECT
        g.id,
        (ARRAY['Informatique','Téléphonie','Maison','Jardin','Sport',
               'Mode','Beauté','Jouets','Alimentation','Livres']
        )[1 + floor(random()*10)::int]              AS categorie,
        round((5 + random()*495)::numeric, 2)       AS prix,
        random() < 0.92                             AS actif,   -- 92 % de produits actifs
        DATE '2018-01-01' + (random()*2800)::int    AS date_ajout
    FROM generate_series(1, 5000) AS g(id)
) base;

-- -----------------------------------------------------------------------------
--  3) COMMANDES
-- -----------------------------------------------------------------------------
\echo '  - commandes (250 000)...'
INSERT INTO commandes (client_id, date_commande, statut, canal)
SELECT
    client_id,
    date_commande,
    -- statut pondéré à partir d'un SEUL tirage r par ligne
    CASE
        WHEN r < 0.70 THEN 'livree'
        WHEN r < 0.85 THEN 'expediee'
        WHEN r < 0.95 THEN 'en_cours'
        ELSE               'annulee'
    END,
    canal
FROM (
    SELECT
        1 + floor(random()*100000)::int                          AS client_id,
        TIMESTAMP '2023-01-01 00:00:00'
            + (floor(random()*1247*86400))::int * INTERVAL '1 second' AS date_commande, -- ~3,4 ans
        random()                                                 AS r,
        (ARRAY['web','web','mobile','magasin'])[1 + floor(random()*4)::int] AS canal
    FROM generate_series(1, 250000) AS g(id)
) base;

-- -----------------------------------------------------------------------------
--  4) LIGNES_COMMANDE  (la grosse table)
-- -----------------------------------------------------------------------------
\echo '  - lignes_commande (~1 000 000)...'
-- Subtilité PostgreSQL : si la borne de generate_series ne dépend pas de la
-- table externe, le random() est évalué UNE SEULE FOIS pour toute la requête
-- (toutes les commandes auraient alors le même nombre de lignes).
-- Solution : calculer nb_lignes PAR commande dans un sous-SELECT (random() en
-- liste de SELECT = évalué par ligne), puis faire dépendre generate_series de
-- cette colonne → l'expansion devient réellement corrélée à chaque commande.
INSERT INTO lignes_commande (commande_id, produit_id, quantite, prix_unitaire, remise)
SELECT
    sub.commande_id,
    sub.produit_id,
    sub.quantite,
    p.prix,                                              -- prix figé = prix produit
    sub.remise
FROM (
    SELECT
        cmd.id                                 AS commande_id,
        1 + floor(random()*5000)::int          AS produit_id,
        1 + floor(random()*5)::int             AS quantite,
        CASE WHEN random() < 0.2
             THEN round((random()*0.30)::numeric, 3)     -- 20 % des lignes remisées
             ELSE 0 END                        AS remise
    FROM (
        -- nb de lignes tiré PAR commande : 1 à 8 (≈ 4 en moyenne → ~1 000 000 au total)
        SELECT id, 1 + floor(random()*7)::int AS nb_lignes
        FROM commandes
    ) cmd
    CROSS JOIN LATERAL generate_series(1, cmd.nb_lignes) AS gl(n)
) sub
JOIN produits p ON p.id = sub.produit_id;

COMMIT;

-- -----------------------------------------------------------------------------
--  Statistiques fraîches : on ANALYZE après le chargement en masse.
--  (Toujours le faire après un gros INSERT pour que le planificateur ait des
--   estimations correctes — sinon les plans sont faussés.)
-- -----------------------------------------------------------------------------
\echo '>>> ANALYZE (mise à jour des statistiques)...'
ANALYZE clients;
ANALYZE produits;
ANALYZE commandes;
ANALYZE lignes_commande;

-- -----------------------------------------------------------------------------
--  Vérification de la volumétrie
-- -----------------------------------------------------------------------------
\echo '>>> Volumétrie obtenue :'
SELECT 'clients'         AS table_, count(*) FROM clients
UNION ALL SELECT 'produits',         count(*) FROM produits
UNION ALL SELECT 'commandes',        count(*) FROM commandes
UNION ALL SELECT 'lignes_commande',  count(*) FROM lignes_commande;
