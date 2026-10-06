import logging
import pandas as pd


class QueryExecutor:

    @staticmethod
    async def execute_sql_async(
        connection,
        sql_query: str,
        logger=None,
    ):
        log = logger or logging.getLogger("QueryExecutor")

        log.info("SQL Query: %s", sql_query)

        cursor = None

        try:
            cursor = connection.cursor()

            cursor.execute(sql_query)

            return await QueryExecutor._safe_load_to_dataframe_async(
                cursor
            )

        except Exception as ex:
            log.error(
                "Error executing SQL Query: %s",
                sql_query,
                exc_info=ex
            )
            raise

        finally:
            if cursor:
                cursor.close()

    @staticmethod
    async def _safe_load_to_dataframe_async(cursor):
        columns = []

        if cursor.description:
            for col in cursor.description:
                column_name = col[0] or "Column"

                if column_name not in columns:
                    columns.append(column_name)

        rows = cursor.fetchall()

        return pd.DataFrame(rows, columns=columns)