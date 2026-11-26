# ADK Agent Archetype

This project is the **target architecture** for modernizing an interactive function of a
legacy system (an online transaction, a screen flow, a service) into a **conversational
agent on Google ADK 2.x**. A code generator receives the business rules extracted from the
legacy source, clones this repository and fills it for one business domain. This document
is the contract the generated project has to meet; the gates of section 8 check it.

The archetype is independent of the legacy technology and of the business: mainframe
(COBOL, FOCUS, CICS, IMS), Java or any other source, in any domain. The domain shipped in
`domain_agent/` (`orders`, invented) is an illustration to be replaced.

Verified with `google-adk` 2.15.1 on Python 3.12 (requires Python 3.11 or later).

---

## 1. The four decisions of this architecture

Everything below follows from four decisions. When a case is not covered, decide by them.

1. **The model talks, code decides.** A legacy rule is deterministic, so it stays
   deterministic: it is plain Python in `domain_agent/domain/`, proven by unit tests that
   run without a model. The model understands what the user wants, chooses the tool and
   words the answer. It never evaluates a rule, computes a value or holds a threshold.
2. **Who acts comes from the session.** The acting user is `tool_context.user_id`, set by
   the platform that authenticated the user. No tool has a parameter for it and nothing
   the user types changes it.
3. **Nothing is written that the user did not see.** A write is prepared, shown and then
   submitted from a draft kept in the session, never from arguments the model sends with
   the write, and never in the turn that prepared it: the user answers in between. A
   decision on someone else's request needs that request shown in an earlier turn.
4. **Every rule says where it comes from.** A rule cites the legacy code, or a document
   of the legacy system, or is declared as an assumption with an open point. Nothing is
   invented silently.

---

## 2. What you generate and what you leave alone

| Path | Owner | Content |
|---|---|---|
| `domain_agent/domain/rules.py` | generator | Constants, validations and the rule catalogue `RULES` |
| `domain_agent/domain/store.py` | generator | Records, the storage port and its in-memory implementation |
| `domain_agent/domain/service.py` | generator | One use case per legacy operation |
| `domain_agent/tools.py` | generator | One thin tool per thing the user can ask for |
| `domain_agent/prompt.py` | generator | The instruction: behaviour, no business values |
| `domain_agent/agent.py` | generator | `root_agent` and `app`: only name, description and tool list change |
| `tests/unit/test_rules.py`, `test_tools.py` | generator | One test per rule; the guards of the tools |
| `tests/eval/<domain>.test.json` | generator | Golden conversations (replaces `orders.test.json`) |
| `tests/eval/test_two_users.py` | generator | Only when a second person decides: the scripted two-user conversation |
| `OPEN_POINTS.md` | generator | What the legacy sources do not state |
| `domain_agent/plugins.py` | archetype | Audit plugin. Do not change |
| `domain_agent/__init__.py` | archetype | `from . import agent`. Do not change |
| `tools/`, `tests/unit/test_conformance.py`, `tests/unit/conftest.py` | archetype | Gates. Do not change (adapt `conftest.py` only to the new store class) |
| `tests/eval/test_eval.py`, `tests/eval/test_config.json` | archetype | Evaluation gate. Do not change (adapt only the store reset) |
| `pyproject.toml`, `.env.example`, `.gitignore` | archetype | Do not change; add a dependency only when a tool needs it |
| `examples/`, `tests/archetype/` | archetype | Reference and self-tests. Leave them or delete both; never copy from them blindly |

The package keeps the name `domain_agent`: ADK resolves sessions by the name of the agent
package, and `App(name=...)` has to equal it (gate C06).

---

## 3. From the legacy system to the agent

A legacy online function is a conversation that was forced into screens. Do not translate
the screens; translate what the user was doing with them.

