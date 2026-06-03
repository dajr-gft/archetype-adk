# ADK Agent Archetype

This project is the **target architecture** for modernizing a **legacy business
domain into a Google ADK 2.1 agent**. The code generator clones this repo and
fills the `domain_agent/` package with the domain it is given, following every
pattern in **Architecture Layers** below.

## What this application is

A minimal, runnable Google ADK agent package. Each cohesive business domain
becomes one `LlmAgent`: its tools are the domain operations and its instruction
encodes the domain's business rules and the exact execution order.

## Pattern Selection (read before writing agent.py)

The `application_pattern` field in the business-rules IR determines which ADK
agent type to use. **Choosing the wrong type is the most common architectural
mistake** — it forces the LLM to orchestrate what the framework should enforce.

| IR `application_pattern` | ADK agent type | When |
|---|---|---|
| `pipeline` | `SequentialAgent` wrapping step sub-agents | Strict ordered steps, fail-fast, compliance audit required |
| `dispatcher` | `LlmAgent` with broad instruction | Flexible routing, multiple capabilities, user-driven |
| `parallel` | `ParallelAgent` wrapping independent sub-agents | Independent operations with no shared mutable state |
| `single_operation` | `LlmAgent` with one tool | Simple CRUD or single computation |

### Pipeline pattern → SequentialAgent (preferred for compliance domains)

For pipeline domains (credit decisions, approval workflows, batch processing),
`SequentialAgent` enforces execution order at the framework level — the LLM
cannot skip, reorder, or repeat steps. This is mandatory for auditable flows.

Use `output_key` on each sub-agent to thread state without requiring the LLM to
pass intermediate results as tool parameters.

```python
from google.adk.agents import LlmAgent, SequentialAgent
from google.genai import types
from .prompt import (
    VALIDATE_INSTRUCTION, RISK_INSTRUCTION,
    PRICING_INSTRUCTION, DECISION_INSTRUCTION,
)
from .tools import validate_inputs, evaluate_risk, calculate_pricing, evaluate_decisioning

MODEL = "gemini-flash-latest"   # pin a GA version for auditable domains — see Model strategy

# Deterministic decoding for auditable rules + 429 resilience — see Generation config.
GENERATION = types.GenerateContentConfig(
    temperature=0.0,
    http_options=types.HttpOptions(
        retry_options=types.HttpRetryOptions(initial_delay=1, attempts=3),
    ),
)

# include_contents="none" makes each step a pure function of the state injected via
# {output_key} templates — no conversation-history bleed (see Manage step context).
_validate_agent = LlmAgent(
    name="validate_agent",
    model=MODEL,
    instruction=VALIDATE_INSTRUCTION,
    tools=[validate_inputs],
    generate_content_config=GENERATION,
    include_contents="none",
    output_key="validation_result",   # written to session.state automatically
)

_risk_agent = LlmAgent(
    name="risk_agent",
    model=MODEL,
    instruction=RISK_INSTRUCTION,
    tools=[evaluate_risk],
    generate_content_config=GENERATION,
    include_contents="none",
    output_key="rule_hits",
)

_pricing_agent = LlmAgent(
    name="pricing_agent",
    model=MODEL,
    instruction=PRICING_INSTRUCTION,
    tools=[calculate_pricing],
    generate_content_config=GENERATION,
    include_contents="none",
    output_key="pricing_result",
)

_decision_agent = LlmAgent(
    name="decision_agent",
    model=MODEL,
    instruction=DECISION_INSTRUCTION,
    tools=[evaluate_decisioning],     # tool computes the decision deterministically
    generate_content_config=GENERATION,
    include_contents="none",
    output_key="final_decision",
)

# SequentialAgent enforces order at the framework level — LLM cannot reorder steps.
root_agent = SequentialAgent(
    name="<domain>_domain_agent",
    sub_agents=[_validate_agent, _risk_agent, _pricing_agent, _decision_agent],
)
```

### Dispatcher pattern → LlmAgent (flexible routing)

For domains where the user drives which operation to invoke, a single `LlmAgent`
with all tools is the right choice. The LLM selects the appropriate tool based
on intent.

