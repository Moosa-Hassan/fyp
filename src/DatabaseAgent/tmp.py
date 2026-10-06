"""Offline end-to-end check of the wiring (no Azure, no embedding model needed).

Run from the folder that contains `src/`:   python -m src.offline_smoke
Uses your real Prompts/*.md and a scripted fake chat model. It checks:
  - every prompt renders and parses (handlebars syntax, no HTML-escaped quotes)
  - schema memorization, agent creation, cache reuse
  - SQL retry loop feeds the previous error back
  - the read-only filter blocks DELETE
"""
import asyncio
import json
import re
import sqlite3
import tempfile
from pathlib import Path

from semantic_kernel.connectors.ai.chat_completion_client_base import ChatCompletionClientBase
from semantic_kernel.connectors.ai.open_ai import OpenAIChatPromptExecutionSettings
from semantic_kernel.contents import AuthorRole, ChatMessageContent

from DatabaseAgent import AgentKernelFactory, DatabaseAgentFactory


class FakeChat(ChatCompletionClientBase):
    ai_model_id: str = "fake"
    service_id: str = "agent"
    log: list = []

    def get_prompt_execution_settings_class(self):
        return OpenAIChatPromptExecutionSettings

    async def _inner_get_chat_message_contents(self, chat_history, settings):
        text = "\n".join(str(m.content) for m in chat_history.messages)
        self.log.append(text)
        assert "&#x27;" not in text and "&quot;" not in text, "template arguments were HTML-escaped"
        return [ChatMessageContent(role=AuthorRole.ASSISTANT, content=json.dumps(self._reply(text)))]

    def _reply(self, text):
        if "Here are the results from the database:" in text:
            data = text.split("Here are the results from the database:")[1].split("The output should")[0]
            return {"thinking": "t", "answer": "DATA " + data.strip().replace("\n", " ")[:120]}
        if "expert SQL query generator" in text:
            nl = re.search(r'\*\*Natural Language Query:\*\* "(.*)"', text).group(1).lower()
            retry = "#### Previous Attempt" in text
            if "delete" in nl:
                return {"comments": [], "query": "DELETE FROM [Customers]"}
            if "customers" in nl:
                return {"comments": [], "query": "SELECT COUNT(*) AS n FROM [Customers]" if retry
                        else "SELECT COUNT(*) AS n FROM [Customer]"}  # wrong table first -> must retry
            if "chai" in nl:
                return {"comments": [], "query": "SELECT UnitPrice FROM [Products] WHERE ProductName = 'Chai'"}
        if "Reformulate user queries" in text:
            q = re.search(r'\*\*User Query\*\*: "(.*)"', text).group(1)
            return {"thinking": "t", "query": q}
        if "You are an expert of" in text:
            t = re.search(r"Table Name:\n(.*)\n", text).group(1)
            return {"tableName": t, "attributes": "- a", "recordSample": "| x |", "definition": f"The {t} table.",
                    "relations": "| r |"}
        if "Create a detailed and appropriate agent description" in text:
            return {"description": "Answers questions about customers and products."}
        if "Generate a creative and fitting agent name" in text:
            assert "Answers questions" in text, "agent description was not injected"
            return {"name": "Data Buddy"}
        if "Generate clear, markdown-based instructions" in text:
            assert "Answers questions" in text, "AgentInstructionsGenerator does not receive the description"
            return {"instructions": "You answer from DB results."}
        raise AssertionError("unrecognised prompt:\n" + text[:300])


async def main():
    tmp = Path(tempfile.mkdtemp())
    db = tmp / "t.db"
    c = sqlite3.connect(db)
    c.executescript("""
        CREATE TABLE Customers (CustomerID TEXT PRIMARY KEY, CompanyName TEXT);
        CREATE TABLE Products (ProductID INTEGER PRIMARY KEY, ProductName TEXT, UnitPrice REAL);
        CREATE TABLE "Order Details" (OrderID INT, ProductID INT REFERENCES Products(ProductID));
        INSERT INTO Customers VALUES ('A','Acme'),('B','Bolt'),('C','Cog');
        INSERT INTO Products VALUES (1,'Chai',18.0);
    """)
    c.commit(); c.close()

    chat = FakeChat()
    ctx = AgentKernelFactory.configure_kernel({"database": {"ConnectionString": str(db)}}, chat_service=chat)
    agent = await DatabaseAgentFactory.create_agent(ctx)
    print("agent:", agent.name, "| tables:", [r.table_name for r in ctx.table_store._records.values()])
    n_calls = len(chat.log)

    again = await DatabaseAgentFactory.create_agent(ctx)  # must reuse, no LLM calls
    assert len(chat.log) == n_calls and again.name == agent.name
    print("reuse ok")

    print("1:", await agent.invoke("How many customers are there?"))
    assert any("Previous Attempt" in t and "[Customer]" in t for t in chat.log), "retry did not feed back previous SQL"
    print("2:", await agent.invoke("Price of 'Chai'?"))
    try:
        await agent.invoke("delete all customers")
        raise SystemExit("FAIL: DELETE was not blocked")
    except RuntimeError as e:
        print("3: blocked ->", str(e)[:70])
    try:
        ctx.connection.execute("DELETE FROM Customers")
        raise SystemExit("FAIL: connection is writable")
    except sqlite3.OperationalError as e:
        print("4: db read-only ->", e)
    print("ALL OK")


if __name__ == "__main__":
    asyncio.run(main())