| In the legacy system | In the agent |
|---|---|
| A menu, an option number, a transaction code | Nothing. The user says what they need; the model picks the tool |
| A screen that asks for fields | The parameters of a tool; the model collects them in conversation |
| Instructions printed on a screen | Behaviour in the instruction, or the docstring of the tool |
| An error message of a screen | A `DomainError` with a stable `code` and a message for the user |
| A function key (confirm, approve, reject, exit) | A turn of the conversation and, when it writes, a tool |
| A validation routine | A function of `domain/rules.py`, called first in the use case |
| A paragraph, procedure or method that does one business operation | One use case in `domain/service.py` |
| A read of a file, table or database | A method of the storage port |
| An update, insert or delete | A method of the storage port, inside one `transaction()` |
| A constant, a limit, a code table | A module constant of `domain/rules.py` |
| The signed-on user (a global variable, a security block) | `tool_context.user_id`, passed to the use case |
| A value kept between screens | Session state (`tool_context.state`), or the draft of a write |
| A second person who approves (maker-checker, four eyes) | A request record and two use cases: create it, decide it |
| A report shown on the terminal | A read tool that returns the rows; the model presents them |
| A batch job, a print step, a file transfer | Not an agent. Out of scope |

Reading guide by source technology (what to look for, not a syntax reference):

- **FOCUS.** `-CRTFORM` is a screen: its input fields are tool parameters and its messages
  are refusals. A chain of `-IF ... GOTO` after a screen is the validation, in that order.
  `TABLE FILE ... IF ...` followed by a test of `&RECORDS` is a read plus an existence or
  duplicate check. `MODIFY FILE ... MATCH ... ON NOMATCH INCLUDE` is an insert-if-absent.
  `-INCLUDE` is a shared routine. `&&` variables are globals of the session (user id,
  mode, dates): identity and configuration, never tool parameters. A menu that only does
  `EX &PROG` is not migrated; each program it calls is a use case. The Master File gives
  the records: field names, aliases, formats and lengths.
- **COBOL (CICS, IMS).** A map or screen section is a screen (as above). `PIC` clauses
  give lengths and decimals; level-88 names are the allowed values of a field, verbatim.
  A paragraph that validates or computes becomes a function; `EVALUATE` keeps its order.
  A file status check, an `ABEND` or a `STOP RUN` becomes a refusal or an error, never a
  process exit. Packed and zoned decimals become exact decimals (section 7).
- **Java and other services.** A public service method is a use case. Enum names and
  reason codes are copied verbatim. A thrown business exception is a `DomainError`.
  `static final` fields are constants of `rules.py`.

---

## 4. Choose the pattern

The extracted rules carry an `application_pattern`. It selects the shape of the agent.

| `application_pattern` | Shape | When |
|---|---|---|
| `dispatcher` | One conversational `Agent` with tools (sections 5, `domain_agent/`) | The user decides what happens next: look up, change, approve |
| `single_operation` | The same, with one or two tools | One query or one computation |
| `pipeline` | A graph `Workflow` with function nodes (section 6, `examples/pipeline_agent/`) | The legacy program runs fixed steps in a fixed order on one request |
| `parallel` | A graph `Workflow` with a fan-out and a join | Independent steps with no shared data |

If the pattern is missing or doubtful, ask: *after the first message, does the user decide
what happens next?* Yes: conversational agent. No, the program does: workflow.

Do not build a pipeline as a chain of model agents that each call one tool. That spends a
model call per step and lets a model skip, repeat or misreport a step. In a workflow the
steps are code and the order is the graph.

---

## 5. The layers of a conversational agent

### 5.1 `domain/rules.py`: constants, validations, catalogue

