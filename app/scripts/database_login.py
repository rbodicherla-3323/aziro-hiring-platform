import psycopg2
from psycopg2.extras import RealDictCursor

# Hardcoded DB settings
DB_NAME = "aziro_hiring"
DB_USER = "aziro"
DB_PASSWORD = "AziroDb2026"
DB_PORT = 5433
DB_HOST = "localhost"

try:
    conn = psycopg2.connect(
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
        port=DB_PORT,
        host=DB_HOST,
        cursor_factory=RealDictCursor,
    )
    cur = conn.cursor()
    cur.execute("SELECT current_database(), current_user, version();")
    row = cur.fetchone()
    print(f"Connected successfully to the Database '{DB_NAME}' as user '{DB_USER}'.")
    print(row)
    cur.close()
    conn.close()
except Exception as e:
    print(f"DB connection failed: {e}")