```python
root_agent = LlmAgent(
    name="<domain>_domain_agent",
    model=MODEL,
    description="Modernized '<Domain>' business domain (from a legacy Java service).",
    instruction=DOMAIN_INSTRUCTION,
    tools=[operation_a, operation_b, operation_c],
    generate_content_config=GENERATION,   # see Generation config
    after_tool_callback=audit_tool_call,  # see Cross-cutting callbacks
)
```

A dispatcher keeps the default `include_contents` (it needs the conversation to
route); only deterministic pipeline steps use `include_contents="none"`.

---

## Architecture Layers

### Agent
File: `domain_agent/agent.py`. Defines the module-level `root_agent` using the
pattern selected above. One agent (or `SequentialAgent` root) per domain.

**Import contract (strict):** derive the import list by reading `tools.py` and
listing every public function defined there — those that do **not** start with
`_`. The `from .tools import ...` names and the `tools=[...]` list must be
**identical** to that set. Never import a name that does not exist in `tools.py`;
never omit a public tool that does exist.

```python
from google.adk.agents import LlmAgent
from google.genai import types
from .callbacks import audit_tool_call
from .prompt import DOMAIN_INSTRUCTION
# Import list derived from public functions in tools.py — keep in sync.
from .tools import evaluate_risk, calculate_pricing, evaluate_decisioning

# See Model strategy below. Default to the latest-stable Flash selector; pin a GA
# version for auditable domains. Write the full literal string — never truncate.
MODEL = "gemini-flash-latest"

GENERATION = types.GenerateContentConfig(           # see Generation config
    temperature=0.0,
    http_options=types.HttpOptions(
        retry_options=types.HttpRetryOptions(initial_delay=1, attempts=3),
    ),
)

root_agent = LlmAgent(
    name="<domain>_domain_agent",
    model=MODEL,
    description="Modernized '<Domain>' business domain (from a legacy Java service).",
    instruction=DOMAIN_INSTRUCTION,
    tools=[evaluate_risk, calculate_pricing, evaluate_decisioning],
    generate_content_config=GENERATION,
    after_tool_callback=audit_tool_call,
)
```

#### Generation config (required)

ADK does not pin a low temperature by default, and Gemini's default sampling is
high — a business-rules agent must not re-roll its rule evaluation. Every agent
sets `generate_content_config` with `temperature=0.0` for the most deterministic
decoding the model allows, plus `HttpRetryOptions` for transient-429 resilience.
`temperature=0` is *strong* but not a byte-for-byte determinism guarantee — the
**eval gate** (see Evaluation) is what actually locks behavior.

#### Model strategy

`MODEL` is a literal model string. Choose it by these rules:

- **Default:** `"gemini-flash-latest"` — the latest-stable Flash selector. Requires
  the `global` endpoint (set in `.env`); on a regional endpoint use a versioned ID.
- **Auditable/compliance domains:** prefer a **pinned GA version** over `-latest`.
  Reproducibility (a fixed model → fixed behavior, regression-diffable) beats
  auto-currency, which can silently drift a credit decision. **But pin only a dated GA
  release you have verified exists in the target Vertex project** — pinning a retired or
  not-yet-enabled version (e.g. `gemini-2.0-flash-001`) raises a runtime
  `404 NOT_FOUND. Publisher Model ... not found`. When unsure, keep the
  `gemini-flash-latest` alias (the safe default) rather than guessing a dated string.
- **Never default to a `-preview` model** — preview models carry availability and
  quota limitations unsuitable for production.
- **Reasoning-heavy domains:** add a `planner` (next section) *before* escalating
  to a `gemini-pro-*` **GA** tier.

#### Reasoning-heavy domains → planner (not a bigger model first)

When a domain needs genuine multi-step reasoning, keep Flash and add bounded
thinking instead of jumping to a Pro model — cheaper and more predictable, and the
budget caps latency/cost:

```python
from google.adk.planners import BuiltInPlanner

planner = BuiltInPlanner(
    thinking_config=types.ThinkingConfig(thinking_budget=1024),
)
# LlmAgent(..., planner=planner)
```

