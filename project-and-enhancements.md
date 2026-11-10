# Project Functionality and Enhancement Tracker

Last updated: 2026-11-10

## Project objective

Evaluate how well AI-written database descriptions support natural-language-to-SQL
generation. Keep a reproducible baseline and introduce enhancements as separately
identifiable experimental conditions.

- [README](readme.md): setup, usage, implementation details, and validation history.
- [Flow diagrams](flow-diagram.md): architecture, execution paths, and breakpoint guide.
- This document: implemented functionality, limitations, and enhancement requests.

## Experimental boundaries

1. Raw schema and sample rows may be used during description generation.
2. SQL generation receives retrieved AI-written descriptions, not raw stored
   definitions or live DDL. Optional augmentation remains commented out.
3. Database errors may be supplied during SQL repair; this feedback is part of the
   current baseline and must be recorded when comparing approaches.
4. Compare retrieval strategies using the same persisted descriptions, embedding
   model, and SQL-generation settings. Do not rebuild between comparison runs.
5. Distinguish functional tests from model-accuracy evaluations. Passing mocked tests
   does not establish that an enhancement improves generated SQL.

## Status definitions

| Status | Meaning |
|---|---|
| Proposed | Discussed idea, not approved for implementation. |
| Requested | Explicitly requested; scope or acceptance criteria may still need agreement. |
| In progress | Implementation has started. |
| Blocked | Cannot proceed; record the reason and next action. |
| Implemented | Code and relevant functional checks are complete; record evidence. |
| Evaluated | Comparative model-quality evaluation has also been recorded. |
| Deferred | Intentionally postponed. |

Implementation and evaluation are separate milestones. Do not mark an enhancement
as evaluated based only on offline unit tests or a single successful query.

## Current functionality

The following inventory records existing capabilities, including changes completed
during development. It is not a claim that every model response is correct.