```python
from __future__ import annotations
from dataclasses import dataclass

ORDER_ID_LENGTH: int = 6  # every fixed value of the legacy source
CANCELLABLE_STATUSES: frozenset[str] = frozenset({"OPEN", "ON_HOLD"})
APPROVAL_THRESHOLD_CENTS: int = 100_000


@dataclass(frozen=True)
class Rule:
    rule_id: str
    statement: str
    source: str


RULES: dict[str, Rule] = {
    rule.rule_id: rule
    for rule in (
        Rule(
            "VAL-001", "An order id is 6 digits; shorter input is zero-filled.", "ORDMNT01:98-125"
        ),
        Rule("BR-005", "A rejection needs a reason.", "DOC:order-approval-screens#APR-02"),
        Rule("BR-006", "A request is applied only if the order is unchanged.", "ASSUMED:OP-001"),
    )
}


class DomainError(Exception):
    def __init__(self, code: str, message: str, rule_id: str | None = None) -> None:
        super().__init__(message)
        self.code, self.message, self.rule_id = code, message, rule_id


def normalize_order_id(raw: str) -> str:
    """VAL-001: the stored form of an order id."""
    text = (raw or "").strip()
    if not text.isdigit() or len(text) > ORDER_ID_LENGTH or int(text) == 0:
        raise DomainError(
            "ORDER_ID_INVALID", "An order id is a number of up to 6 digits.", "VAL-001"
        )
    return text.zfill(ORDER_ID_LENGTH)
```

Rules for this file:

- **Every rule of the extraction is one `Rule`** with the id it has in the extraction. Do
  not merge, split or renumber rules.
- **`source` is one of three forms** (gate C07):
  `<member>:<line>[-<line>]` for legacy code; `DOC:<document>#<anchor>` for a document of
  the legacy system (a screen print, a manual); `ASSUMED:OP-<n>` for behaviour that no
  source states, with OP-<n> described in `OPEN_POINTS.md`. Prefer leaving a behaviour out
  to assuming it; assume only what the function cannot work without.
- **Every fixed value is a module constant here**, with the exact value of the legacy
  source. Never a tool parameter, never in the instruction, never in `tools.py` (C08).
- **A refusal is a `DomainError`**: a stable `code` in `SCREAMING_SNAKE_CASE`, a message
  the user can act on, and the `rule_id` that refused. The audit trail records the rule id.
- This package imports neither ADK nor a model SDK (C04).

### 5.2 `domain/store.py`: records and the storage port

```python
class OrderStore(Protocol):
    def transaction(self) -> AbstractContextManager[None]: ...
    def get_order(self, order_id: str) -> Order | None: ...
    def save_order(self, order: Order) -> None: ...

    # one method per read and per write the use cases need


def get_store() -> OrderStore: ...
def set_store(store: OrderStore) -> None: ...
```

- Records are frozen dataclasses with the fields of the legacy record, in its formats.
- The use cases know the port only. The in-memory implementation serves local runs, unit
  tests and the evaluation, with **invented** seed data.
- `transaction()` makes one use case atomic. In the in-memory store it is a lock that
  restores the previous state on an error; on a database it is a transaction.
- A deployed agent calls `set_store(...)` with an implementation on the system of record.
  A container keeps nothing between restarts and instances share nothing (gate D06).
- Never put real data of the legacy system in the repository: not in the seed, not in
  tests, not in the evaluation set.

### 5.3 `domain/service.py`: one use case per operation

```python
def cancel_order(order_id: str, reason: str, user: str) -> dict[str, Any]:
    """Cancels the order, or creates the request that a second person decides (BR-003)."""
    requester = _user(user)
    store = get_store()
    with store.transaction():
        order, text = _cancellable(order_id, reason)  # validations first, legacy order
        if not needs_approval(order.amount_cents):
            store.save_order(replace(order, status="CANCELLED"))
            return {"applied": True, "order": ...}
        request = store.add_request(CancellationRequest(...))
        return {"applied": False, "request": ...}
```

- One function per business operation of the legacy system; one `transaction()` each.
- **Validations run first and in the order of the legacy source; the first refusal wins**
  (raise at once, do not collect).
- **A use case computes what the legacy routine computed.** If the legacy code derived a
  value from its inputs, the use case derives it: never ask the caller for a derived value.
- The acting user is an argument (`user`), normalized once. The use case decides what that
  user may do (for example: the person who requested cannot decide).
- A write that depends on what was read re-checks it inside the transaction: the record
  may have changed since the user saw it.
- Returns plain data (`dict`, lists, scalars). Never a key named `status`: that is the key
  of the tool envelope.