`PlanReActPlanner` is the alternative for models without native thinking. Only
escalate to a `gemini-pro-*` GA model if a planner is still insufficient.

#### Manage step context with `include_contents`

`include_contents` controls whether an agent receives prior conversation history
(default `"default"`). For a `SequentialAgent` pipeline, set
`include_contents="none"` on each step so it is a **pure function of the state**
injected via `{output_key}` templates (see §9) — no history bleed, tighter
determinism, cleaner audit. Keep the default on a **dispatcher** `LlmAgent`, which
needs the conversation to route.

#### Structured output with `output_schema` (terminal, tool-less steps only)

To force a machine-checkable JSON output, set `output_schema=<PydanticModel>` on
an agent. **Caveat (from the ADK docs): `output_schema` does not work reliably on
an agent that also has `tools`.** So use it only on a **terminal step that calls
no tools** and merely formats/summarizes prior state:

```python
from pydantic import BaseModel

class DecisionSummary(BaseModel):
    status: str            # "APPROVED" | "REFERRED" | "DENIED"
    approved_limit_brl: float
    reasons: list[str]

# Tool-less summarizer reads {final_decision} from state and re-emits it as schema:
_summary_agent = LlmAgent(
    name="summary_agent", model=MODEL, instruction=SUMMARY_INSTRUCTION,
    generate_content_config=GENERATION, include_contents="none",
    output_schema=DecisionSummary,    # NO tools on this agent
)
```

Prefer a **deterministic tool** (e.g. `evaluate_decisioning`) for the actual
computation — the tool returns the authoritative values; `output_schema` only
shapes a final, LLM-formatted view. Never put `output_schema` on a tool-calling
agent. Optionally use `input_schema` on the entry agent for a strict request
contract.

#### Cross-cutting callbacks (audit trail)

Wire `after_tool_callback=audit_tool_call` (see `domain_agent/callbacks.py`) on
every agent to emit a structured audit record per tool call — for an auditable
domain the tool-call sequence *is* the decision trail. Keep **business validation
and numeric coercion inside the tools** (the tool is where the types and verbatim
string codes are known); centralizing coercion in a callback would risk corrupting
domain string codes (e.g. CNAE `"24"`). Callbacks are for cross-cutting concerns
(audit logging, guardrails), not business logic.

---

### Tools
File: `domain_agent/tools.py`. One typed Python function per domain operation.
ADK infers each tool's JSON schema from the function name, type hints, and
docstring — keep all three accurate and complete.

#### 0. Process integrity (non-negotiable)

These rules protect the ADK agent process — violating them causes silent crashes
or data loss that are hard to diagnose.

```python
# ❌ NEVER — sys.exit() / os._exit() / raise SystemExit inside a tool
# Kills the entire agent process, not just the tool call.
# Any error that Java signalled with an ABEND or System.exit() must be
# converted to a structured error return.
def validate_file_io(return_code: str) -> dict[str, Any]:
    if return_code not in VALID_CODES:
        sys.exit(1)                          # ← FORBIDDEN in ADK tools
        print("ABENDING PROGRAM")           # ← FORBIDDEN: print() is not captured

# ✅ Correct — return error dict; the agent framework handles it gracefully
def validate_file_io(return_code: str) -> dict[str, Any]:
    if return_code not in VALID_CODES:
        return {"status": "error",
                "error_message": f"Invalid I/O return code {return_code!r}. ABEND."}
    return {"status": "success", "result": "OK"}
```

Never use `sys.exit`, `os._exit`, `raise SystemExit`, or bare `print()` anywhere
in `tools.py`. All communication with the agent goes through the return dict.

#### 1. Module-level constants (required)

Declare every fixed value sourced from the original Java (`static final` fields,
config constants, policy thresholds) as a **module-level constant** in
`SCREAMING_SNAKE_CASE`. Business constants must never be function parameters —
the LLM must not be able to override a policy value at call time.

