# FYP: AI Description-Based Database Agent

This project explores how well AI-written database descriptions support natural-language-to-SQL generation. It uses Python, Semantic Kernel, Azure OpenAI, SQLite, and selectable baseline or hybrid description retrieval.

* See the [application flow diagrams](flow-diagram.md) for CLI modes, schema learning,
description-only SQL generation, and rate-limit handling.
* Use the [project and enhancement tracker](project-and-enhancements.md) to review
implemented functionality and record future requests separately from proposed ideas.

## Current experiment: descriptions only

**The SQL generator currently receives retrieved AI-written table descriptions, not raw table definitions or live database DDL.**

There are two distinct stages:

1. **Learning:** inspect the database schema and five sample rows per table, generate descriptions, and store them with embeddings.
2. **Question answering:** retrieve and rerank those descriptions, generate SQL, execute it, and produce a natural-language answer.

Raw schema is used to create the descriptions during learning. It is not directly supplied to SQL generation during question answering. SQL execution errors can still be passed back to the model for correction.

Raw-schema augmentation was temporarily added during troubleshooting, then commented out to preserve this experiment. Successful runs with augmentation enabled are not evidence of description-only accuracy.

## Requirements and setup

- Python: the local environment was created using Python 3.13.
- [uv](https://docs.astral.sh/uv/).
- An Azure OpenAI chat deployment and credentials.
- Packages in [requirements.txt](requirements.txt).

Run these commands from the repository root in PowerShell:

```powershell
uv venv .venv
uv pip install --python .\.venv\Scripts\python.exe --default-index https://packagefeedproxy.microsoft.io/pypi/simple/ -r .\requirements.txt
.\.venv\Scripts\Activate.ps1
```

The approved package index above was used after downloads from `files.pythonhosted.org` failed with TLS handshake errors. The index is specified per command; no persistent uv index configuration was added.

Dependency versions are currently unpinned, so a new installation may resolve different versions.

### Environment variables

Create a `.env` file at the repository root:

```dotenv
AZURE_OPENAI_API_KEY=
AZURE_OPENAI_ENDPOINT=
AZURE_OPENAI_DEPLOYMENT=
EMBEDDING_MODEL=
```

| Variable | Purpose |
|---|---|
| `AZURE_OPENAI_API_KEY` | Required API key for the Azure resource. |
| `AZURE_OPENAI_ENDPOINT` | Required resource base URL. Do not append `/openai/v1/`; the code appends it. |
| `AZURE_OPENAI_DEPLOYMENT` | Required chat deployment name, not necessarily the underlying model name. |
| `EMBEDDING_MODEL` | Optional local sentence-transformers model name or path. Leave empty for hashing embeddings. |

[AgentKernelFcatory.py](src/DatabaseAgent/AgentKernelFcatory.py) loads environment variables with `python-dotenv`. Existing process environment variables take precedence over values loaded from the file.

Do not commit credentials. The root ignore rules exclude `.env` and `.env.*`, except `.env.example`.

### Embeddings

With `EMBEDDING_MODEL` empty, the app uses a 256-dimensional hashing embedding by default. This is a lexical placeholder, not a learned semantic embedding model. Baseline retrieval reranks vector candidates with BM25; hybrid combines independent vector and BM25 rankings.

Setting `EMBEDDING_MODEL` enables the optional local sentence-transformers implementation. That requires installing `sentence-transformers`, which is not included in the base requirements:

```powershell
uv pip install --python .\.venv\Scripts\python.exe --default-index https://packagefeedproxy.microsoft.io/pypi/simple/ sentence-transformers
```

Models may require an initial download. Use an approved model source or a locally available model path. When changing embedding models or dimensions, use a fresh memory file and rebuild the descriptions; old and new vectors are not interchangeable.

## Running the application

Interactive:

```powershell
.\.venv\Scripts\python.exe .\src\main.py
```

With a question:

```powershell
.\.venv\Scripts\python.exe .\src\main.py "How many products are there?"
.\.venv\Scripts\python.exe .\src\main.py "sales figures for October 2023"
```

Use the explicit interpreter above if VS Code or the terminal reports `ModuleNotFoundError: No module named 'semantic_kernel'`. In VS Code, select `.venv\Scripts\python.exe` as the Python interpreter.

### Simulation and debugging options

```powershell
.\.venv\Scripts\python.exe .\src\main.py --simulate --verbose
.\.venv\Scripts\python.exe .\src\main.py --simulate --verbose --rebuild
.\.venv\Scripts\python.exe .\src\main.py --verbose "How many products are there?"
```

- `--simulate`: runs all ten questions shared with the integration tests, sequentially
  using one agent instance. Prints each question, expected answer, and actual answer.
  It does not score or assert answer similarity and stops if a case fails.
- `--verbose`: enables application information logs plus rewritten-question debug logs.
  Logs include generated SQL and query results; treat them as potentially sensitive.
- `--rebuild`: regenerates stored table descriptions and the agent definition once
  before running the question or simulation. It updates the same `agent_memory.db`.
- `--retriever baseline|hybrid`: selects retrieval behavior; baseline is the default.

Simulation makes live Azure calls and can incur charges. It cannot be combined with
a positional question. Without `--rebuild`, persisted agent definitions are reused.
The cases are in [simulation_cases.py](src/simulation_cases.py), shared with
[test.py](src/test.py) without importing pytest into the application.

For breakpoints, debug [main.py](src/main.py) with these arguments in VS Code and use
the repository root as the working directory. Cases run sequentially for predictable
stepping. Use `--rebuild` to reach schema-learning and agent-generation breakpoints.
Description-only SQL generation remains unchanged.

### Comparing description retrievers

[DescriptionRetrievers.py](src/DatabaseAgent/DescriptionRetrievers.py) contains two
strategies with the same `retrieve(query, top_k)` interface:

| Strategy | Candidate selection | Final ranking |
|---|---|---|
| `BaselineDescriptionRetriever` | Vector top `min(top_k * 5, 100)` | Original BM25-only ordering within those candidates |
| `HybridDescriptionRetriever` | Independent vector search and BM25 over all stored descriptions, each limited to `min(top_k * 5, 100)` candidates | Equal-weight reciprocal rank fusion (RRF) |

Hybrid lexical candidates must share at least one query token with a description.
Tokenization matches baseline: lowercase words extracted using `\w+`.
Fusion deduplicates by record UUID and sums `1 / (60 + rank)` from each branch, using
1-based ranks. Exact fused-score ties are resolved by UUID for deterministic results.
Only the final top `top_k` records are returned; `top_k` must be positive and defaults
to five.

BM25 searches the complete persisted description corpus, not just vector candidates,
so hybrid can recover a matching table that vector search missed, including a stored
description without an embedding. It does not read the live source schema. Memory
enumeration loads stored records, but ranking uses only their descriptions.

```powershell
.\.venv\Scripts\python.exe .\src\main.py --simulate --verbose --retriever baseline
.\.venv\Scripts\python.exe .\src\main.py --simulate --verbose --retriever hybrid
```

Keep the same memory file, descriptions, embedding model, and SQL-generation settings
for both runs. Do not pass `--rebuild` between the two runs. Selecting a strategy
works with saved agents and does not itself regenerate descriptions or alter SQL
generation, filtering, execution, or retries. Verbose logs identify the strategy and
selected table names. Model answers remain nondeterministic.

For Python callers:

```python
from DatabaseAgent.DatabasePluginOptions import DatabasePluginOptions

agent = await DatabaseAgentFactory.create_agent(
    ctx, options=DatabasePluginOptions(retriever="hybrid")
)
```

The shared pipeline still supplies only retrieved AI-written descriptions to SQL
generation. The baseline intentionally retains its original ranking behavior; hybrid
is a separate experimental condition, not a replacement or a proven improvement.

### Database and persisted memory

- The default source database is [northwind.db](src/DatabaseAgent/northwind.db), opened read-only.
- [main.py](src/main.py) uses a separate `agent_memory.db` for generated table descriptions, embeddings, and agent definitions.
- The memory path is relative to the working directory. Running from a different directory can create a different memory file and trigger learning again.
- The first run may make several model calls. Later runs reuse the saved agent and table descriptions.

To explicitly regenerate descriptions and the agent definition, use the existing Python API:

```python
agent = await DatabaseAgentFactory.create_agent(ctx, update=True)
```

Alternatively, pass `--rebuild` to the CLI. Use the same context and memory configuration
as the application. Changes to description-generation prompts do not automatically
refresh stored descriptions.

## Question-answering flow

1. Load or create the persisted agent.
2. Rephrase the question without introducing extra dimensions or invented fields.
3. Retrieve descriptions with the selected baseline or hybrid strategy.
4. Supply selected descriptions to the SQL-generation prompt.
5. Apply the read-only query filter and execute SQL.
6. On SQL failure, pass the previous query and database error back for correction, with up to three SQL attempts.
7. Generate an answer from the database results.

Description retrieval defaults to five final matches. Neither retrieval nor prompt constraints guarantee valid SQL; missing or inaccurate descriptions can still cause failures.

## Updates and modifications

### Environment and dependency setup

- Created a local `.env` configuration with the four variables used by the application.
- Created the uv-managed `.venv` and installed requirements through the approved package feed.
- Verified dependency compatibility and imports during setup.

### Rate-limit handling

[RetryHelper.py](src/DatabaseAgent/Internals/RetryHelper.py) now identifies OpenAI rate-limit errors, including errors wrapped by Semantic Kernel.

- Applies to initialization prompts, query rewriting, SQL generation, and final-answer generation.
- Allows five total attempts by default.
- Checks `retry-after-ms`, `x-ms-retry-after-ms`, then `retry-after`.
- Supports numeric delays and HTTP-date `retry-after` values.
- Ignores invalid, zero, or elapsed delays instead of immediately retrying.
- Without a usable header, waits approximately 60 seconds initially, then 120 seconds, with jitter.
- Logs retries and propagates the exception when attempts are exhausted.
- Does not retry unrelated errors through the rate-limit helper.
- Prevents outer SQL-repair loops from restarting an exhausted rate-limit sequence.

The configured OpenAI client has SDK retries disabled with `max_retries=0`, so application retries control this behavior.

During troubleshooting, the Azure deployment allocation was raised from 10,000 to 30,000 and then to **100,000 tokens/minute and 100 requests/minute**. Those were verified service settings at the time, not limits enforced by this repository or a guarantee of current cloud configuration. Higher actual usage can increase charges.

### Saved-agent reuse

[DatabaseAgentFactory.py](src/DatabaseAgent/DatabaseAgentFactory.py) again loads a stored agent definition when one exists and `update=False`.

This avoids regenerating the agent's description, name, and instructions on every launch. `update=True` retains the explicit rebuild behavior.

### Binary sample-size reduction

During schema learning, binary fields in SQLite sample rows are represented as byte-count labels:

```text
[binary data: 100000 bytes]
```

Previously, escaped byte strings could produce huge prompts; a diagnostic request contained 183,621 characters. The change summarizes `bytes`, `bytearray`, and `memoryview` values before rendering the sample.

This affects only schema-learning samples. It does not modify the source database or replace binary values in actual query results.

### Query scope, dates, and answer accuracy

- [RewriteUserQuery.md](src/DatabaseAgent/Prompts/RewriteUserQuery.md) no longer encourages adding inferred report dimensions, fields, or placeholders.
- [WriteSQLQuery.md](src/DatabaseAgent/Prompts/WriteSQLQuery.md) asks the model to use the supplied descriptions and avoid inventing columns or join keys.
- Current UTC date is supplied to rewriting, SQL generation, and final-answer context.
- "Last month" means the previous calendar month, not the latest month available in the database.
- SQLite month filters are encouraged to use a half-open date range, including the first day of the previous month and excluding the first day of the current month.
- Final-answer instructions distinguish missing records from evidence of zero real-world sales.

The bundled database was inspected during troubleshooting and its latest order date was October 28, 2023. Questions about recent months can legitimately return no matching records.

These are prompt-level behavior changes, not guarantees that every model response will comply.

### Description fidelity for SQL generation

[ExplainTable.md](src/DatabaseAgent/Prompts/ExplainTable.md) now asks the model to:

- Cover every column in supplied order, preserving exact identifiers, types, and
  available constraints.
- State row grain and declared keys, distinguishing structural facts from inferred
  business meaning.
- Include exact join-key pairs only for declared relationships, preserving composite
  key order and marking unsupported cardinality or missing endpoints as unknown.
- Treat sample values as examples, not proof of currency, units, uniqueness, or
  complete data ranges.

Misleading illustrative schema examples were removed. The response fields and storage
format are unchanged. This is a prompt-only enhancement to learning: no runtime
schema validator or live-schema augmentation was added. The separate optional hybrid
retriever adds rank fusion during question answering, not during description generation.
Model compliance and SQL accuracy still require evaluation.

Existing cached descriptions keep their previous content. Use `--rebuild` to apply
the new prompt; preserve a separate copy of the old memory store first if comparing
baseline and enhanced descriptions.

### Optional raw-schema augmentation: disabled

The following additions remain commented out for future comparisons:

| Location | Disabled augmentation |
|---|---|
| [DatabasePlugin.py](src/DatabaseAgent/DatabasePlugin.py), `execute_query_async` | Combining stored raw table definitions with retrieved descriptions. |
| [DatabasePlugin.py](src/DatabaseAgent/DatabasePlugin.py), `_get_sql_query_string_async` | Reading SQLite table/view DDL from `sqlite_master`. |
| Same method's `KernelArguments` | Passing that DDL as `databaseSchema`. |
| [WriteSQLQuery.md](src/DatabaseAgent/Prompts/WriteSQLQuery.md) | Rendering an authoritative live-schema section that overrides descriptions. |

To re-enable **stored-definition augmentation**, replace the active description-only assignment with the adjacent commented assignment.

To re-enable **live-schema augmentation**, enable all three related pieces together:

1. Uncomment the live-schema query block in `_get_sql_query_string_async`.
2. Uncomment its `databaseSchema=database_schema` argument.
3. Restore the commented section in the SQL prompt. For its `#if databaseSchema`, `databaseSchema`, and `/if` expressions, remove the comment `!` marker but keep the Handlebars braces. For ordinary text lines, remove the comment wrappers.

The two augmentation options are independent. Enabling either changes the experiment from description-only SQL generation. Adjust the tests and label evaluation results accordingly.

### Git ignore rules

The root [.gitignore](.gitignore) now covers secrets, virtual environments, Python caches, test/coverage caches, notebook checkpoints, runtime databases and their sidecar files, logs, IDE files, and OS metadata.

The bundled Northwind database is explicitly preserved by exceptions in both relevant ignore files. Already-tracked caches or databases remain tracked; ignore rules do not remove them from Git's index.

## Testing and verification

Run the offline regression tests:

```powershell
.\.venv\Scripts\python.exe -m pytest .\src\test_rate_limits.py .\src\test_sql_grounding.py .\src\test_main_cli.py .\src\test_description_prompt.py .\src\test_description_retrievers.py -q -p no:cacheprovider
```

- [test_rate_limits.py](src/test_rate_limits.py): retry headers, wrapped errors, exhaustion, prompt/SQL/final-answer retry wiring, saved-agent reuse, forced regeneration, and binary sample reduction.
- [test_sql_grounding.py](src/test_sql_grounding.py): description-only SQL inputs, exclusion of raw definitions and live-schema queries, disabled prompt rendering, SQL-repair feedback, date boundaries, and missing historical data.
- [test_main_cli.py](src/test_main_cli.py): simulation ordering, single-agent reuse, rebuild
  forwarding, verbose logging, existing question modes, and error propagation without live calls.

- [test_description_prompt.py](src/test_description_prompt.py): description-prompt
  rendering across providers, faithful input preservation, and response-contract compatibility.
- [test_description_retrievers.py](src/test_description_retrievers.py): baseline
  equivalence, independent lexical recovery, exact rank-fusion scores, deduplication,
  deterministic ties, candidate limits, persisted corpus loading, and error propagation.

The latest recorded offline run passed **81 tests**. These tests use mocked model responses and do not establish description-only model accuracy or hybrid superiority.

The existing [test.py](src/test.py) is a separate live integration/evaluation suite:

```powershell
.\.venv\Scripts\python.exe -m pytest .\src\test.py -q
```

It requires working Azure credentials, makes model calls, can incur charges, and uses an LLM evaluator. It was not run as part of the latest 81-test offline check.

Live smoke tests during troubleshooting returned 77 products and correctly reported no matching records for the relative last-month sales question. The successful sales smoke test occurred while raw-schema augmentation was enabled, before it was commented out; it must not be reported as validation of the current description-only experiment.

## Known limitations and troubleshooting

- **429 errors:** bursts, large requests, or other consumers of the deployment can still exhaust limits. Retries cannot guarantee that an oversized request will eventually fit.
- **Unknown SQL columns:** inspect the generated descriptions and retrieved matches. The current experiment deliberately does not inject live schema to compensate.
- **Stale descriptions:** regenerate with `update=True` after schema or description-generation changes. Use separate memory files for separate databases or experiments.
- **Embedding changes:** use a fresh memory store and rebuild when changing the model or dimensions.
- **Template warnings:** Semantic Kernel may print template-format warnings; inspect the actual exception or result rather than treating every warning as a failed request.
- **Reproducibility:** record model/deployment, prompts, embedding configuration, memory state, and whether augmentation was enabled when comparing results.
