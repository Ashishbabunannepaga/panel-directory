-- reset_schema.sql
-- Master DDL Schema for Cloudflare D1 (contact_master_v2)

DROP TABLE IF EXISTS possible_duplicates;
DROP TABLE IF EXISTS companies_fts;
DROP TABLE IF EXISTS companies;
DROP TABLE IF EXISTS users;

-- 1. Users & Authentication Table
CREATE TABLE users (
    id TEXT PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'user',
    full_name TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 2. Companies Relational Table
CREATE TABLE companies (
    id TEXT PRIMARY KEY,
    panel_no INTEGER,
    raw_name TEXT NOT NULL,
    canonical_name TEXT NOT NULL,
    normalized_name TEXT NOT NULL,
    aliases TEXT DEFAULT '[]',
    address TEXT DEFAULT '',
    pincode TEXT DEFAULT '',
    website TEXT DEFAULT '',
    emails TEXT DEFAULT '[]',
    phones TEXT DEFAULT '[]',
    representatives TEXT DEFAULT '[]',
    nature_of_business TEXT DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Performance Indexes
CREATE INDEX IF NOT EXISTS idx_panel_no ON companies(panel_no);
CREATE INDEX IF NOT EXISTS idx_canonical_name ON companies(canonical_name);
CREATE INDEX IF NOT EXISTS idx_normalized_name ON companies(normalized_name);
CREATE INDEX IF NOT EXISTS idx_pincode ON companies(pincode);

-- 3. Full-Text Search (FTS5) Virtual Table
CREATE VIRTUAL TABLE companies_fts USING fts5(
    canonical_name,
    normalized_name,
    aliases,
    nature_of_business,
    representatives,
    content='companies',
    content_rowid='rowid'
);

-- 4. Fuzzy Duplicate Review Queue Table
CREATE TABLE IF NOT EXISTS possible_duplicates (
    id TEXT PRIMARY KEY,
    incoming_name TEXT NOT NULL,
    existing_name TEXT NOT NULL,
    similarity_score REAL NOT NULL,
    pincode TEXT DEFAULT '',
    incoming_data TEXT DEFAULT '{}',
    status TEXT DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);