- For every write operation there is a **preview** use case that runs the same checks and
  writes nothing (`preview_cancellation`). The tool layer needs it (section 5.4).

### 5.4 `tools.py`: thin adapters

```python
import asyncio
from google.adk.tools.tool_context import ToolContext
from .domain import service
from .domain.rules import DomainError

DRAFT = "cancellation_draft"  # session state keys written by the tools


async def _run(tool_context: ToolContext, use_case: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    try:
        result = await asyncio.to_thread(use_case)  # the use case may wait for storage
    except DomainError as error:
        return _error(error.code, error.message, error.rule_id)
    return {"status": "success", "acting_user": tool_context.user_id.upper(), **result}


async def prepare_order_cancellation(
    order_id: str, reason: str, tool_context: ToolContext
) -> dict[str, Any]:
    """Checks a cancellation and keeps it as a draft. Writes nothing.

    Call it when the user asks to cancel an order, then show the user the order, the
    reason and whether a second person will have to approve, and ask for confirmation.

    Args:
        order_id: The id of the order to cancel.
        reason: Why the order is cancelled, in the user's words.

    Returns:
        The draft: order_id, customer, amount_cents, status_before, reason, needs_approval.
    """
    tool_context.state[DRAFT] = None
    result = await _run(tool_context, lambda: service.preview_cancellation(order_id, reason))
    if result["status"] == "success":
        tool_context.state[DRAFT] = {
            "order_id": result["order_id"],
            "reason": result["reason"],
            "invocation_id": tool_context.invocation_id,  # the turn that prepared it
        }
    return result


async def submit_order_cancellation(tool_context: ToolContext) -> dict[str, Any]:
    """Submits the cancellation that was prepared and that the user confirmed. ..."""
    draft = tool_context.state.get(DRAFT)
    if not draft:
        return _error("NO_DRAFT", "There is no cancellation prepared. Prepare it first.")
    if draft["invocation_id"] == tool_context.invocation_id:  # same turn: nobody answered
        return _error("NOT_CONFIRMED", "The user has not answered yet. Show what was prepared.")
    result = await _run(
        tool_context,
        lambda: service.cancel_order(draft["order_id"], draft["reason"], tool_context.user_id),
    )
    if result["status"] == "success":
        tool_context.state[DRAFT] = None
    return result
```

- **A tool decides nothing.** It calls one use case and returns its result. No rule, no
  constant, no computation here.
- **Envelope.** Success: `{"status": "success", "acting_user": ..., <fields>}`. Refusal:
  `{"status": "error", "error_code", "error_message", "rule_id"}`. A tool never raises a
  `DomainError` to the model and never exits the process (C02).
- **A tool is a coroutine that runs the use case in a worker thread**
  (`await asyncio.to_thread(use_case)`). ADK runs a synchronous tool on the event loop,
  so a use case that waits for the system of record would stall every other
  conversation of the process. The domain stays synchronous and simple; session state
  is read and written in the coroutine, not in the thread.
- **Signature** (C03): every parameter typed, no default values, no `*args`/`**kwargs`,
  `tool_context: ToolContext` last, `dict[str, Any]` returned. The docstring is what the
  model reads: say what the tool does, **when to call it**, each argument under `Args:`,
  and what comes back. Do not mention `tool_context`.
- **No identity parameter** (C03): no `user`, `user_id`, `approver`, `requested_by`...
- **Scalars and keys only** (C03): a tool does not take lists of records or free-form
  dictionaries. It takes the key and reads the records itself.
- **Read tools** call the use case directly.
- **Write tools come in pairs**: `prepare_<operation>` (preview, stores the draft with
  the `invocation_id` of its turn) and `submit_<operation>` (no business parameter: it
  submits the draft and clears it). A new `prepare` discards the previous draft.
- **`submit` refuses in the turn of its `prepare`** (`NOT_CONFIRMED`). An invocation is
  one user message and everything the agent does until it answers, so a different
  `invocation_id` means the user wrote something in between. Without this guard a model
  (or text injected into a tool result) can prepare and submit in one turn.
