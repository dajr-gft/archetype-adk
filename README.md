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
| Who acts comes from the session | The toolkit gives the session user to the use case; no tool has a parameter for it |
| A write is the one the user was shown, answered and made once | Preview, then exactly one message of the user, then the write; refused if what was shown changed; recorded with its confirmation key |
| Every rule says where it comes from | Legacy code, a document, or a declared assumption in `OPEN_POINTS.md` |

## Layout

```
archetype.md               the contract for the generator (patterns, rules, gates)
OPEN_POINTS.md             what the legacy sources do not state
ARCHETYPE_OWNED.sha256     the files a generated agent must not change
domain_agent/              the agent package (its name is the ADK app name)
  agent.py                 root_agent and app (model, generation config, plugins)
  prompt.py                the instruction: behaviour, no business values
  tools.py                 one thin tool per thing the user can ask for
  toolkit.py               (archetype) envelope, acting user, confirmation of writes
  plugins.py               (archetype) audit log, one JSON line per tool call
  wiring.py                which store the agent is connected to
  domain/
    base.py                (archetype) shared types; what makes a write safe
    rules.py               constants, validations, the rule catalogue with sources
    service.py             one use case per legacy operation
    store.py               records, storage port, in-memory implementation
examples/pipeline_agent/   the pipeline pattern: a graph workflow with code steps
tools/
  conformance.py           gate: the rules of archetype.md a machine can check (C00-C13)
  check_model.py           preflight: does the configured model answer here?
  check_deploy.py          preflight: faults that only show after deployment (D01-D08)
tests/
  unit/                    rules, flows, toolkit, store contract, golden set replayed: no model
  eval/                    golden conversations against the real model
  archetype/               self-tests of the archetype (gates, pipeline example)
  support/                 a scripted model that drives the real tools in tests
```

## Run it

```bash
uv sync --extra dev                                  # the locked versions (Python 3.11 or later)
# or: python -m venv .venv && . .venv/bin/activate && pip install -e ".[dev]"
cp .env.example .env                                 # then set the project and the location

python tools/check_model.py                          # the model answers in this project and region
adk run domain_agent                                 # talk to the agent in the terminal
adk web                                              # or in the ADK developer UI
adk run examples/pipeline_agent                      # the pipeline example
```

In the developer UI the user id of the session is the acting user: use two user ids to
play the requester and the approver. The in-memory store starts with two pending requests
of a third user, so an approver has something to decide.

## Gates

```bash
ruff check . && ruff format --check . && mypy        # static
python tools/conformance.py                          # conformance, C00-C13
pytest -m "not model"                                # everything that needs no model
pytest -m model                                      # evaluation, calls the model
```

The first three need no credentials. The evaluation asks for an exact tool trajectory: a
wrong, missing, extra or reordered tool call fails. It fails, not skips, when no backend
is configured (`EVAL_GATE=off` skips it on purpose).

For the archetype itself, also `mypy examples` and, after changing a file of the
archetype, `python tools/conformance.py --write-owned`.

## Deploy

```bash
agents-cli scaffold enhance . --agent-directory domain_agent --deployment-target agent_runtime
python tools/check_deploy.py                         # fix what it reports
agents-cli deploy
```

`check_deploy.py` checks eight faults that pass every local test and fail after
deployment (a missing server dependency, the routes that Gemini Enterprise calls, an
in-memory store, ...). Before deploying, connect the system of record in
`domain_agent/wiring.py` and read section 10 of `archetype.md`: the guarantees of the
agent assume that the platform, not the caller, sets the user of the session.

## What changed

**2.1** (after an independent review of 2.0)

- The escape for braces that 2.0 documented does not work in ADK 2.15: a text passed as
  `instruction=` is templated even with doubled braces, and an unknown name stops the
  agent on its first turn. The instruction is now `static_instruction`, sent as it is.
- A write is bound to what the user was shown (a fingerprint checked inside the
  transaction), happens once per confirmation, and is recorded by the store.
- The confirmation counts the user's messages in the session instead of comparing
  invocation ids: exactly one message after the preview; any other tool call drops it.
  It fails closed through `AgentTool` and with planted session state.
- The guards moved out of the generated `tools.py` into an archetype-owned toolkit,
  tested once through the real ADK runner with a scripted model.
- The tool boundary carries text, integers and booleans only; amounts and dates are
  parsed and formatted by the domain. The tool result is nested under `result`.
- The conformance gate now catches what passed before: a direct write, an identity
  argument that is not the session user, a synchronous tool, a templated instruction, a
  changed archetype file, an evaluation set without the required conversations.
- The evaluation gate fails without a backend, runs one case at a time, and is replayed
  without a model on every run.
- The pipeline example asks for a value the user did not give instead of deciding on a
  default, maps the user's word to a legacy code, and uses exact decimals.
- The audit log has an output of its own (Python drops INFO records by default).

**2.0**: redesign for ADK 2.15 and for any legacy source. Version 1 targeted ADK 2.1 and
legacy Java, kept the rules in the prompt, built a pipeline as a chain of model agents,
and defaulted to the model alias `gemini-flash-latest`, which no longer resolves.