| ID | Functionality | State / behavior | Implementation |
|---|---|---|---|
| FUN-001 | Python environment and configuration | uv environment, approved package-feed installation, and four environment variables documented | [Requirements](requirements.txt), [kernel factory](src/DatabaseAgent/AgentKernelFcatory.py) |
| FUN-002 | Interactive and single-question CLI | Accepts a question argument or prompts for one | [Main](src/main.py) |
| FUN-003 | Description learning | Describes each table from schema and five sample rows; persists records and embeddings | [Agent factory](src/DatabaseAgent/DatabaseAgentFactory.py) |
| FUN-004 | Description fidelity | Prompt requires exact identifiers, exhaustive columns, row grain, declared joins, and labeled inferences; not programmatically enforced | [Description prompt](src/DatabaseAgent/Prompts/ExplainTable.md) |
| FUN-005 | Binary sample reduction | Binary sample fields become byte-count labels; source data remains unchanged | [Agent factory](src/DatabaseAgent/DatabaseAgentFactory.py) |
| FUN-006 | Persistent agent reuse | Reuses saved definitions; `--rebuild` regenerates descriptions and agent definition | [Agent factory](src/DatabaseAgent/DatabaseAgentFactory.py), [main](src/main.py) |
| FUN-007 | Baseline retrieval | Default strategy: vector candidates followed by BM25-only ordering | [Description retrievers](src/DatabaseAgent/DescriptionRetrievers.py) |
| FUN-008 | Hybrid retrieval | Independent vector and full-corpus BM25 search with reciprocal rank fusion; opt in with `--retriever hybrid` | [Description retrievers](src/DatabaseAgent/DescriptionRetrievers.py) |
| FUN-009 | Question rewriting | Every question is sent for rewriting, with instructions to preserve scope and current UTC date | [Agent](src/DatabaseAgent/DatabaseAgent.py), [rewrite prompt](src/DatabaseAgent/Prompts/RewriteUserQuery.md) |
| FUN-010 | Description-only SQL generation | Uses selected descriptions and dialect instructions; raw-schema augmentation is disabled | [Database plugin](src/DatabaseAgent/DatabasePlugin.py), [SQL prompt](src/DatabaseAgent/Prompts/WriteSQLQuery.md) |
| FUN-011 | Read-only execution and SQL repair | Source database opened read-only; query filter and up to three SQL attempts with error feedback | [Kernel factory](src/DatabaseAgent/AgentKernelFcatory.py), [database plugin](src/DatabaseAgent/DatabasePlugin.py) |
| FUN-012 | Rate-limit retries | Handles wrapped 429s, retry headers, fallback delays, and bounded attempts | [Retry helper](src/DatabaseAgent/Internals/RetryHelper.py) |
| FUN-013 | Result-grounded answers | Answers from query results; prompt distinguishes absent records from zero real-world activity | [Agent](src/DatabaseAgent/DatabaseAgent.py) |
| FUN-014 | Live simulation | `--simulate` runs ten shared questions sequentially with one agent; displays expected and actual answers without scoring | [Main](src/main.py), [shared cases](src/simulation_cases.py) |
| FUN-015 | Debug logging | `--verbose` shows rewritten questions, selected retrieval strategy/tables, SQL, and results | [Main](src/main.py), [database plugin](src/DatabaseAgent/DatabasePlugin.py) |
| FUN-016 | Regression and live evaluation tests | Offline tests plus a separate Azure-dependent integration/evaluation suite | [README testing guide](readme.md#testing-and-verification), [live tests](src/test.py) |
| FUN-017 | Git exclusions | Secrets, caches, virtual environments, and runtime databases ignored; previously tracked bytecode untracked | [Root ignore rules](.gitignore) |

## Verification snapshot

- Latest recorded offline regression run: **81 tests passed**.
- Baseline extraction was checked against the original ranking algorithm.
- Hybrid tests cover independent lexical recovery, fusion scores, deduplication,
  candidate limits, and deterministic ties.
- Description-only checks cover both retrievers.
- No live baseline-versus-hybrid accuracy comparison has been completed.
- The description-fidelity prompt has not yet been comparatively evaluated.
- Earlier successful live SQL tests with raw-schema augmentation enabled must not be
  counted as validation of the current description-only condition.

See the [README](readme.md#testing-and-verification) for commands and detailed scope.

## Enhancement backlog

The following ideas were discussed but have **not** been requested for implementation.
Their IDs are stable references; the order below does not establish priority.

| ID | Enhancement | Status | Intended outcome | Acceptance criteria / experiment |
|---|---|---|---|---|
| ENH-001 | Selectable question-rewrite modes | Proposed | Compare current unconditional rewriting with original-question and conditional modes | Keep `always` as baseline; add `off` and `conditional`; record decisions, SQL correctness, latency, and model-call counts |
| ENH-002 | Structured clarification outcomes | Proposed | Avoid silently choosing an ambiguous business definition | Represent preserve/normalize/clarify outcomes; surface clarification to the caller; never send an unresolved request for SQL execution |
| ENH-003 | Explicit relative-date normalization | Proposed | Make temporal interpretation reproducible | Define timezone and calendar boundaries; preserve original wording and resolved range; test month/year boundaries and explicit dates |
| ENH-004 | History-aware follow-up rewriting | Proposed | Resolve requests such as "now group those by category" | Pass relevant conversation context; test standalone and follow-up questions; do not share history between independent simulation cases |
| ENH-005 | Relationship-aware description retrieval | Proposed | Recover necessary join tables missed by top-k retrieval | Expand only from relationships in AI descriptions; bound expansion; evaluate table recall without reading live schema |
| ENH-006 | Diagnosis-driven SQL repair | Proposed | Fix the cause instead of repeatedly regenerating from identical context | Classify missing-context versus syntax errors; retrieve extra descriptions where appropriate; detect repeated failed SQL; preserve bounded retries |
| ENH-007 | Comparative evaluation reports | Proposed | Measure improvements rather than relying on execution success | Record retrieval recall, first-attempt success, verified result correctness, repairs, tokens, latency, and cost for fixed experimental conditions |
| ENH-008 | Learning-time description validation | Proposed | Detect omitted or invented identifiers before descriptions are stored | Define a separately labeled experimental condition; validate against learning input only; report failures explicitly; do not inject schema into SQL prompts |

## Requested enhancements awaiting implementation

None currently recorded. The explicitly requested description-prompt update and
baseline/hybrid retriever implementation are already represented in FUN-004,
FUN-007, and FUN-008.

When a proposal is requested, update its status and add an entry below. Do not infer
approval from a suggestion or from placement in this backlog.

## Enhancement request template

Copy this template for a new request or a detailed expansion of a backlog item:

```markdown
### ENH-009: Short descriptive title

- Status: Requested
- Requested on: YYYY-MM-DD
- Request: What behavior should change?
- Motivation: What limitation or experiment does this address?
- Current behavior:
- Proposed behavior:
- In scope:
- Out of scope:
- Experiment impact: Does this change descriptions, retrieval, rewriting, SQL, or evaluation?
- Baseline preservation: How can the existing behavior still be selected?
- Dependencies / blockers:
- Acceptance criteria:
  - [ ] Observable behavior and edge cases agreed
  - [ ] Description-only boundary preserved, or deviation explicitly approved
  - [ ] Existing behavior and new behavior tested
  - [ ] Documentation and diagrams updated where relevant
- Validation evidence: Commands, results, and evaluation scope
- Outcome / remaining limitations:
```

Use the next unused enhancement ID. Preserve IDs and decisions when moving an item
to Implemented, Evaluated, or Deferred.

## Tracking workflow

1. Record each new request before implementation, reusing an existing ID if applicable.
2. Agree on scope where ambiguity affects behavior or experimental validity.
3. Mark work In progress and record dependencies or blockers.
4. Implement without silently replacing the baseline or enabling raw-schema augmentation.
5. Record functional validation and update the functionality inventory.
6. Track comparative evaluation separately and document its actual conditions.
7. Update this document alongside the relevant code and user-facing documentation.