- **Decision tools** (`approve_...`, `reject_...`) refuse unless the session called the
  review tool for that request (`NOT_REVIEWED`) in an earlier turn (`NOT_CONFIRMED`).
- **What a tool returns is data, not instructions.** Records of the legacy system reach
  the model as text; a name or a comment field may contain anything. The guards above
  are what keeps such text from causing a write.
- These guards are in code on purpose: they hold whatever the model does and on every
  surface. ADK also offers `FunctionTool(function, require_confirmation=True)`, which
  pauses for a confirmation in the client; use it in addition only after verifying that
  the target surface renders it.

### 5.5 `prompt.py`: behaviour, not values

```python
STATE_KEYS: frozenset[str] = frozenset()  # state keys the instruction references as {key}

DOMAIN_INSTRUCTION = """\
You help the staff of the Orders domain look up orders and cancel them. ...
How you talk
- Answer in the language the user writes in, briefly and plainly.
- Never show menus, option numbers or function keys.
How you act
- Every fact you state comes from a tool result of this conversation.
- You act only for the signed-in user. ...
- To cancel an order: call prepare_order_cancellation, show ..., ask for confirmation.
  Call submit_order_cancellation only after the user confirmed.
- When a tool returns status "error", tell the user what it says and do not try another
  way around it.
- If the user asks for something no tool does, say that it is not available here.
"""
```

- The instruction says who the agent serves, how it talks, and **when each tool is
  called**. It contains **no limit, threshold, code or rule text**: those reach the user
  through tool results. A value written twice will one day disagree with itself.
- Keep the six behaviours of the example: answer in the user's language; no menus or
  keys; facts only from tool results; act only for the signed-in user; relay a refusal
  without working around it; say when something is not available.
- **Braces** (C05, a generated agent crashed on its first turn because of this): ADK
  replaces `{name}` with `session.state["name"]`. A single-brace name must be declared in
  `STATE_KEYS`. Every other literal brace is doubled: `{{"id": 1}}`.

### 5.6 `agent.py`: the agent and the app

```python
DEFAULT_MODEL = "gemini-3.8-flash"
MODEL = os.environ.get("AGENT_MODEL", DEFAULT_MODEL)

GENERATION = types.GenerateContentConfig(
    temperature=0.0,
    http_options=types.HttpOptions(
        retry_options=types.HttpRetryOptions(initial_delay=1, attempts=3)
    ),
)

root_agent = Agent(
    name="orders_agent",
    model=MODEL,
    description="Looks up orders and cancels them, with approval by a second person.",
    instruction=DOMAIN_INSTRUCTION,
    tools=[find_order, prepare_order_cancellation, submit_order_cancellation, ...],
    generate_content_config=GENERATION,
)

app = App(name="domain_agent", root_agent=root_agent, plugins=[AuditPlugin()])
```

- Change only `name` (`<domain>_agent`), `description` (one sentence a user or a routing
  agent reads) and the tools.
- **Tool contract** (C01): the names imported from `.tools`, the `tools=[...]` list and
  the public functions of `tools.py` are the same set. Derive the import from `tools.py`.
- Do not change `DEFAULT_MODEL`, `GENERATION` or the `App` line (C06). Section 9 explains
  the model.
- Shared instructions for several agents go in `GlobalInstructionPlugin` on the `App`;
  the `global_instruction` field of an agent is deprecated.
- `output_schema` may be combined with `tools` in ADK 2.x (the schema is enforced on the
  final answer only). A conversational agent normally needs none.

### 5.7 `plugins.py` (archetype-owned)

`AuditPlugin` is registered once on the `App`, so every agent and tool is covered. It logs
one record per tool call: user, session, invocation, agent, tool, argument **names**,
status, error code and rule id. Values are not logged. If a tool raises (a defect, storage
down), the plugin answers `{"status": "error", "error_code": "UNAVAILABLE", ...}` so the
user is told that nothing was changed. Business validation never moves into a plugin.

