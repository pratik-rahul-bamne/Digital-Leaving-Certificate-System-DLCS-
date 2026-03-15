import sqlite3
import os

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
    PSYCOPG2_AVAILABLE = True
except ImportError:
    PSYCOPG2_AVAILABLE = False

from config import DATABASE_URL, SQLITE_PATH


def get_connection():
    """Return a DB connection — PostgreSQL if DATABASE_URL is set, else SQLite."""
    if DATABASE_URL and PSYCOPG2_AVAILABLE:
        conn = psycopg2.connect(DATABASE_URL)
        return conn, "postgres"
    else:
        conn = sqlite3.connect(SQLITE_PATH)
        conn.row_factory = sqlite3.Row
        return conn, "sqlite"


def query(sql, params=(), fetchone=False, fetchall=False, commit=False):
    """Execute SQL and optionally return results. Translates %s→? for SQLite."""
    conn, db_type = get_connection()
    try:
        if db_type == "postgres":
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute(sql, params)
        else:
            sqlite_sql = sql.replace("%s", "?")
            cur = conn.cursor()
            cur.execute(sqlite_sql, params)

        result = None
        if fetchone:
            row = cur.fetchone()
            result = dict(row) if row else None
        elif fetchall:
            rows = cur.fetchall()
            result = [dict(r) for r in rows]

        if commit:
            conn.commit()

        return result
    finally:
        conn.close()


