# Migrations

This project uses the versioned raw SQL scripts in [`../../database/`](../../database/)
as the source of truth for schema creation (run in SSMS or `sqlcmd`, in order:
`001_create_database.sql` -> `002_create_tables.sql` -> `003_create_indexes.sql` ->
`004_create_seed_data.sql`).

SQLAlchemy models in `app/models/` mirror that schema exactly. If you add a
column, update both the SQL script and the corresponding model, and add a new
`00N_*.sql` script for existing databases (never edit an already-applied
script in place).
