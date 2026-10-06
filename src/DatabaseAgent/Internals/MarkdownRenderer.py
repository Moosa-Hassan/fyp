import pandas as pd


class MarkdownRenderer:

    @staticmethod
    def render(data):
        if isinstance(data, pd.DataFrame):
            return MarkdownRenderer._render_dataframe(data)

        elif isinstance(data, pd.Series):
            return MarkdownRenderer._render_row(data)

        else:
            raise TypeError(
                "Expected pandas DataFrame or Series"
            )

    @staticmethod
    def _render_dataframe(data_table: pd.DataFrame) -> str:
        result = []

        # Append column names
        result.append(
            "| " + " | ".join(str(column) for column in data_table.columns) + " |"
        )

        # Append separator
        result.append(
            "| " + " | ".join("---" for _ in data_table.columns) + " |"
        )

        # Append rows
        for _, row in data_table.iterrows():
            result.append(
                "| " + " | ".join(str(value) for value in row) + " |"
            )

        result.append("|")

        return "\n".join(result)

    @staticmethod
    def _render_row(data: pd.Series) -> str:
        result = []

        # Append column names
        result.append(
            "| " + " | ".join(str(column) for column in data.index) + " |"
        )

        # Append separator
        result.append(
            "| " + " | ".join("---" for _ in data.index) + " |"
        )

        # Append row
        result.append(
            "| " + " | ".join(str(value) for value in data) + " |"
        )

        return "\n".join(result)