```python
from __future__ import annotations

from typing import Any

# ── Business constants (exact values from the legacy source) ──────────────────
BASE_SPREAD_PCT: float = 5.20
MIN_SERASA_SCORE: int = 600
REFER_SERASA_THRESHOLD: int = 700
MIN_REVENUE_MULTIPLE: float = 3.0
MAX_NET_DEBT_EBITDA: float = 3.5
REFER_NET_DEBT_EBITDA: float = 2.5
MAX_EXPOSURE_PCT_OF_PL: float = 0.15
REFER_EXPOSURE_PCT_OF_PL: float = 0.12
MAX_TENOR_DEFAULT_MONTHS: int = 60
MAX_TENOR_WATCHLIST_MONTHS: int = 24
SPREAD_DISCOUNT_RECEIVABLES: float = 1.00
SPREAD_DISCOUNT_REAL_ESTATE: float = 1.80
SPREAD_DISCOUNT_LONG_CLIENT: float = 0.30
WATCHLIST_SECTORS: frozenset[str] = frozenset({"24", "41", "42", "49"})
RESTRICTED_SECTORS: frozenset[str] = frozenset({"12", "92"})
```

#### 2. String literals — verbatim fidelity

String constants from Java — enum names, type identifiers, reason codes, sector
codes — **must be reproduced character-for-character**, including underscores,
capitalisation, and any other formatting present in the original source. Never
normalise, strip underscores, or change case.

```python
# ✅ Correct — matches Java CollateralType.REAL_ESTATE.name()
if collateral_type == "REAL_ESTATE":
    discount = SPREAD_DISCOUNT_REAL_ESTATE

# ❌ Wrong — underscore removed, breaks every caller that passes the Java enum name
if collateral_type == "REALESTATE":
    ...
```

#### 3. Derived calculations belong in the tool body

When a Java method computes an intermediate value internally before applying a
rule, replicate that computation **inside the Python tool**. Never expose a
derived value as a function parameter — the LLM calling the tool should never
be asked to pre-compute what the original Java method computed itself.

```python
# ✅ Correct — mirrors Java: projected = current + amount; pct = projected / equity
def evaluate_exposure_concentration(
    current_exposure_brl: float,
    amount_brl: float,
    net_equity_brl: float,
) -> dict[str, Any]:
    projected_exposure = current_exposure_brl + amount_brl  # Java-internal formula
    exposure_pct = projected_exposure / net_equity_brl
    if exposure_pct > MAX_EXPOSURE_PCT_OF_PL:
        return {"status": "success", "outcome": "DENY", "reason": "CONCENTRACAO_EXCESSIVA"}
    ...

# ❌ Wrong — caller (LLM) must pre-compute exposure_pct; formula is lost
def evaluate_exposure_concentration(exposure_pct: float) -> dict[str, Any]:
    ...
```

#### 4. DENY vs REFER — strict semantic mapping

Map each Java call to its ADK outcome with zero tolerance for reinterpretation.
Inspect the **concrete Java call**, not the rule description text:

| Java source pattern | ADK `"outcome"` |
|---|---|
| `Decision.deny(reason)` · `return Decision.denied(...)` · `throw DenialException` | `"DENY"` |
| `addReferralReason(reason)` · `referrals.add(reason)` · `Decision.refer(...)` | `"REFER"` |
| Rule passes with no action | `"OK"` |

A rule that was a hard DENY in Java must remain `"DENY"` in the tool. Silently
downgrading DENY to REFER changes the bank's credit policy — any regression
suite will catch it and any auditor will flag it.

#### 5. Fail-fast pipeline inside the tool

When the Java method returned immediately upon a DENY (fail-fast pattern), the
Python tool must do the same. Do **not** continue evaluating subsequent rules
after a hard DENY — append the hit and return immediately.

```python
# ✅ Correct — fail-fast after first DENY, matches Java behaviour
if sector_cnae in RESTRICTED_SECTORS:
    return {"status": "success", "rule_hits": [
        {"rule": "BR-009", "outcome": "DENY", "reason": "SETOR_RESTRITO"}
    ]}

# ❌ Wrong — appends DENY and continues evaluating, diverges from Java pipeline
rule_hits.append({"rule": "BR-009", "outcome": "DENY", ...})
# ... more rule checks below — never reached in Java
```

