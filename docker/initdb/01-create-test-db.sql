-- Runs only on first cluster init. The main DB (study_notes) is created via
-- POSTGRES_DB; this adds the dedicated test database.
CREATE DATABASE study_notes_test;
