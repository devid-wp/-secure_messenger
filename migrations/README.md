# Alembic migrations

`20260726_01` is a forward-only foundation migration. It supports:

- a clean SQLite or PostgreSQL database;
- the SQLite schema produced by stage 0, including the four migrated messages;
- an already-foundation-shaped database without an Alembic stamp.

For an existing database, the migration builds constrained replacement tables,
copies and verifies all rows, then swaps table names. Unknown legacy chat
members become inactive placeholder users so no messages are lost and all
membership foreign keys remain valid.