def init_db():
    """Create all tables if they don't exist (idempotent)."""
    conn, db_type = get_connection()
    try:
        cur = conn.cursor()
        if db_type == "postgres":
            cur.execute("""
                CREATE TABLE IF NOT EXISTS admin_users (
                    id SERIAL PRIMARY KEY,
                    username VARCHAR(100) UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )""")
            cur.execute("""
                CREATE TABLE IF NOT EXISTS students (
                    student_id SERIAL PRIMARY KEY,
                    name VARCHAR(200) NOT NULL,
                    father_name VARCHAR(200) NOT NULL,
                    mother_name VARCHAR(200),
                    dob DATE NOT NULL,
                    gender VARCHAR(20),
                    address TEXT,
                    course VARCHAR(200) NOT NULL,
                    department VARCHAR(200) NOT NULL,
                    admission_year INT NOT NULL,
                    admission_type VARCHAR(50) DEFAULT 'First Year',
                    passing_year INT,
                    leaving_year INT NOT NULL,
                    leaving_date DATE,
                    reason_for_leaving TEXT,
                    conduct VARCHAR(100) DEFAULT 'Good',
                    academic_status VARCHAR(100) DEFAULT 'Regular',
                    gap_year_applicable BOOLEAN DEFAULT FALSE,
                    gap_years INT DEFAULT 0,
                    gap_certificate_path TEXT,
                    email VARCHAR(200),
                    phone VARCHAR(30),
                    is_deleted BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )""")
            cur.execute("""CREATE SEQUENCE IF NOT EXISTS cert_number_seq START 1001""")
            cur.execute("""
                CREATE TABLE IF NOT EXISTS certificates (
                    certificate_id SERIAL PRIMARY KEY,
                    student_id INT NOT NULL REFERENCES students(student_id),
                    certificate_number VARCHAR(50) UNIQUE NOT NULL,
                    issue_date DATE NOT NULL DEFAULT CURRENT_DATE,
                    generated_by VARCHAR(100),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )""")
            cur.execute("""
                CREATE TABLE IF NOT EXISTS audit_logs (
                    log_id SERIAL PRIMARY KEY,
                    action VARCHAR(100) NOT NULL,
                    admin_id INT,
                    student_id INT,
                    certificate_id INT,
                    ip_address VARCHAR(50),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )""")
            cur.execute("""
                CREATE TABLE IF NOT EXISTS student_users (
                    id SERIAL PRIMARY KEY,
                    student_id INT UNIQUE REFERENCES students(student_id),
                    username VARCHAR(100) UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    email VARCHAR(200),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )""")
            cur.execute("""
                CREATE TABLE IF NOT EXISTS lc_requests (
                    request_id SERIAL PRIMARY KEY,
                    student_id INT NOT NULL REFERENCES students(student_id),
                    status VARCHAR(30) DEFAULT 'pending',
                    reason TEXT,
                    admin_note TEXT,
                    certificate_id INT REFERENCES certificates(certificate_id),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )""")
        else:
            # ── SQLite ─────────────────────────────────────────────────────────
            cur.executescript("""
                CREATE TABLE IF NOT EXISTS admin_users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    created_at TEXT DEFAULT (datetime('now'))
                );

                CREATE TABLE IF NOT EXISTS students (
                    student_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    father_name TEXT NOT NULL,
                    mother_name TEXT,
                    dob TEXT NOT NULL,
                    gender TEXT,
                    address TEXT,
                    course TEXT NOT NULL,
                    department TEXT NOT NULL,
                    admission_year INTEGER NOT NULL,
                    admission_type TEXT DEFAULT 'First Year',
                    passing_year INTEGER,
                    leaving_year INTEGER NOT NULL,
                    leaving_date TEXT,
                    reason_for_leaving TEXT,
                    conduct TEXT DEFAULT 'Good',
                    academic_status TEXT DEFAULT 'Regular',
                    gap_year_applicable INTEGER DEFAULT 0,
                    gap_years INTEGER DEFAULT 0,
                    gap_certificate_path TEXT,
                    email TEXT,
                    phone TEXT,
                    is_deleted INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT (datetime('now')),
                    updated_at TEXT DEFAULT (datetime('now'))
                );

                CREATE TABLE IF NOT EXISTS certificates (
                    certificate_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    student_id INTEGER NOT NULL REFERENCES students(student_id),
                    certificate_number TEXT UNIQUE NOT NULL,
                    issue_date TEXT NOT NULL DEFAULT (date('now')),
                    generated_by TEXT,
                    created_at TEXT DEFAULT (datetime('now'))
                );

                CREATE TABLE IF NOT EXISTS audit_logs (
                    log_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    action TEXT NOT NULL,
                    admin_id INTEGER,
                    student_id INTEGER,
                    certificate_id INTEGER,
                    ip_address TEXT,
                    created_at TEXT DEFAULT (datetime('now'))
                );

                CREATE TABLE IF NOT EXISTS student_users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    student_id INTEGER UNIQUE REFERENCES students(student_id),
                    username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    email TEXT,
                    created_at TEXT DEFAULT (datetime('now'))
                );

                CREATE TABLE IF NOT EXISTS lc_requests (
                    request_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    student_id INTEGER NOT NULL REFERENCES students(student_id),
                    status TEXT DEFAULT 'pending',
                    reason TEXT,
                    admin_note TEXT,
                    certificate_id INTEGER REFERENCES certificates(certificate_id),
                    created_at TEXT DEFAULT (datetime('now')),
                    updated_at TEXT DEFAULT (datetime('now'))
                );
                CREATE TABLE IF NOT EXISTS student_registrations (
                    reg_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    father_name TEXT NOT NULL,
                    mother_name TEXT,
                    dob TEXT NOT NULL,
                    gender TEXT,
                    address TEXT,
                    course TEXT NOT NULL,
                    department TEXT NOT NULL,
                    admission_year INTEGER NOT NULL,
                    admission_type TEXT DEFAULT 'First Year',
                    passing_year INTEGER,
                    leaving_year INTEGER NOT NULL,
                    leaving_date TEXT,
                    reason_for_leaving TEXT,
                    conduct TEXT DEFAULT 'Good',
                    academic_status TEXT DEFAULT 'Regular',
                    gap_year_applicable INTEGER DEFAULT 0,
                    gap_years INTEGER DEFAULT 0,
                    gap_certificate_path TEXT,
                    email TEXT,
                    phone TEXT,
                    username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    status TEXT DEFAULT 'pending',
                    admin_note TEXT,
                    created_at TEXT DEFAULT (datetime('now'))
                );
            """)
        conn.commit()

        # ── SQLite-only: migrate older databases with missing columns ──────
        if db_type == "sqlite":
            _migrate_sqlite(conn)
    finally:
        conn.close()


