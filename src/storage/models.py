"""Схема таблиц хранилища."""

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS seen_listings (
    listing_id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('approved', 'rejected')),
    first_seen_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""