#### 6. Runtime type coercion

The LLM may pass numeric values as strings (e.g. `"1500000"` instead of
`1500000.0`). Coerce scalar parameters at the entry point of every tool to avoid
`TypeError` deep in business logic:

```python
try:
    amount_brl = float(amount_brl)
    tenor_months = int(tenor_months)
    serasa_score = int(serasa_score)
except (TypeError, ValueError):
    return {"status": "error", "error_message": "Numeric parameters must be numeric."}
```

#### 7. Tool parameter size limit

ADK tool calls pass parameters as JSON through the LLM. Do **not** design tools
that accept large collections (lists of transactions, full customer datasets,
file contents) as parameters. The LLM cannot reliably populate or pass back
thousands of records. Instead:

- Accept identifiers/keys and look up data internally (database, file, API).
- If batch processing is unavoidable, split into smaller tools with pagination.
- Maximum realistic parameter payload: ~50 records or ~2 KB of JSON.

```python
# ❌ Wrong — LLM cannot reliably supply large lists
def generate_batch_statements(
    transactions: list[dict[str, Any]],   # potentially thousands of records
    customers: list[dict[str, Any]],
    accounts: list[dict[str, Any]],
) -> dict[str, Any]: ...

# ✅ Correct — tool fetches data internally; LLM passes only the key
def generate_batch_statements(report_date: str) -> dict[str, Any]:
    transactions = _load_transactions(report_date)   # internal I/O
    ...
```

#### 8. Input validation — complete, first

Validate every parameter that the original Java `validateInput` (or equivalent)
method checked, **before** any business logic runs. Return `{"status": "error",
"error_message": "..."}` for invalid inputs — never raise exceptions.

```python
def evaluate_risk(
    amount_brl: float,
    tenor_months: int,
    sector_cnae: str,
    serasa_score: int,
    revenue_12m_brl: float,
    net_debt_ebitda: float | None,
    current_exposure_brl: float,
    net_equity_brl: float,
) -> dict[str, Any]:
    """Evaluate credit risk, enforcing BR-001 through BR-008.

    Args:
        amount_brl: Requested credit amount in BRL. Must be strictly positive.
        tenor_months: Requested term in months. Must be strictly positive.
        sector_cnae: Client CNAE sector code. Must not be null or empty.
        serasa_score: Serasa bureau score. Must be in range [0, 1000].
        revenue_12m_brl: Trailing 12-month revenue in BRL. Must be strictly positive.
        net_debt_ebitda: Net Debt / EBITDA ratio, or None when not available.
        current_exposure_brl: Existing exposure before this operation, in BRL.
        net_equity_brl: Client net equity (Patrimônio Líquido) in BRL. Must be positive.
    Returns:
        dict: ``status`` ("success" | "error"); on success, ``rule_hits`` list
        where each hit has ``rule``, ``outcome`` ("DENY" | "REFER" | "OK"), and
        ``reason``; on error, ``error_message``.
    """
    # ── Validation (mirrors Java validateInput — cover every field checked there)
    if amount_brl is None or amount_brl <= 0:
        return {"status": "error", "error_message": "amount_brl must be strictly positive."}
    if tenor_months is None or tenor_months <= 0:
        return {"status": "error", "error_message": "tenor_months must be strictly positive."}
    if not sector_cnae:
        return {"status": "error", "error_message": "sector_cnae must not be null or empty."}
    if serasa_score is None or not (0 <= serasa_score <= 1000):
        return {"status": "error", "error_message": "serasa_score must be in [0, 1000]."}
    if revenue_12m_brl is None or revenue_12m_brl <= 0:
        return {"status": "error", "error_message": "revenue_12m_brl must be strictly positive."}
    if net_equity_brl is None or net_equity_brl <= 0:
        return {"status": "error", "error_message": "net_equity_brl must be strictly positive."}

    rule_hits: list[dict[str, Any]] = []

    # ── Business rules ────────────────────────────────────────────────────────
    # BR-001: Tenor limit
    max_tenor = MAX_TENOR_WATCHLIST_MONTHS if sector_cnae in WATCHLIST_SECTORS \
        else MAX_TENOR_DEFAULT_MONTHS
    if tenor_months > max_tenor:
        rule_hits.append({"rule": "BR-001", "outcome": "DENY", "reason": "PRAZO_EXCEDE_POLITICA"})
        return {"status": "success", "rule_hits": rule_hits}  # fail-fast

    # ... remaining rules ...
    return {"status": "success", "rule_hits": rule_hits}
```

