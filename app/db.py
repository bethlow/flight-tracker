from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
from .config import DATABASE_URL

# One small pool of reusable connections shared by the whole app.
pool = ConnectionPool(DATABASE_URL, min_size=1, max_size=5, kwargs={"row_factory": dict_row}, open=False)

def get_conn():
    """FastAPI dependency: one transaction per request. Commits on success, rolls back on error."""
    with pool.connection() as conn:
        yield conn