---

## 6. The pipeline pattern: a graph workflow

`examples/pipeline_agent/` is the reference. The model is used at the two ends only.

```python
from google.adk.agents import LlmAgent
from google.adk.events.event import Event
from google.adk.events.event_actions import EventActions
from google.adk.workflow import Workflow

intake = LlmAgent(  # reads the request out of the user's words
    name="intake",
    model=MODEL,
    output_schema=DiscountRequest,
    instruction="Extract the discount request ... Copy the values; do not compute or correct them.",
    generate_content_config=GENERATION,
)


def validate_request(node_input: DiscountRequest) -> Event:  # code
    refusal = validate(node_input)
    if refusal is not None:
        return Event(
            actions=EventActions(route="invalid", state_delta={"decision": refusal.model_dump()})
        )
    return Event(output=node_input.model_dump(), actions=EventActions(route="valid"))


def decide_request(node_input: DiscountRequest) -> Event:  # code
    decision = decide(node_input).model_dump()
    return Event(output=decision, actions=EventActions(state_delta={"decision": decision}))


present = LlmAgent(  # words the result
    name="present",
    model=MODEL,
    include_contents="none",
    instruction="Tell the user the result ... The decision is: {decision}. State its outcome "
    "and reason as given; do not change, soften or add to them.",
    generate_content_config=GENERATION,
)

root_agent = Workflow(
    name="discount_pipeline",
    edges=[
        ("START", intake, validate_request, {"valid": decide_request, "invalid": present}),
        (decide_request, present),
    ],
)
app = App(name="pipeline_agent", root_agent=root_agent)
```

- **Edges are chains.** `(a, b, c)` is a → b → c. A `dict` in a chain is a routing map:
  the node before it continues on the entry whose key equals the route of the `Event` it
  returned. `(a, b, "route")` is **not** valid in this ADK version.
- **A step of the legacy program is a function node**: a plain function whose
  `node_input` is the output of the node before it. With `output_schema` on the model
  agent before it, a typed `node_input` arrives as that Pydantic model.
- **Stop at the first refusal by routing**, as the legacy program did: the refusing node
  returns the route that skips the remaining steps.
- **Results go to the session state** through `state_delta`; the final model agent reads
  them with `{key}`. That key is the one place a single brace appears in its instruction.
- The rules are functions in a `rules.py` with no ADK import, exactly as in section 5.1.
- **Test a workflow on the state its code wrote**, never on the wording of the answer
  (`tests/archetype/test_pipeline_model.py`), and assert the graph itself
  (`tests/archetype/test_pipeline_rules.py`).
- The output of an intermediate model node (the extracted request) is an event of the
  conversation; a client that shows every event shows it.

For `parallel`: `("START", (branch_a, branch_b))` fans out and a `JoinNode` collects the
branches before the next node.

---

## 7. Fidelity to the legacy source

- **Literals verbatim.** Codes, enum names, status values and reason codes are copied
  character for character: case, underscores, spaces. `"REAL_ESTATE"` is not `"REALESTATE"`.
- **Outcomes are not reinterpreted.** A refusal in the legacy source is a refusal; a
  referral to a second person is a referral; a pass is a pass. Read the statement that the
  legacy code executes, not the comment above it. Never soften a refusal into a referral.
- **Boundaries exactly.** `>` is not `>=`. Write a unit test at the boundary and on each
  side of it.
- **Money and decimals are exact.** Use integer minor units (`amount_cents: int`) or
  `decimal.Decimal` with the scale and rounding of the legacy field. Never `float` for a
  value the legacy system held as a decimal.
- **Stored forms.** Keep what the legacy record stores: fixed length, padding, upper case,
  leading zeros. Normalize input to the stored form in `rules.py` and say so in the rule.
- **Order.** If the legacy function lists records in an order, keep it, including the
  collating sequence of the source platform when it differs from the default of Python.
- **Dates** keep the calendar and the windowing of the source (two-digit years, special
  values such as zeros or blanks for "no date").