#### 9. State threading with output_key (pipeline pattern)

In a `SequentialAgent` pipeline, each sub-agent's result is written to
`session.state` via `output_key`. The next sub-agent reads prior results from
state — **the LLM never needs to re-pass intermediate values as parameters**.

Tools in downstream steps access prior results from the session context
automatically; the sub-agent instruction should reference `{rule_hits}` (the
output_key of the upstream step) using ADK's template interpolation:

```python
# The intake/validate step returns the FULL request, so {validation_result} carries every
# field; each later step reads the raw inputs it needs from it — not just the previous step's
# output. (amount_brl is a RAW request field, so it comes from {validation_result}.)
DECISION_INSTRUCTION = """\
You are the decision assembly step.

Validated request: {validation_result}   # full request — read amount_brl from here
Risk evaluation:   {rule_hits}
Pricing result:    {pricing_result}

Call evaluate_decisioning with rule_hits, suggested_spread_pct (from {pricing_result}), and
amount_brl (from {validation_result}). Return the final credit decision.
"""
```

This eliminates the LLM threading problem: each step sees the upstream outputs injected into
its instruction — it cannot lose, reorder, or hallucinate them.

> **⚠️ A downstream step sees ONLY the upstream `output_key`s injected into state — NEVER the
> original user request.** So **the FIRST step must capture and echo EVERY field the later
> steps need**, and each step threads forward what downstream steps require. If the validate
> step returns only a few of the request's fields, the risk/pricing/decision steps won't have
> `serasa_score`, `revenue_12m_brl`, `amount_brl`, etc. — and the LLM will then **hallucinate
> "a healthy profile" or stall asking the user for values**. Make the intake/validate tool
> return the **full validated request**, and reference its `output_key` (e.g.
> `{validation_result}`) in every later step that needs a raw input.

#### 10. Return shape (all tools)

```python
# Success
{"status": "success", "result": {...}}      # computation result
{"status": "success", "rule_hits": [...]}   # rule evaluation

# Error — never raise; always return
{"status": "error", "error_message": "Human-readable description."}
```

---

### Prompt
File: `domain_agent/prompt.py`. For `SequentialAgent` pipelines, define **one
instruction per sub-agent step**. For `LlmAgent` dispatchers, define a single
`DOMAIN_INSTRUCTION` covering all capabilities.

> **⚠️ Curly braces are ADK templates — escape every literal one (critical, runtime-fatal).**
> At runtime ADK replaces every `{name}` in an instruction with `session.state["name"]`. The
> **only** single-brace `{name}` allowed is an upstream **`output_key`** (a real state key,
> e.g. `{rule_hits}`). **Every other literal brace MUST be doubled** — JSON examples, output
> samples, and field names such as `{serasaScore}`, `{highRelevanceCount}`, or
> `{companyName}` must be written `{{serasaScore}}`, `{{highRelevanceCount}}`,
> `{{companyName}}`. An unescaped non-state `{name}` raises
> `KeyError: Context variable not found: 'name'` and the agent **crashes on its first turn**.
> Rule of thumb: in any instruction, double **every** brace that is not an upstream output_key.

**Pipeline step instructions** must state:
1. **Single responsibility** — "You are the risk evaluation step. Call `evaluate_risk` once and return."
2. **Inputs from session state** — reference prior `output_key` values via `{key}` templates.
3. **Fail-fast trigger** — explicit condition: "If rule_hits contains any DENY, halt — do not call further tools."
4. **Explicit outcomes** — never write "appropriate outcome"; always write DENY, REFER, or OK.

**Dispatcher instruction** must state:
1. All tools and when to invoke each.
2. Business rules verbatim from the IR.
3. No orchestration order (LLM decides based on user intent).

