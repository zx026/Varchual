-- ==========================================
-- 5SIM Telegram Bot - FULL DATABASE SCHEMA
-- ==========================================

PRAGMA foreign_keys = OFF;
BEGIN TRANSACTION;

-- ===========================
-- USERS TABLE
-- ===========================
DROP TABLE IF EXISTS users;
CREATE TABLE users (
    tg_id INTEGER PRIMARY KEY,
    balance REAL DEFAULT 0,
    is_admin INTEGER DEFAULT 0,
    created_at TEXT
);

-- ===========================
-- PRICES TABLE
-- ===========================
DROP TABLE IF EXISTS prices;
CREATE TABLE prices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    country TEXT,
    service TEXT,
    price REAL
);

-- ===========================
-- ORDERS TABLE
-- ===========================
DROP TABLE IF EXISTS orders;
CREATE TABLE orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    order_id TEXT,
    phone TEXT,
    country TEXT,
    service TEXT,
    cost_price REAL,
    sell_price REAL,
    status TEXT,
    created_at TEXT
);

COMMIT;
