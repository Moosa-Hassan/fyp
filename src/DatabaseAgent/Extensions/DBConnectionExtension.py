import re


class DBConnectionExtension:
    """Maps a Python DB-API connection to the provider names the prompts branch on."""

    _BY_MODULE = (
        ("sqlite3", "SQLite"),
        ("psycopg", "PostgreSQL"),
        ("asyncpg", "PostgreSQL"),
        ("mysql", "MySQL"),
        ("pymysql", "MySQL"),
        ("oracledb", "Oracle"),
        ("cx_oracle", "Oracle"),
        ("pymssql", "SQL Server"),
    )
    _BY_DBMS_NAME = (
        ("sql server", "SQL Server"),
        ("postgres", "PostgreSQL"),
        ("mysql", "MySQL"),
        ("mariadb", "MySQL"),
        ("oracle", "Oracle"),
        ("sqlite", "SQLite"),
    )

    @staticmethod
    def get_provider_name(connection) -> str:
        module = type(connection).__module__.lower()

        for prefix, name in DBConnectionExtension._BY_MODULE:
            if module.startswith(prefix):
                return name

        if module.startswith("pyodbc"):
            try:
                dbms = str(connection.getinfo(17)).lower()  # SQL_DBMS_NAME
                for key, name in DBConnectionExtension._BY_DBMS_NAME:
                    if key in dbms:
                        return name
            except Exception:
                pass
            return "Unknown Provider"

        return "Unknown Provider"

    @staticmethod
    def extract_driver_from_connection_string(connection_string):
        if not connection_string or not connection_string.strip():
            return "Unknown Driver"
        match = re.search(r"Driver\s*=\s*([^;]+)", connection_string, re.IGNORECASE)
        return match.group(1) if match else "Unknown Driver"