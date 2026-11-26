# Database Migrations (Alembic)

Schema definitions live in `services/claims/models.py`.

```bash
# Generate a migration against the configured DATABASE_URL
alembic revision --autogenerate -m "describe_change"

# Apply migrations
alembic upgrade head

# Rollback one revision
alembic downgrade -1
```