- **Do not improve.** A rule that looks wrong is copied as it is and listed in
  `OPEN_POINTS.md`. The owner of the system decides, not the generator.
- **Do not fill gaps.** What the extraction does not contain is not implemented. If the
  function cannot work without it, it is an `ASSUMED:OP-<n>` rule with an open point.

---

## 8. Gates

A generated project is done when all four pass. The first three need no model.

| Gate | Command | Proves |
|---|---|---|
| Static | `ruff check . && ruff format --check . && mypy` | Style, imports, strict typing, no `print` |
| Conformance | `python tools/conformance.py` | The rules of this document that a machine can check (C01-C09) |
| Unit | `pytest tests/unit` | Every rule, without a model; the guards of the tools |
| Evaluation | `pytest tests/eval` | With the model: the right tool, arguments and order |

What you write for them:

- **`tests/unit/test_rules.py`**: at least one test per rule id of `RULES`, with the id in
  the test (C07 looks for it). For each rule: the accepted case, the refused case with its
  `code` and `rule_id`, and the boundary. For each write: that a refusal wrote nothing.
- **`tests/unit/test_tools.py`**: no write without a draft; no write in the turn that
  prepared it; the draft is used once; a refused `prepare` discards the previous draft;
  no decision without a review, nor in the turn of the review; the acting user is the
  session user. The tests call the tools with a stand-in context (`conftest.py`).
- **`tests/eval/<domain>.test.json`**: the ADK `EvalSet` schema exactly as in
  `orders.test.json` (`eval_set_id`, `eval_cases[]`, each with `conversation[]` of turns
  holding `user_content`, `final_response` and `intermediate_data.tool_uses`, plus
  `session_input`). `test_config.json` asks for `tool_trajectory_avg_score` 1.0: a wrong,
  missing, extra or reordered tool call fails. Cover: one read; one write with its
  confirmation turn; the user declining (no write tool is called); something that is not
  available (no tool is called). Use messages whose arguments are unambiguous, and
  invented data only.
- The evaluation cases write, so the gate runs each set once on a fresh store.
- **A flow with a second person** cannot be an evaluation case (one user per case). It is
  a scripted conversation of two sessions on one store, `tests/eval/test_two_users.py`,
  that asserts what was written to the store and who decided it.

Conformance checks: **C01** tool contract; **C02** no `print`, `exit`, `input` or process
call; **C03** tool signatures, no identity parameter, no record collections; **C04** the
domain imports no ADK; **C05** instruction braces; **C06** model from configuration,
temperature 0, `App` named after the package; **C07** every rule has a source and a unit
test; **C08** no business value outside `domain/rules.py`; **C09** evaluation set in the
`EvalSet` schema naming real tools only.

---

## 9. Model and configuration

- The model is configuration: `AGENT_MODEL` overrides `DEFAULT_MODEL`. Which versions a
  project can call depends on the project and on the region; a version served on the
  `global` endpoint may not be served on a regional one. `python tools/check_model.py`
  asks the configured backend before anything is deployed.
- `DEFAULT_MODEL` is a dated version name, never an alias (`-latest`) and never a preview
  (C06): an alias can stop resolving or change behaviour without a change in the project.
- Changing the model is a change of behaviour: run the evaluation gate with the new model
  before using it.
- `temperature=0.0` on every agent. It reduces variation; it does not make answers
  identical. The evaluation gate is what holds behaviour.
- A domain that needs more reasoning gets a planner with a bounded thinking budget before
  it gets a larger model.

---

## 10. Deployment

The archetype is a plain ADK project. To deploy it, add the serving code with
`agents-cli` and run the preflight:

```bash
agents-cli scaffold enhance . --agent-directory domain_agent --deployment-target agent_runtime
python tools/check_deploy.py       # D01-D06, then fix what it reports
agents-cli deploy
```

`check_deploy.py` exists because each of these faults passes every local test and fails
at the first call of the deployed agent:

