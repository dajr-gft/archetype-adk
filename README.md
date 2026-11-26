# ADK Agent Archetype

Target architecture for modernizing an interactive function of a legacy system into a
**conversational agent on [Google ADK](https://adk.dev/) 2.x**. A code generator (the
Legacy Transformer) clones this repository and fills it with one business domain, from
the business rules it extracted from the legacy source. [`archetype.md`](archetype.md) is
the contract for the generator; this file is for people.

It is independent of the legacy technology (mainframe COBOL, FOCUS, CICS, Java, ...) and
of the business. The domain shipped here (`orders`, invented) only illustrates the shape:
look something up, change it after a confirmation, and have a second person approve it.

## The idea

| Decision | What it means in the code |
|---|---|
| The model talks, code decides | Rules are plain Python in `domain_agent/domain/`, unit-tested without a model |
| Who acts comes from the session | The user is `tool_context.user_id`; no tool has a parameter for it |
| Nothing is written that the user did not see | A write is prepared, shown, then submitted from a draft in the session, in a later turn |
| Every rule says where it comes from | Legacy code, a document, or a declared assumption in `OPEN_POINTS.md` |

## Layout

```
archetype.md               the contract for the generator (patterns, rules, gates)
OPEN_POINTS.md             what the legacy sources do not state
domain_agent/              the agent package (its name is the ADK app name)
  agent.py                 root_agent and app (model, generation config, plugins)
  prompt.py                the instruction: behaviour, no business values
  tools.py                 thin tools: session identity, draft and review guards
  plugins.py               audit plugin (one record per tool call)
  domain/
    rules.py               constants, validations, the rule catalogue with sources
    service.py             one use case per legacy operation
    store.py               records, storage port, in-memory implementation
examples/pipeline_agent/   the pipeline pattern: a graph workflow with code steps
tools/
  conformance.py           gate: the rules of archetype.md a machine can check (C01-C09)
  check_model.py           preflight: does the configured model answer here?
  check_deploy.py          preflight: faults that only show after deployment (D01-D06)
tests/
  unit/                    rules and tool guards, no model
  eval/                    golden conversations against the real model
  archetype/               self-tests of the archetype (gates, pipeline example)
```

## Run it

```bash
python -m venv .venv && . .venv/bin/activate        # Python 3.11 or later
pip install -e ".[dev]"
cp .env.example .env                                 # project, location, optional model

python tools/check_model.py                          # the model answers in this project and region
adk run domain_agent                                 # talk to the agent in the terminal
adk web                                              # or in the ADK developer UI
adk run examples/pipeline_agent                      # the pipeline example
```

In the developer UI the user id of the session is the acting user: use two user ids to
play the requester and the approver.

## Gates

```bash
ruff check . && ruff format --check . && mypy        # static
python tools/conformance.py                          # conformance, C01-C09
pytest -m "not model"                                # unit tests and self-tests, no model
pytest -m model                                      # evaluation, calls the model
```

The first three need no credentials and run in seconds. The evaluation asks for an exact
tool trajectory: a wrong, missing, extra or reordered tool call fails.

## Deploy

```bash
agents-cli scaffold enhance . --agent-directory domain_agent --deployment-target agent_runtime
python tools/check_deploy.py                         # fix what it reports
agents-cli deploy
```

`check_deploy.py` checks six faults that pass every local test and fail on the first call
of the deployed agent (for example a missing server dependency, or the missing routes
that Gemini Enterprise calls). Before deploying, replace the in-memory store with an
implementation on the system of record, and decide who may do what from the user id the
platform passes. See section 10 of `archetype.md`.

## What changed in 2.0

Version 1 targeted ADK 2.1 and legacy Java. Version 2 is a redesign:

- **ADK 2.15** (Python 3.11+): `App` with plugins, the graph `Workflow`, session identity
  on the tool context. The `global_instruction` field is deprecated in ADK and no longer
  used.
- **Rules moved out of the instruction** into a domain package with no ADK dependency,
  with a rule catalogue that cites its sources. Version 1 put the rules in the prompt and
  repeated their values in the tools.
- **The pipeline pattern is a graph workflow with code steps**, not a chain of model
  agents that each call one tool: two model calls instead of one per step, and the order
  cannot be skipped or changed by a model.
- **Write and approval guards in code**: draft before submit, never in the same turn;
  review before a decision; identity from the session. Tools are coroutines, so a slow
  system of record does not stall the other conversations.
- **A conformance gate** turns the prose rules into checks. Each one is a defect that
  code generation produced before (a tool imported but not defined, unescaped braces in
  an instruction, an unavailable model name, the old evaluation format, ...).
- **The model is configuration.** The previous default, the alias `gemini-flash-latest`,
  no longer resolves. The default is now a dated version, overridable with `AGENT_MODEL`,
  and `tools/check_model.py` verifies it per project and region.
- **Any legacy source.** The mapping covers mainframe screens and programs as well as
  services.
- **Money is exact** (integer minor units or `Decimal`), never `float`.
- **Deployment preflight** for Agent Runtime and Gemini Enterprise.
