# Database Agent: Architecture and Execution

**Current mode: AI-description-only SQL generation.**

Read the overview first, then follow the numbered diagrams for implementation detail.
GitHub renders these Mermaid diagrams directly; VS Code needs a Mermaid-capable
Markdown preview.

## Visual key

| Color / shape | Meaning |
|---|---|
| Blue rounded box | User input or output |
| Purple box | LLM operation |
| Teal cylinder | Persistent database or memory |
| Amber diamond | Decision or validation |
| Gray box | Local processing |
| Red box | Failure |
| Solid arrow | Execution or data flow |
| Dashed arrow | Supporting data, configuration, or feedback |

## 1. The big picture

**Two stages, one important boundary:** schema is visible during learning, but only
the resulting descriptions are supplied as schema context during SQL generation.

```mermaid
flowchart TB
    subgraph LEARN["STAGE A - Learn once, or regenerate with --rebuild"]
        direction LR
        DB[("Source SQLite<br/>READ ONLY")] --> Sample["Schema + five sample rows<br/>Summarize binary fields"]
        Sample --> Describe["LLM<br/>Describe each table"]
        Describe --> Memory[("Agent memory<br/>Descriptions + embeddings")]
    end

    subgraph ANSWER["STAGE B - Answer each question"]
        direction LR
        Question(["User question"]) --> Rewrite["LLM<br/>Preserve intent"]
        Rewrite --> Retrieve["Description retrieval<br/>Baseline or hybrid"]
        Retrieve --> SQL["LLM<br/>Generate SQL"]
        SQL --> Execute["Validate read-only SQL<br/>Execute query"]
        Execute --> Respond["LLM<br/>Explain results"]
        Respond --> Output(["Answer"])
    end

    Memory -->|"Selected descriptions ONLY"| Retrieve
    Execute -->|"Read query data"| DB

    classDef io fill:#dbeafe,stroke:#2563eb,color:#172554
    classDef llm fill:#ede9fe,stroke:#7c3aed,color:#2e1065
    classDef store fill:#ccfbf1,stroke:#0f766e,color:#134e4a
    classDef process fill:#f1f5f9,stroke:#64748b,color:#0f172a
    class Question,Output io
    class Describe,Rewrite,SQL,Respond llm
    class DB,Memory store
    class Sample,Retrieve,Execute process
```

**Not injected into SQL prompts:** raw stored table definitions, sample rows, or live
SQLite DDL. The optional schema-augmentation code remains commented out.

## 2. Startup: reuse or rebuild?

**Debugging tip:** `--rebuild` takes the learning path; otherwise a saved agent can
skip that entire section.

```mermaid
flowchart TB
    Start(["Start application"]) --> Setup["Load environment<br/>Configure kernel and model client"]
    Setup --> Open["Open read-only source database<br/>Initialize embeddings and memory stores"]
    Open --> Cache{"Saved agent exists<br/>AND rebuild is off?"}

    Cache -->|Yes| Reuse["Load saved name,<br/>description, and instructions"]
    Cache -->|No| Next["For each source table"]
    Next --> TableCache{"Saved table description<br/>AND rebuild is off?"}
    TableCache -->|Yes| Collect["Collect description"]
    TableCache -->|No| Inspect["Read columns, relationships,<br/>and five sample rows"]
    Inspect --> Compact["Replace binary sample values<br/>with byte-count labels"]
    Compact --> Describe["LLM<br/>Generate table description"]
    Describe --> Persist["Embed and save table record"]
    Persist --> Collect
    Collect --> More{"More tables?"}
    More -->|Yes| Next
    More -->|No| Agent["LLM<br/>Generate agent description,<br/>name if needed, and instructions"]
    Agent --> Save["Embed description<br/>Save agent definition"]
    Save --> Ready(["Agent ready"])
    Reuse --> Ready

    classDef io fill:#dbeafe,stroke:#2563eb,color:#172554
    classDef llm fill:#ede9fe,stroke:#7c3aed,color:#2e1065
    classDef decision fill:#fef3c7,stroke:#d97706,color:#78350f
    classDef process fill:#f1f5f9,stroke:#64748b,color:#0f172a
    class Start,Ready io
    class Describe,Agent llm
    class Cache,TableCache,More decision
    class Setup,Open,Reuse,Next,Collect,Inspect,Compact,Persist,Save process
```