| Check | Fault |
|---|---|
| D01 | The manifest has no deployment target |
| D02 | `enhance` lowered the ADK version in `pyproject.toml` |
| D03 | `google-cloud-aiplatform[agent-engines]` is missing from the dependencies the container installs: the server does not start |
| D04 | The server does not attach the reasoning-engine routes: Gemini Enterprise gets `404 Not Found` |
| D05 | `App.name` is not the package name: sessions are not found |
| D06 | Nothing replaces the in-memory store: data lives in one container |

Also decide before deploying:

- **Identity.** The acting user is whatever the platform passes as user id (Gemini
  Enterprise passes the signed-in e-mail). Who may do what is decided in the use cases
  from that id; if the legacy system had roles, the use case reads them from the system
  of record. An agent that anyone can call with a chosen user id has no access control.
- **Storage.** The store implementation on the system of record, its transactions, and
  the service account that reaches it.
- **Region.** The models available there (`tools/check_model.py`) and where data may go.

---

## 11. Anti-patterns

| Never | Instead | Gate |
|---|---|---|
| A rule, limit or code in the instruction or in a tool | A constant and a function in `domain/rules.py` | C08 |
| A tool parameter for the user, the approver or the role | `tool_context.user_id` | C03 |
| A write tool that takes the values to write from the model | `prepare_...` stores a draft; `submit_...` takes nothing | unit |
| Preparing and submitting a write in one turn | `submit` refuses in the turn of its `prepare` | unit |
| Deciding a request the user was not shown | The review tool first, in an earlier turn | unit |
| A synchronous tool that waits for storage or a service | `async def` tool, use case in `asyncio.to_thread` | review |
| A tool that takes a list of records | The key; the tool reads the records | C03 |
| A parameter with a default value | Required parameters | C03 |
| `print`, `sys.exit`, `os._exit`, `input` | A refusal in the envelope; `logging` | C02 |
| An exception that reaches the model | `DomainError` caught by `_run` | unit |
| A name imported in `agent.py` that `tools.py` does not define | Derive the import from `tools.py` | C01 |
| `{field}` with single braces in an instruction | `{{field}}`, or a declared state key | C05 |
| A model alias or preview as default; a truncated model name | A dated version; `AGENT_MODEL` to override | C06 |
| A rule with no source | Legacy code, a document, or `ASSUMED:OP-<n>` | C07 |
| A rule with no unit test | A test that names the rule id | C07 |
| The old evaluation format (`query` / `expected_tool_use`) | The `EvalSet` schema of `orders.test.json` | C09 |
| `float` for money | Integer minor units or `Decimal` | review |
| A changed literal, a softened refusal, an "improved" rule | Verbatim; the doubt goes to `OPEN_POINTS.md` | review |
| A pipeline of model agents that each call one tool | A `Workflow` with function nodes | review |
| `global_instruction` on an agent | `GlobalInstructionPlugin` on the `App` | review |
| Real data of the legacy system in seed, tests or evaluation | Invented data | review |
| Menus, option numbers or function keys in the conversation | The user's own words | evaluation |

---

## 12. Order of work for the generator

1. Read the extracted rules. List the operations, the records, the rules with their ids
   and sources, and what the sources do not state.
2. Choose the pattern (section 4).
3. Write `domain/rules.py`: constants, `RULES`, validations.
4. Write `domain/store.py`: records, port, in-memory store with invented data.
5. Write `domain/service.py`: one use case per operation, a preview for each write.
6. Write `tests/unit/test_rules.py`. Run `pytest tests/unit`: the rules are proven before
   any agent code exists.
7. Write `tools.py`, then `agent.py` (import derived from `tools.py`), then `prompt.py`.
8. Write `tests/unit/test_tools.py` and `tests/eval/<domain>.test.json`; delete
   `tests/eval/orders.test.json`. Rewrite `tests/eval/test_two_users.py` for the domain
   if a second person decides, otherwise delete it.
9. Write `OPEN_POINTS.md`.
10. Run the gates of section 8 in order. Fix the code, never the gate.
