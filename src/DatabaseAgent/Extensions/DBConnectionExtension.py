import re


class DBConnectionExtension:

    @staticmethod
    def get_provider_name(connection):
        type_name = type(connection).__module__ + "." + type(connection).__name__

        if "MySqlClient".lower() in type_name.lower():
            return "MySQL"

        elif "SqlClient".lower() in type_name.lower():
            return "SQL Server"

        elif "Npgsql".lower() in type_name.lower():
            return "PostgreSQL"

        elif "Oracle".lower() in type_name.lower():
            return "Oracle"

        elif "SQLite".lower() in type_name.lower():
            return "SQLite"

        elif "OleDb".lower() in type_name.lower():
            return "OLE DB"

        elif "Odbc".lower() in type_name.lower():
            return DBConnectionExtension._extract_driver_from_connection_string(
                connection.connection_string
            )

        else:
            return "Unknown Provider"

    @staticmethod
    def _extract_driver_from_connection_string(connection_string):
        if not connection_string or not connection_string.strip():
            return "Unknown Driver"

        match = re.search(
            r"Driver\s*=\s*([^;]+)",
            connection_string,
            re.IGNORECASE
        )

        return match.group(1) if match else "Unknown Driver"