def _migrate_sqlite(conn):
    """
    Add any columns that exist in the current schema but are absent from an
    older lc.db (created before the Smart LC rewrite).  ALTER TABLE ADD COLUMN
    is a no-op if the column already exists — we catch the IntegrityError /
    OperationalError so each migration is safe to run repeatedly.
    """
    # Fix #6: Allowlist tables and columns — never interpolate user-supplied input
    _ALLOWED_TABLES = {
        "students", "certificates", "student_registrations",
        "student_users", "lc_requests", "audit_logs", "admin_users",
    }
    _ALLOWED_COLUMN_RE = __import__("re").compile(r"^[a-z_][a-z0-9_]*$")

    migrations = [
        # students — new columns added in v2
        ("students", "mother_name",        "TEXT"),
        ("students", "gender",             "TEXT"),
        ("students", "address",            "TEXT"),
        ("students", "leaving_year",       "INTEGER DEFAULT 0"),
        ("students", "reason_for_leaving", "TEXT"),
        ("students", "academic_status",    "TEXT DEFAULT 'Regular'"),
        ("students", "email",              "TEXT"),
        ("students", "phone",              "TEXT"),
        ("students", "is_deleted",         "INTEGER DEFAULT 0"),
        ("students", "admission_type",     "TEXT DEFAULT 'First Year'"),
        ("students", "passing_year",       "INTEGER"),
        ("students", "gap_year_applicable","INTEGER DEFAULT 0"),
        ("students", "gap_years",          "INTEGER DEFAULT 0"),
        ("students", "gap_certificate_path","TEXT"),
        # student_registrations migrations
        ("student_registrations", "admission_type", "TEXT DEFAULT 'First Year'"),
        ("student_registrations", "passing_year",   "INTEGER"),
        ("student_registrations", "gap_year_applicable", "INTEGER DEFAULT 0"),
        ("student_registrations", "gap_years",      "INTEGER DEFAULT 0"),
        ("student_registrations", "gap_certificate_path", "TEXT"),
        # certificates
        ("certificates", "generated_by",   "TEXT"),
    ]
    cur = conn.cursor()
    for table, column, col_def in migrations:
        # Fix #6: guard — skip any entry that doesn't pass the allowlist
        if table not in _ALLOWED_TABLES:
            raise ValueError(f"_migrate_sqlite: table '{table}' not in allowlist")
        if not _ALLOWED_COLUMN_RE.match(column):
            raise ValueError(f"_migrate_sqlite: column '{column}' failed regex check")
        try:
            cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_def}")
            conn.commit()
        except Exception:
            # Column already exists — safe to ignore
            pass


def next_cert_number(conn, db_type):
    """Generate the next unique certificate number."""
    if db_type == "postgres":
        cur = conn.cursor()
        cur.execute("SELECT nextval('cert_number_seq')")
        seq = cur.fetchone()[0]
        return f"LC-{seq}"
    else:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM certificates")
        count = cur.fetchone()[0]
        return f"LC-{1001 + count}"


def log_action(action: str, admin_id=None, student_id=None, certificate_id=None, ip=None):
    """
    Write a row to audit_logs.
    Call this whenever a certificate is generated, a request is approved/rejected,
    a registration is approved/rejected, or an admin logs in.
    Errors are suppressed so a logging failure never breaks the main request.
    """
    try:
        query(
            """INSERT INTO audit_logs (action, admin_id, student_id, certificate_id, ip_address)
               VALUES (%s, %s, %s, %s, %s)""",
            (action, admin_id, student_id, certificate_id, ip),
            commit=True,
        )
    except Exception:
        pass  # Logging must never crash the app
