-- ============================================================
-- THE PLATE SCRAPER (theplatescraper.com)
-- MySQL schema — created by the built-in MySQL Wizard
-- or by setup-theplatescraper.ps1 / tools/mysql_setup.py
-- Requires: MySQL 5.7+ or MariaDB 10.2+ (JSON column support)
-- ============================================================

CREATE TABLE IF NOT EXISTS users (
  email         VARCHAR(190) NOT NULL PRIMARY KEY,
  name          VARCHAR(120) NOT NULL,
  salt          VARCHAR(64)  NOT NULL,
  pw_hash       VARCHAR(128) NOT NULL,
  tier          VARCHAR(20)  NOT NULL DEFAULT 'free',
  created       DOUBLE       NOT NULL DEFAULT 0,
  saved         JSON,
  shopping_list JSON,
  scrapes       JSON,
  custom        JSON,
  list_cursor   INT          NOT NULL DEFAULT 1000
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS sessions (
  token VARCHAR(80)  NOT NULL PRIMARY KEY,
  email VARCHAR(190) NOT NULL,
  KEY idx_sessions_email (email)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS recipes (
  slug  VARCHAR(190) NOT NULL PRIMARY KEY,
  data  JSON         NOT NULL,
  added DOUBLE       NOT NULL DEFAULT 0,
  KEY idx_recipes_added (added)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS substitutions (
  ing_id VARCHAR(60) NOT NULL PRIMARY KEY,
  data   JSON        NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS affiliate_stores (
  id   VARCHAR(40) NOT NULL PRIMARY KEY,
  data JSON        NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS affiliate_products (
  id    VARCHAR(40) NOT NULL PRIMARY KEY,
  store VARCHAR(40) NOT NULL,
  data  JSON        NOT NULL,
  KEY idx_aff_products_store (store)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS affiliate_links (
  code    VARCHAR(40) NOT NULL PRIMARY KEY,
  product VARCHAR(40) NOT NULL,
  created DOUBLE      NOT NULL DEFAULT 0
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS affiliate_clicks (
  id    BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  ts    DOUBLE NOT NULL,
  code  VARCHAR(40) NOT NULL,
  path  VARCHAR(190) NOT NULL DEFAULT '',
  KEY idx_aff_clicks_ts (ts),
  KEY idx_aff_clicks_code (code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS feeds (
  id   VARCHAR(40) NOT NULL PRIMARY KEY,
  data JSON        NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS posts (
  id   VARCHAR(40) NOT NULL PRIMARY KEY,
  data JSON        NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS meta (
  k VARCHAR(60) NOT NULL PRIMARY KEY,
  v JSON        NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