```python
DOMAIN_INSTRUCTION = """\
You are the **<Domain>** domain agent, modernized from a legacy Java service.

Responsibilities:
- Own every business operation of the <Domain> domain.
- Execute tools in the exact order below — do not reorder, skip, or parallelize steps.
- Apply fail-fast pipeline semantics: if any tool returns a rule_hit with
  outcome DENY, stop immediately and return the denial decision without calling
  further tools.

Tool execution order:
1. evaluate_risk(amount_brl, tenor_months, sector_cnae, serasa_score,
                 revenue_12m_brl, net_debt_ebitda, current_exposure_brl,
                 net_equity_brl)
   → Applies BR-001 to BR-008. On any DENY in rule_hits: return denial now.

2. calculate_pricing(collateral_type, years_as_client)
   → Applies BR-002, BR-003, CALC-001. Returns suggested_spread_pct.

3. evaluate_decisioning(rule_hits, suggested_spread_pct, amount_brl)
   → Assembles final status (APPROVED / REFERRED / DENIED) and approved_limit_brl.

Business rules enforced:
  * VAL-001: <rule text — copied verbatim from extracted rules>
  * BR-001: <rule text>
  ...

Never guess a result without calling the corresponding tool.
Never pass a pre-computed value that the tool is responsible for computing internally.
"""
```

---

## Conventions

- One agent per domain; one tool per domain operation; business rules in the instruction.
- Keep `domain_agent/__init__.py` as `from . import agent` (so `adk run/web` auto-discovers it).
- Models: default `gemini-flash-latest`; pin a GA version for auditable domains; never
  default to `-preview`; add a `planner` before escalating to a `gemini-pro-*` GA tier.
  All run on the Vertex AI global endpoint. See Model strategy.
- Every agent sets `generate_content_config` (temperature=0 + retry); pipeline steps add
  `include_contents="none"`; wire `after_tool_callback=audit_tool_call`.