Learning updates `agent_memory.db`, not the source database. Existing descriptions
are not automatically refreshed when their generation prompts change.

## 3. One question: who calls whom?

**This is the main breakpoint map.** Reading downward follows the awaited operations;
the model calls are sequential within this request.

```mermaid
sequenceDiagram
    autonumber
    actor User
    participant CLI as main.py
    participant Agent as DatabaseKernelAgent
    participant Plugin as DatabasePlugin
    participant Retriever as Selected retriever
    participant Memory as Description memory
    participant LLM as Azure OpenAI
    participant DB as Source SQLite

    User->>CLI: Ask a question
    CLI->>Agent: invoke(question)
    Agent->>LLM: Rewrite question, preserving scope
    LLM-->>Agent: Rewritten question
    Agent->>Plugin: execute_query_async(rewritten, original)
    Plugin->>Retriever: retrieve(rewritten question, top_k)
    Retriever->>Memory: Vector search using question embedding
    Memory-->>Retriever: Vector candidates
    alt Baseline strategy - default
        Note over Retriever: BM25 reranks vector candidates
    else Hybrid strategy
        Retriever->>Memory: Load all stored description records
        Memory-->>Retriever: Full description corpus
        Note over Retriever: Independent BM25 ranking<br/>Fuse vector and lexical ranks with RRF
    end
    Retriever-->>Plugin: Top description records
    Note over Plugin,LLM: Description-only boundary:<br/>no raw definitions or live DDL supplied

    loop Up to 3 SQL attempts - stop on success
        Plugin->>LLM: Generate SQL from selected descriptions<br/>and previous SQL/error if correcting
        LLM-->>Plugin: SQL
        Note over Plugin: Enforce read-only query filter
        alt Filter accepts query
            Plugin->>DB: Execute SQL
            DB-->>Plugin: Rows or execution error
        else Filter rejects query
            Note over Plugin: Capture validation error for correction
        end
        Note over Plugin: On error, retry with feedback<br/>After final failure, log and raise
    end

    Plugin-->>Agent: Successful rows rendered as Markdown
    Agent->>LLM: Generate answer from results,<br/>original question, and agent instructions
    LLM-->>Agent: Answer
    Agent-->>CLI: Return answer
    CLI-->>User: Print answer
```

The final steps occur only after a successful SQL attempt. Failed calls propagate
errors instead of continuing with fabricated results. Rate-limit retries wrap the
LLM operations separately; see diagram 5.

Current UTC date is supplied to rewriting, SQL generation, and final-answer context.
"Last month" means the previous calendar month, not the latest month available in
the dataset.

### Retrieval strategies at a glance

```mermaid
flowchart TB
    Query(["Rewritten question"]) --> Select{"--retriever"}
    Select -->|baseline - default| BV["Vector candidate search"]
    BV --> BB["BM25 reranking<br/>within vector candidates"]
    Select -->|hybrid| HV["Independent vector search"]
    Select -->|hybrid| HB["Independent BM25 search<br/>over ALL stored descriptions"]
    HV --> Fusion["Reciprocal rank fusion<br/>Sum 1 / (60 + rank)"]
    HB --> Fusion
    BB --> Top["Top k AI-written descriptions"]
    Fusion --> Top
    Top --> SQL["Shared SQL-generation pipeline"]
    classDef io fill:#dbeafe,stroke:#2563eb,color:#172554
    classDef process fill:#f1f5f9,stroke:#64748b,color:#0f172a
    classDef decision fill:#fef3c7,stroke:#d97706,color:#78350f
    classDef llm fill:#ede9fe,stroke:#7c3aed,color:#2e1065
    class Query io
    class Select decision
    class BV,BB,HV,HB,Fusion,Top process
    class SQL llm
```

Both searches in hybrid use the same question and memory. Each branch selects up to
`min(top_k * 5, 100)` candidates. Fusion deduplicates records and uses UUIDs to break
equal scores. The branches are logically independent but executed sequentially in
the current implementation. Neither strategy injects raw schema.

## 4. Simulation: one agent, ten independent questions

