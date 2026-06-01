# ADK Agent Archetype — Wynxx modernization target (Google ADK 2.0)

This repository is a **Wynxx code-generation archetype**: the target shape for
modernizing a **legacy Java domain into a [Google ADK 2.0](https://adk.dev/2.0/)
agent**. Wynxx extracts cohesive **business domains** from the legacy codebase and
the code generator clones this repo as the reference style for each one.

## The mapping

| Legacy (Java)                       | Modernized (ADK 2.0)                                 |
| ----------------------------------- | --------------------------------------------------- |
| Service / module (one domain)       | one `LlmAgent` in `domain_agent/agent.py`           |
| Public service methods / use-cases  | typed function tools in `domain_agent/tools.py`     |
| Business rules / validations        | the agent `instruction` in `domain_agent/prompt.py` |

## Structure (ADK 2.0 canonical layout)

```
adk-agent-archetype/
├── .env.example          # backend selection (Vertex AI / AI Studio)
├── pyproject.toml        # depends on google-adk >= 2.0
└── domain_agent/         # the agent package (its name is the app name)
    ├── __init__.py       # `from . import agent` — lets `adk run/web` import it
    ├── agent.py          # defines the module-level `root_agent` (required)
    ├── prompt.py         # instruction = the domain's business rules
    └── tools.py          # one typed function per domain operation
```

Run locally from this directory: `adk web` (dev UI) or `adk run domain_agent`.

## Conventions

- **Model:** Gemini on Vertex AI (global endpoint). `gemini-3.5-flash` by default;
  use `gemini-3.1-pro-preview` for reasoning-heavy domains.
- **One agent per domain, one tool per operation;** business rules live in the
  instruction, not scattered across tools.
- **Tools** return a `dict` with a `status` key, and every parameter is
  type-hinted and documented — ADK builds the tool schema from the signature and
  docstring.
- **Composing domains:** for a domain that orchestrates sub-capabilities, add a
  coordinator `LlmAgent` with `sub_agents=[...]`, or use `SequentialAgent` /
  `ParallelAgent` / `LoopAgent` for fixed pipelines.
- The illustrative domain here is `orders` — generated agents replace it with the
  domain being modernized (e.g. `shopping`, `styling`, `delivery`).