- For a coordinator/root with `sub_agents`, put cross-agent invariants in
  `global_instruction` (e.g. "never fabricate a result without calling its tool; never
  downgrade a DENY to REFER"); lock pipeline roots with
  `disallow_transfer_to_parent=True, disallow_transfer_to_peers=True`.
- Ship the eval gate (`tests/*.test.json` + `test_config.json`) — see Evaluation.
- All business constants live at module level in `tools.py`. Never in `prompt.py`. Never as parameters.
- Agent imports must be derived from `tools.py` public symbols — cross-reference before writing `agent.py`.

---

## Evaluation (required — the regression gate)

A modernized credit/approval domain is only trustworthy if a regression suite
catches a silently-downgraded `DENY` or a reordered pipeline. Ship the **native
ADK evaluator** as a build gate (it runs locally, no paid service):

- `tests/<domain>.test.json` — golden cases in the **current ADK `EvalSet` schema**,
  EXACTLY like `tests/orders.test.json`: top-level `eval_set_id` → `eval_cases[]` → each
  case a `conversation[]` whose turns have `user_content`, `final_response`, and
  `intermediate_data.tool_uses` (the **expected tool-call trajectory**, in order, with args),
  plus `session_input`. **Never emit the legacy format** (`turns` / `expected_tool_uses` /
  `initial_session`) — the ADK 2.1 `AgentEvaluator` rejects it with
  *"Samples ... must include 'query' and 'expected_tool_use' keys"* and the eval gate fails.
- `tests/test_config.json` — `{"criteria": {"tool_trajectory_avg_score": 1.0}}`. The
  `1.0` enforces an **exact** tool trajectory: a wrong, reordered, or dropped tool call
  fails the build — the auditability lever. Add `response_match_score` only with a
  **pinned GA model** and stable reference responses (ROUGE on free-form prose drifts
  under the `-latest` alias).
- `tests/test_eval.py` — `await AgentEvaluator.evaluate(agent_module="domain_agent",
  eval_dataset_file_path_or_dir="tests/<domain>.test.json")`.

Run: `pytest tests/` (auto-discovers `test_config.json`) or
`adk eval domain_agent tests/<domain>.test.json --config_file_path tests/test_config.json`
(the CLI does not auto-discover the config — pass it explicitly). For a pipeline
domain, the golden trajectory is the ordered step sequence
(`validate_inputs → evaluate_risk → calculate_pricing → evaluate_decisioning`).

## Observability (decision provenance)

ADK emits OpenTelemetry traces/logs/metrics — for an auditable decision the trace
*is* the provenance. Enable Cloud Trace on deploy (Agent Runtime / Cloud Run / GKE)
and set `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=NO_CONTENT` to keep PII
out of logs (see `.env.example`). The `after_tool_callback` audit log complements
traces with a domain-level record of every tool call and its outcome.

---

## Anti-patterns — never do these

| Anti-pattern | Correct approach |
|---|---|
| `from .tools import evaluate_credit_request` when no such function exists in `tools.py` | Read `tools.py` first; import only what is defined there |
| `MODEL = "o "` — truncated or incomplete model string | Write the full literal: `MODEL = "gemini-3.5-flash"` |
| Receiving `BASE_SPREAD_PCT` as a parameter | `BASE_SPREAD_PCT: float = 5.20` at module level |
| Receiving `exposure_pct` as a pre-computed input | Compute `(current + amount) / equity` inside the tool |
| `"REALESTATE"` when Java uses `"REAL_ESTATE"` | Copy string literals verbatim from the Java source |
| Mapping `Decision.deny()` → `"outcome": "REFER"` | DENY calls → `"DENY"`; referral calls → `"REFER"` |
| "trigger the appropriate outcome" in prompt | Always write explicit outcome: "If X → DENY", "If Y → REFER" |
| Continuing rule evaluation after a DENY | Return immediately after the first DENY — fail-fast |
| Validating only 2 of 6 fields from Java `validateInput` | Validate every field the Java method validated |
| `sys.exit()`, `os._exit()`, or `raise SystemExit` inside a tool | Return `{"status": "error", "error_message": "..."}` |
| `print()` for errors or logging inside a tool | Return errors in dict; use `logging` if needed, never `print()` |
| Tool parameters that accept large lists (transactions, customers) | Tools receive identifiers; data fetched internally |
| No runtime type coercion for numeric parameters | `float(amount_brl)` / `int(tenor_months)` at entry point |
| Raising exceptions from tools | Wrap in try/except; return `{"status": "error", "error_message": str(e)}` |
| Prompt that lists rules but omits tool execution order | Always document the pipeline sequence in `DOMAIN_INSTRUCTION` |
| Omitting `generate_content_config` (relying on the default high temperature) | Set `temperature=0` via `generate_content_config` on every agent |
| Defaulting `MODEL` to a `-preview` model | Default to `gemini-flash-latest`; pin a GA version for auditable domains |
| Switching to a Pro model just for reasoning | Add a `BuiltInPlanner` thinking budget first; escalate to a `gemini-pro-*` GA tier only if needed |
| `output_schema` on a tool-calling agent (unreliable) | `output_schema` only on a terminal, tool-less step; compute with a deterministic tool |
| Centralizing numeric coercion in a callback | Coerce inside each tool — a generic callback would corrupt string codes (e.g. CNAE `"24"`) |
| Shipping a domain agent with no eval set | Add `tests/<domain>.test.json` + `test_config.json` with `tool_trajectory_avg_score=1.0` |
| Unescaped literal `{serasaScore}` / `{companyName}` in an instruction (ADK reads it as state → `KeyError`) | Double every non-state brace: `{{serasaScore}}`; only upstream `output_key`s stay single-brace |
| Pinning a retired/unverified model (`gemini-2.0-flash-001` → runtime 404) | Use `gemini-flash-latest`, or pin only a GA version verified to exist in the target project |
| Legacy eval format (`turns` / `expected_tool_uses` / `initial_session`) | Use the current `EvalSet` schema exactly like `tests/orders.test.json` |
| First pipeline step captures only some request fields → later steps hallucinate a "healthy profile" or stall asking the user | Intake/validate tool returns the **full** validated request; later steps read raw inputs from its `output_key` (e.g. `{validation_result}`) |