```mermaid
flowchart LR
    Args(["--simulate"]) --> Init["Create or load agent ONCE<br/>--rebuild forces regeneration"]
    Init --> Cases["Load 10 shared test cases"]
    Cases --> Show["Print question<br/>and expected answer"]
    Show --> Invoke["Await agent.invoke(question)<br/>Use pipeline in diagram 3"]
    Invoke --> Valid{"Nonempty answer?"}
    Valid -->|Yes| Print["Print actual answer"]
    Print --> More{"Another case?"}
    More -->|Yes| Show
    More -->|No| Done(["Simulation complete"])
    Valid -->|No| Fail["Raise error<br/>Stop simulation"]
    Invoke -.->|Exception| Fail

    classDef io fill:#dbeafe,stroke:#2563eb,color:#172554
    classDef decision fill:#fef3c7,stroke:#d97706,color:#78350f
    classDef process fill:#f1f5f9,stroke:#64748b,color:#0f172a
    classDef failure fill:#fee2e2,stroke:#dc2626,color:#7f1d1d
    class Args,Done io
    class Valid,More decision
    class Init,Cases,Show,Invoke,Print process
    class Fail failure
```

- Cases run **sequentially**, making breakpoints predictable.
- The same agent and memory are reused, but no shared conversation history is passed.
- Expected answers are displayed for comparison; they are not sent as hints to the agent.
- There is no evaluator score or answer-similarity assertion.
- `--verbose` enables existing SQL/result logs and rewritten-question debug logs.
- Simulation uses live Azure calls and can incur charges.

## 5. Two different retry loops

Do not confuse **transport throttling** with **SQL correction**:

| Loop | Trigger | Budget | What changes on retry? |
|---|---|---|---|
| Model-call retry | OpenAI HTTP 429, including SK-wrapped errors | 5 total attempts by default | Wait, then retry the model operation |
| SQL correction | Query generation, filtering, or execution failure other than an exhausted 429 | 3 total SQL attempts | Supply previous SQL and error to the model |

```mermaid
flowchart TB
    Call["Attempt LLM operation"] --> Result{"Outcome?"}
    Result -->|Success| Done(["Return result"])
    Result -->|Other error| Raise["Propagate error"]
    Result -->|HTTP 429| Budget{"Attempts remain?"}
    Budget -->|No| Exhausted["Log exhaustion<br/>Propagate original exception"]
    Budget -->|Yes| Headers{"Positive, valid<br/>retry delay available?"}
    Headers -->|Yes| Delay["Use server retry delay"]
    Headers -->|No| Fallback["60 seconds initially<br/>then 120 seconds + jitter"]
    Delay --> Sleep["Log delay<br/>await asyncio.sleep"]
    Fallback --> Sleep
    Sleep --> Call

    classDef io fill:#dbeafe,stroke:#2563eb,color:#172554
    classDef llm fill:#ede9fe,stroke:#7c3aed,color:#2e1065
    classDef decision fill:#fef3c7,stroke:#d97706,color:#78350f
    classDef process fill:#f1f5f9,stroke:#64748b,color:#0f172a
    classDef failure fill:#fee2e2,stroke:#dc2626,color:#7f1d1d
    class Done io
    class Call llm
    class Result,Budget,Headers decision
    class Delay,Fallback,Sleep process
    class Raise,Exhausted failure
```

Header priority: `retry-after-ms`, `x-ms-retry-after-ms`, then `retry-after`
(seconds or HTTP date). Zero, negative, invalid, or elapsed values are skipped.
The fallback includes jitter on the initial wait too.

The configured OpenAI client has SDK retries disabled. An exhausted 429 is not
restarted by the outer SQL-correction loop.

## Breakpoint guide

| Goal | Start here |
|---|---|
| CLI options and simulation loop | [main.py](src/main.py) |
| Cache decisions and learning | [DatabaseAgentFactory.py](src/DatabaseAgent/DatabaseAgentFactory.py) |
| Rewritten question and final answer | [DatabaseAgent.py](src/DatabaseAgent/DatabaseAgent.py) |
| Retrieved descriptions, SQL, and correction feedback | [DatabasePlugin.py](src/DatabaseAgent/DatabasePlugin.py) |
| Baseline ranking or independent hybrid search and fusion | [DescriptionRetrievers.py](src/DatabaseAgent/DescriptionRetrievers.py) |
| Retry headers, delays, and exception handling | [RetryHelper.py](src/DatabaseAgent/Internals/RetryHelper.py) |
| Full configuration and optional augmentation instructions | [README](readme.md) |
