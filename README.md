# ADK Agent Archetype — Wynxx modernization target (Google ADK 2.1)

This repository is a **Wynxx code-generation archetype**: the target shape for
modernizing a **legacy Java domain into a [Google ADK 2.1](https://adk.dev/)
agent**. Wynxx extracts cohesive **business domains** from the legacy codebase and
the code generator clones this repo as the reference style for each one.

## The mapping

| Legacy (Java)                       | Modernized (ADK 2.1)                                 |
| ----------------------------------- | --------------------------------------------------- |
| Service / module (one domain)       | one `LlmAgent` in `domain_agent/agent.py`           |
| Public service methods / use-cases  | typed function tools in `domain_agent/tools.py`     |
| Business rules / validations        | the agent `instruction` in `domain_agent/prompt.py` |

## Structure (ADK canonical layout)

```
adk-agent-archetype/
├── .env.example          # backend selection (Vertex AI / AI Studio) + observability
├── pyproject.toml        # google-adk >= 2.1, build-system, dev tooling (ruff/mypy/pytest)
├── domain_agent/         # the agent package (its name is the app name)
│   ├── __init__.py       # `from . import agent` — lets `adk run/web` import it
│   ├── agent.py          # defines the module-level `root_agent` (required)
│   ├── prompt.py         # instruction = the domain's business rules
│   ├── tools.py          # one typed function per domain operation
│   └── callbacks.py      # cross-cutting guards (audit logging)
└── tests/                # native ADK eval regression gate
    ├── orders.test.json  # golden tool-call trajectories
    ├── test_config.json  # eval criteria (tool_trajectory_avg_score = 1.0)
    └── test_eval.py      # pytest entrypoint (AgentEvaluator.evaluate)
```

Run locally from this directory: `adk web` (dev UI) or `adk run domain_agent`.

## Conventions

- **Model:** Gemini on Vertex AI (global endpoint). Default to the `gemini-flash-latest`
  selector. For **auditable/compliance domains, pin a specific GA version** (reproducibility
  beats auto-currency) and **never default to a `-preview` model** (quota/availability risk).
  For reasoning-heavy domains, add a `planner` (thinking budget) before escalating to a
  `gemini-pro-*` GA tier — see `archetype.md`.
- **Determinism:** every agent sets `generate_content_config` with `temperature=0` (plus
  `HttpRetryOptions` for 429 resilience). Pipeline sub-agents add `include_contents='none'`
  so each step is a pure function of the state threaded via `output_key`.
- **One agent per domain, one tool per operation;** business rules live in the
  instruction, not scattered across tools.
- **Tools** return a `dict` with a `status` key, validate inputs and coerce numeric
  strings *inside the tool*, and never raise — ADK builds the tool schema from the
  signature and docstring.
- **Composing domains:** for a domain that orchestrates sub-capabilities, use a
  `SequentialAgent` (ordered, auditable pipeline), `ParallelAgent`, or `LoopAgent`; a
  coordinator `LlmAgent` with `sub_agents=[...]` carries shared guardrails via
  `global_instruction`.
- The illustrative domain here is `orders` — generated agents replace it with the
  domain being modernized (e.g. `credit`, `shopping`, `delivery`).

## Evaluation (the regression gate)

The native ADK evaluator turns golden trajectories into a build gate — essential for
auditable domains where a silently-downgraded `DENY` must be caught:

```bash
pip install -e ".[dev]"
pytest tests/                              # via AgentEvaluator (needs a Gemini backend)
# equivalent CLI form — pass the config explicitly (CLI does not auto-discover it):
adk eval domain_agent tests/orders.test.json --config_file_path tests/test_config.json
```

`test_config.json` sets `tool_trajectory_avg_score = 1.0`, so any wrong, reordered, or
dropped tool call fails — the auditability lever. (`response_match_score` is omitted on
purpose: ROUGE on free-form prose is noisy and drifts under the `-latest` alias; add it
only with a pinned GA model and stable references.) Generated agents replace
`orders.test.json` with domain-specific golden trajectories (e.g.
`validate → risk → pricing → decision`), whose tools take explicit scalar args that
assert cleanly.

## Quality tooling

```bash
ruff check domain_agent/      # flags print(), security smells, style, imports
mypy domain_agent/            # strict typing (the archetype mandates it)
```

## Observability

ADK emits OpenTelemetry traces/logs/metrics; for an auditable decision the trace **is**
the provenance. Enable Cloud Trace on deploy (Agent Runtime / Cloud Run / GKE) and use
`OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=NO_CONTENT` to keep PII out of logs.
See `.env.example`.
