# ADK Agent Archetype

This project is the **target architecture** for modernizing an interactive function of a
legacy system (an online transaction, a screen flow, a service) into a **conversational
agent on Google ADK 2.x**. A code generator receives the business rules extracted from the
legacy source, clones this repository and fills it for one business domain. This document
is the contract the generated project has to meet; the gates of section 8 check it.

The archetype is independent of the legacy technology and of the business: mainframe
(COBOL, FOCUS, CICS, IMS), Java or any other source, in any domain. The domain shipped in
`domain_agent/` (`orders`, invented) is an illustration to be replaced.

Verified with `google-adk` 2.15.1 on Python 3.12 (requires Python 3.11 or later). ADK
changes between minor versions: every statement about ADK below was checked against that
version, and the dependency is pinned to it.

---

## 1. The four decisions of this architecture

Everything below follows from four decisions. When a case is not covered, decide by them.

1. **The model talks, code decides.** A legacy rule is deterministic, so it stays
   deterministic: it is plain Python in `domain_agent/domain/`, proven by unit tests that
   run without a model. The model understands what the user wants, chooses the tool and
   words the answer. It never evaluates a rule, computes a value or holds a threshold.
2. **Who acts comes from the session.** The acting user is the user of the session, set by
   the platform that authenticated the person. The toolkit hands it to the use case; no
   tool has a parameter for it and nothing the user types changes it.
3. **A write is the one the user was shown, answered and made once.** A write is previewed
   and shown. It runs only when the user sent exactly one message after the preview, only
   if what was shown still holds, and at most once. A decision on someone else's request
   follows the same rule after that request was shown. What code cannot know is whether
   the user's message meant yes: the model reads that.
4. **Every rule says where it comes from.** A rule cites the legacy code, or a document of
   the legacy system, or is declared as an assumption with an open point. Nothing is
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
| `domain_agent/agent.py` | generator | `root_agent` and `app`: name, description and tool list change |
| `domain_agent/wiring.py` | generator | Which store the agent is connected to |
| `tests/conftest.py` | generator | The fresh store of each test: adapt the store class |
| `tests/unit/test_rules.py` | generator | At least one test per rule |
| `tests/unit/test_flows.py` | generator | The flows of the domain through the real tools, without a model |
| `tests/eval/<domain>.test.json` | generator | Golden conversations (replaces `orders.test.json`) |
| `tests/eval/test_two_users.py` | generator | Only when a second person decides: the two-user conversation |
| `OPEN_POINTS.md` | generator | What the legacy sources do not state |
| `domain_agent/domain/base.py` | archetype | The shared types and what makes a write safe |
| `domain_agent/toolkit.py` | archetype | Envelope, acting user, confirmation of writes |
| `domain_agent/plugins.py` | archetype | Audit plugin |
| `domain_agent/__init__.py` | archetype | `from . import agent` |
| `tools/`, `conftest.py`, `tests/support/` | archetype | Gates and test support |
| `tests/unit/test_toolkit.py`, `test_base.py`, `test_replay.py`, `test_conformance.py` | archetype | Tests that hold for any domain |
| `tests/eval/test_eval.py`, `tests/eval/test_config.json` | archetype | Evaluation gate |
| `pyproject.toml`, `.env.example`, `.gitignore` | archetype | Add a dependency only when an adapter needs it; set `[project].name` |
| `examples/`, `tests/archetype/` | archetype | Reference and self-tests of the archetype. Leave them or delete both |

Archetype files are listed with their digests in `ARCHETYPE_OWNED.sha256`; the gate fails
when one was changed (C12). Do not regenerate that file.

The package is named `domain_agent`. When several agents share an environment (a session
database, a registry, a log), rename the folder to `<domain>_agent`: ADK resolves sessions
by the package name, `App(name=...)` has to equal it (C06), and the gates find the package
by its `agent.py`. Then update the imports of the tests and `packages` in `pyproject.toml`.

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
| A record held or locked while the user looks at a screen | The confirmation: the write is refused if what was shown changed |
| A constant, a limit, a code table | A module constant of `domain/rules.py` |
| The signed-on user (a global variable, a security block) | The user of the session, given to the use case by the toolkit |
| A value kept between screens | What the toolkit keeps for the confirmation; nothing else |
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
  `static final` fields are constants of `rules.py`; `BigDecimal` stays exact.

---

## 4. Choose the pattern

The extracted rules carry an `application_pattern`. It selects the shape of the agent.

| `application_pattern` | Shape | When |
|---|---|---|
| `dispatcher` | One conversational `Agent` with tools (section 5, `domain_agent/`) | The user decides what happens next: look up, change, approve |
| `single_operation` | The same, with one or two tools | One query or one computation |
| `pipeline` | A graph `Workflow` with function nodes (section 6, `examples/pipeline_agent/`) | The legacy program runs fixed steps in a fixed order on one request and answers |
| `parallel` | A graph `Workflow` with a fan-out and a join | Independent steps with no shared data |

If the pattern is missing or doubtful, ask: *after the first message, does the user decide
what happens next?* Yes: conversational agent. No, the program does: workflow.

- **A function that writes is a conversational agent**, whatever its pattern says: a write
  needs the confirmation of section 5.5, and a workflow of this archetype decides and
  answers without writing.
- **Do not build a pipeline as a chain of model agents that each call one tool.** That
  spends a model call per step and lets a model skip, repeat or misreport a step.
- **Many operations.** One agent holds the operations of one screen family (about twenty
  tools at most). A larger domain is several agents, each a package of this shape, under a
  root agent that lists them in `sub_agents`. Never wrap an agent in `AgentTool` and never
  set `mode=` on one: each such call is a session or an invocation of its own, and no
  write can be confirmed through it (C06).

---

## 5. The layers of a conversational agent

### 5.1 `domain/base.py` (archetype)

The types every domain shares. Import them; do not redefine or change them.

```python
from .base import Confirmation, DomainError, Rule, as_text, authorize, record, utc_now
```

- `Rule(rule_id, statement, source)`: one entry of the catalogue.
- `DomainError(code, message, rule_id=None)`: a refusal. `rule_id` names the business rule
  that refused; a refusal that enforces no business rule (missing input, an unknown key)
  has none.
- `Confirmation`, `authorize`, `record`: how a write stays the one that was shown and
  happens once (5.4).
- `as_text(raw, what)`: the text a caller gave, or a refusal. A model may send a number
  where text is expected.

### 5.2 `domain/rules.py`: constants, validations, catalogue

```python
from .base import DomainError, Rule, as_text

ORDER_ID_LENGTH: int = 6  # every fixed value of the legacy source, once
APPROVAL_THRESHOLD_CENTS: int = 100_000

RULES: dict[str, Rule] = {
    rule.rule_id: rule
    for rule in (
        Rule(
            "VAL-001",
            "An order id is a number of up to ORDER_ID_LENGTH digits, not zero.",
            "ORDMNT01:98-125",
        ),
        Rule("BR-005", "A rejection needs a reason.", "DOC:order-approval-screens#APR-02"),
        Rule("BR-006", "A request is applied only if the order is unchanged.", "ASSUMED:OP-001"),
    )
}


def normalize_order_id(raw: object) -> str:
    """VAL-001: the stored form of an order id."""
    text = as_text(raw, "the order id").strip()
    digits = text.isascii() and text.isdigit()
    if not digits or len(text) > ORDER_ID_LENGTH or int(text) == 0:
        raise DomainError(
            "ORDER_ID_INVALID", "An order id is a number of up to 6 digits.", "VAL-001"
        )
    return text.zfill(ORDER_ID_LENGTH)
```

- **Every rule of the extraction is one `Rule`** with the id it has in the extraction. Do
  not merge, split or renumber rules. Its three arguments are string literals (C07).
- **`source` is one of three forms** (C07):
  `<member>:<line>[-<line>][,<line>-<line>]` for legacy code, where the member is the name
  or path of the source as delivered (`ORDMNT01:98-125`,
  `src/main/java/com/acme/OrderService.java:77-90`); `DOC:<document>#<anchor>` for a
  document of the legacy system; `ASSUMED:OP-<n>` for behaviour that no source states,
  with OP-<n> described in `OPEN_POINTS.md`. Prefer leaving a behaviour out to assuming
  it; assume only what the function cannot work without.
- **Every fixed value is a module constant here**, with the exact value of the legacy
  source: limits, lengths, code sets, page sizes. Never a tool parameter, never in the
  instruction or in a tool (C08). A rule statement names the constant, not its value.
- **A normalizer takes `object` and returns the stored form or refuses.** Check the
  character set of the legacy record: `str.isdigit()` and `str.isprintable()` accept
  characters the legacy field never held; test `isascii()` or the exact range.
- **How user ids are compared is a rule** (`normalize_user`, `same_user`), with its source.
  A stored id may be padded or in another case; when the platform's id (an e-mail) is not
  the legacy id, the store maps one to the other and refuses an unmapped user.
- **Values that are shown are formatted here, by code** (`format_amount`). The model
  repeats them; it does not convert, round or add a currency.
- No `float` anywhere in the domain (C08). This package imports neither ADK, nor a model
  SDK, nor the agent layer (C04).

### 5.3 `domain/store.py`: records and the storage port

```python
class OrderStore(WriteJournal, Protocol):
    def transaction(self) -> AbstractContextManager[None]: ...
    def get_order(self, order_id: str) -> Order | None: ...
    def save_order(self, order: Order) -> None: ...

    # one method per read and per write the use cases need


def get_store() -> OrderStore: ...
def set_store(store: OrderStore) -> None: ...
```

- Records are frozen dataclasses with the fields of the legacy record, in its formats.
- The port extends `WriteJournal` (`find_write`, `add_write`): the store keeps a record of
  every confirmed write, in the transaction of the write.
- Name the methods that change the store `save_`, `add_`, `delete_`, `remove_`, `update_`,
  `put_` or `insert_`: the gate recognises a write by them (C11).
- **`transaction()` is atomic and isolated.** A use case checks and then writes ("no
  pending request", then "add one"): two of them at once must not both pass the check. On
  a database that is a serializable transaction or a lock on what was read; the in-memory
  store uses one lock. `tests/unit/test_base.py` checks it on any implementation.
- The in-memory implementation serves local runs, unit tests and the evaluation, with
  **invented** seed data. Never put real data of the legacy system in the repository.
- `wiring.py` connects the store. A deployed agent connects an adapter of the system of
  record there (`domain_agent/adapters/`, which may use any client library).

### 5.4 `domain/service.py`: one use case per operation

```python
def _cancellation(store: OrderStore, order_id: object, reason: object) -> tuple[Order, dict[str, Any]]:
    """The order and what a cancellation of it shows, or the refusal."""
    order = ...  # validations and rules, in the order of the legacy source
    return order, {"order_id": order.order_id, "amount": format_amount(order.amount_cents), ...}


def preview_cancellation(order_id: object, reason: object) -> dict[str, Any]:
    store = get_store()
    with store.transaction():
        return _cancellation(store, order_id, reason)[1]


def cancel_order(order_id: object, reason: object, user: object, confirmation: Confirmation) -> dict[str, Any]:
    requester = normalize_user(user)
    store = get_store()
    with store.transaction():
        order, shown = _cancellation(store, order_id, reason)  # the same checks as the preview
        authorize(store, confirmation, shown)  # last check before the first change
        store.save_order(replace(order, status="CANCELLED"))
        record(store, confirmation, operation="cancel_order", target=order.order_id, user=requester)
        return {"applied": True, "order": ...}
```

- One function per business operation of the legacy system; one `transaction()` each.
- **Validations run first and in the order of the legacy source; the first refusal wins**
  (raise at once, do not collect).
- **A use case computes what the legacy routine computed.** If the legacy code derived a
  value from its inputs, the use case derives it: never ask the caller for a derived value.
- **A write is a pair that shares one private function**: `preview_<operation>` returns
  what the user is shown and writes nothing; the write runs the same function again
  inside its transaction and passes the result to `authorize`. So the write is refused
  (`CHANGED_SINCE_SHOWN`) when the record changed after the user saw it: another amount,
  another status, another branch of the rule.
- **A write takes `user` and `confirmation`** and calls `authorize(...)` after its checks
  and `record(...)` after its changes (C11). `authorize` also refuses a second write of
  the same confirmation (`ALREADY_SUBMITTED`).
- **A decision** (approve, reject) is a write too: its preview is the review use case,
  which returns the request with the record as it is now.
- The acting user is the argument `user`, normalized once. The use case decides what that
  user may do (for example: the person who requested cannot decide).
- **What a use case returns is what the user is shown**, and it crosses to the model and
  to the session as JSON: text, integers, booleans, lists and dictionaries of them. No
  `Decimal`, no `date`, no dataclass: format them here. A list that was cut at a limit
  says so (`total_matches`, `more`).

### 5.5 `tools.py`: one tool per thing the user can ask for

```python
from . import toolkit
from .domain import service


async def find_order(query: str, tool_context: ToolContext) -> dict[str, Any]:
    """Finds orders by order id or by a part of the customer name. ..."""
    return await toolkit.read(tool_context, lambda user: service.find_orders(query))


async def prepare_order_cancellation(
    order_id: str, reason: str, tool_context: ToolContext
) -> dict[str, Any]:
    """Checks a cancellation and keeps it for confirmation. Writes nothing.

    Call it when the user asks to cancel an order. Then show the user the order, the
    reason and whether a second person will have to approve, and ask for confirmation.

    Args:
        order_id: The id of the order to cancel.
        reason: Why the order is cancelled, in the user's words.

    Returns:
        What will be done: order_id, customer, amount, status, reason and needs_approval.
    """
    return await toolkit.prepare(
        tool_context, "cancel_order", lambda user: service.preview_cancellation(order_id, reason)
    )


async def submit_order_cancellation(tool_context: ToolContext) -> dict[str, Any]:
    """Submits the cancellation that was prepared, after the user confirmed it. ..."""
    return await toolkit.submit(
        tool_context,
        "cancel_order",
        lambda user, shown, confirmation: service.cancel_order(
            shown["order_id"], shown["reason"], user, confirmation
        ),
    )


async def review_cancellation_request(request_id: int, tool_context: ToolContext) -> dict[str, Any]:
    """Shows one cancellation request in full. Required before approving or rejecting it. ..."""
    return await toolkit.review(
        tool_context,
        "cancellation_request",
        request_id,
        lambda user: service.review_request(request_id, user),
    )


async def approve_cancellation_request(
    request_id: int, tool_context: ToolContext
) -> dict[str, Any]:
    """Approves a pending cancellation request: the order is cancelled. ..."""
    return await toolkit.decide(
        tool_context,
        "cancellation_request",
        request_id,
        lambda user, confirmation: service.approve_request(request_id, user, confirmation),
    )
```

A tool decides nothing and guards nothing. It names the use case that answers it and
hands it to the toolkit (`toolkit.py`, archetype-owned), which gives every agent the same
guarantees, tested once in `tests/unit/test_toolkit.py`:

| Toolkit entry | For | What it guarantees |
|---|---|---|
| `read(tool_context, use_case)` | A use case that only reads | The acting user, the envelope |
| `prepare(tool_context, operation, preview)` | The preview of a write | Keeps what was shown for `submit` |
| `submit(tool_context, operation, write)` | The write | Runs only when the user sent exactly one message since the preview |
| `review(tool_context, subject, item, show)` | Showing an item to decide | Keeps which item and what was shown |
| `decide(tool_context, subject, item, decision)` | A decision on that item | The same rule as `submit`, for that item |

- **The use-case callable receives the acting user** as its first parameter, named `user`,
  and passes it to the use case (C11). A tool never reads `tool_context`: not the user, not
  the state, not the session (C10).
- **The envelope.** Success: `{"status": "success", "acting_user": ..., "result": {...}}`.
  Refusal: `{"status": "error", "error_code", "error_message", "rule_id"}`.
- **`submit` takes no parameter from the model** (C11): the write receives what the
  preview returned (`shown`) and takes its arguments from it. `prepare` and `submit` of one
  write use the same operation name; `review` and `decide` the same subject (C11).
- **When `submit` and `decide` refuse.** `NOTHING_PREPARED` / `NOT_REVIEWED`: nothing waits
  for this confirmation. `NOT_CONFIRMED`: it is still the turn of the preview, nobody
  answered. `CONFIRMATION_EXPIRED`: the user wrote more than one message since. Any other
  tool call drops what waited. The instruction therefore says: call `submit` only when the
  user's next message confirms, and before any other tool.
- **Signature** (C03): `async def`; every parameter typed `str`, `int`, `bool`, `list[str]`
  or `list[int]`; no default value, no `*args`/`**kwargs`; `tool_context: ToolContext`
  last; `dict[str, Any]` returned. An amount or a date is a `str` parameter that
  `rules.py` parses: ADK does not convert arguments to `Decimal` or `date`, and passes
  whatever JSON value the model sent.
- **The docstring is what the model reads**: what the tool does, **when to call it**, each
  argument under `Args:`, what comes back. Do not mention `tool_context`.
- **A record with many fields** is changed one field per confirmation:
  `prepare_<record>_change(key, field, new_value)`, with the allowed fields a constant of
  `rules.py` and the before and after computed by the preview. Do not write a tool with
  one parameter per field of a screen: the model would have to send back every value the
  user did not touch.
- **A decision tool takes the item and what the decision itself needs** from the user's
  message (the reason of a rejection). Everything else comes from what was reviewed.
- **What a tool returns is data, not instructions.** Records of the legacy system reach
  the model as text; a name or a comment may contain anything. The toolkit is what keeps
  such text from causing a write.

### 5.6 `prompt.py`: behaviour, not values

```python
DOMAIN_INSTRUCTION = """\
You help the staff of the Orders domain look up orders and cancel them. ...

How you talk
- Answer in the language the user writes in, briefly and plainly.
- Never show menus, option numbers or function keys.
- Repeat codes, names, dates and amounts exactly as a tool returned them.

How you act
- Every fact you state comes from a tool result of this conversation.
- You act only for the signed-in user. ...
- To cancel an order: call prepare_order_cancellation, show ..., ask for confirmation.
  Call submit_order_cancellation only when the user's next message confirms it, and call
  it before any other tool. If the user says anything else, do not submit.
- When a tool returns status "error", tell the user what it says, do what it asks for,
  and do not try another way around it.
- If the user asks for something no tool does, say that it is not available here.
"""
```

- The instruction says who the agent serves, how it talks, and **when each tool is
  called**. It contains **no limit, threshold, code or rule text**: those reach the user
  through tool results. A value written twice will one day disagree with itself.
- Keep the behaviours of the example: the user's language; no menus or keys; values
  repeated as returned; facts only from tool results; only for the signed-in user; the
  confirmation in the user's next message; a refusal relayed, not worked around; what is
  not available.
- **The text is passed as `static_instruction`** (C05). ADK sends it to the model as it
  is: braces, JSON examples and field names need no escaping. Do not pass a text as
  `instruction=`: there ADK substitutes `{name}` from the session state, **doubling the
  braces does not prevent it**, and a name that is not a state key stops the agent on its
  first turn (`KeyError: Context variable not found`).
- An instruction that needs a value of the session is a function of `prompt.py` that
  receives the context and returns the text (`instruction=<function>`); see section 6.

### 5.7 `agent.py`: the agent and the app

```python
wiring.configure()

DEFAULT_MODEL = "gemini-3.8-flash"
MODEL = os.environ.get("AGENT_MODEL", DEFAULT_MODEL)
TEMPERATURE = float(os.environ.get("AGENT_TEMPERATURE", "0.0"))
GENERATION = types.GenerateContentConfig(
    temperature=TEMPERATURE,
    http_options=types.HttpOptions(
        retry_options=types.HttpRetryOptions(initial_delay=1, attempts=3)
    ),
)

root_agent = Agent(
    name="orders_agent",
    model=MODEL,
    description="Looks up orders and cancels them, with approval by a second person.",
    static_instruction=DOMAIN_INSTRUCTION,
    tools=[find_order, prepare_order_cancellation, submit_order_cancellation, ...],
    generate_content_config=GENERATION,
)

app = App(name="domain_agent", root_agent=root_agent, plugins=[AuditPlugin()])
```

- Change `name` (`<domain>_agent`), `description` (one sentence a user or a routing agent
  reads) and the tools. You may add a `planner`, sub-agents and further plugins.
- Do not change (C06): `DEFAULT_MODEL`, `MODEL`, `TEMPERATURE`, `GENERATION`; `model=MODEL`
  and `generate_content_config=GENERATION` on every agent; one `App` named after the
  package with `AuditPlugin()`; the name `root_agent`.
- **Tool contract** (C01): the names imported from `.tools`, the `tools=[...]` list and
  the public functions of `tools.py` are the same set. Derive the import from `tools.py`.
- Shared text for several agents goes in `GlobalInstructionPlugin` on the `App`; the
  `global_instruction` field of an agent is deprecated (C06).

### 5.8 `plugins.py` and the two records of what happened (archetype)

- **The audit log.** `AuditPlugin`, registered on the `App`, writes one JSON line per tool
  call on the standard error stream: user, session, invocation, agent, tool, argument
  **names**, status, error code, rule id. Values are not logged. It has an output of its
  own, because Python drops INFO records unless logging was configured.
- **The record of writes.** `record(...)` stores who did what on which key, with the key
  of the confirmation, in the transaction of the write. This one is durable and is the
  one to rely on.
- If a tool raises (a defect, storage that is down), the plugin answers
  `OUTCOME_UNKNOWN`: the tool may have written before it failed, so the user is told to
  look at the current state. Business validation never moves into a plugin.

---

## 6. The pipeline pattern: a graph workflow

`examples/pipeline_agent/` is the reference: `agent.py`, `prompt.py`, `domain/rules.py`.
The model is used at the two ends only.

```python
class Extracted(BaseModel):
    """What the intake reads out of the user's message: text as written, null when absent."""

    segment: str | None = Field(
        default=None,
        description=f"Customer segment: the code of {sorted(SEGMENTS)} that means what the user wrote, or null.",
    )
    order_amount: str | None = Field(
        default=None, description="Order amount exactly as the user wrote it, or null."
    )
    years_as_customer: int | None = Field(
        default=None, description="Whole years as a customer, or null."
    )


intake = LlmAgent(  # reads the request out of the user's words
    name="intake",
    model=MODEL,
    instruction=intake_instruction,  # a function of prompt.py
    output_schema=Extracted,
    generate_content_config=GENERATION,
)


def collect_request(ctx: Context, node_input: Extracted) -> Event:  # code
    """Keeps what the user gave so far; nothing is decided on a missing field."""
    given = {key: value for key, value in node_input.model_dump().items() if value is not None}
    known = {**(ctx.state.get("request") or {}), **given}
    missing = missing_fields(known)
    if missing:
        decision = Decision("INCOMPLETE", "VAL-004", "FIELDS_MISSING", missing=tuple(missing))
        return _decided(decision, "incomplete", request=known)
    return Event(
        output=known, actions=EventActions(route="complete", state_delta={"request": known})
    )


def validate_request(node_input: dict[str, Any]) -> Event:  # code
    checked = check(node_input)
    if isinstance(checked, Decision):
        return _decided(checked, "invalid")
    return Event(output=node_input, actions=EventActions(route="valid"))


present = LlmAgent(  # words the result
    name="present",
    model=MODEL,
    instruction=present_instruction,  # reads the decision from the state
    include_contents="none",
    generate_content_config=GENERATION,
)

root_agent = Workflow(
    name="discount_pipeline",
    edges=[
        ("START", intake, collect_request, {"complete": validate_request, "incomplete": present}),
        (validate_request, {"valid": decide_request, "invalid": present}),
        (decide_request, present),
    ],
)
```

- **Edges are chains.** `(a, b, c)` is a → b → c. A `dict` in a chain is a routing map:
  the node before it continues on the entry whose key equals the route of the `Event` it
  returned. `(a, b, "route")` is **not** valid in this ADK version.
- **A step of the legacy program is a function node** (C13): a plain function whose
  `node_input` is the output of the node before it. With `output_schema` on the model
  agent before it, a typed `node_input` arrives as that Pydantic model.
- **The intake copies numbers and maps codes.** Amounts, percentages and dates are text
  fields "as the user wrote them", parsed by `rules.py` into exact values. A field with a
  list of codes names the codes in its description (built from the constant of
  `rules.py`), so the user's word, in any language, becomes the legacy code.
- **A field the user did not give is null, not a default.** Every field of the schema is
  optional with `default=None` (a null of the model may arrive as an absent key). A code
  node checks what is missing, keeps what is known in the state and routes to a question.
  Never let a rule run on a value the user did not give.
- **Stop at the first refusal by routing**, as the legacy program did: the refusing node
  returns the route that skips the remaining steps.
- **Results go to the session state** through `state_delta`. The instruction of a model
  node is a function of `prompt.py` that reads the state and the user's message
  (`context.state`, `context.user_content`) and returns the text. A model node sees its
  node input, not the conversation.
- **Test a workflow on the state its code wrote**, never on the wording of the answer:
  without a model, with the two model nodes scripted
  (`tests/archetype/test_pipeline_rules.py`), and with the model
  (`tests/archetype/test_pipeline_model.py`). A generated pipeline has both, the second as
  `tests/eval/test_pipeline_model.py` (C13).
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
- **Boundaries exactly.** `>` is not `>=`. Write a unit test at the boundary and one step
  past it.
- **Money and decimals are exact.** Inside the domain: integer minor units
  (`amount_cents: int`) or `decimal.Decimal` with the scale and rounding of the legacy
  field. At the tool boundary: text in, text out, parsed and formatted by `rules.py`.
- **Stored forms.** Keep what the legacy record stores: fixed length, padding, upper case,
  leading zeros, and the character set of the record. Normalize input to the stored form
  in `rules.py` and say so in the rule.
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
| Conformance | `python tools/conformance.py` | The rules of this document that a machine can check |
| Unit | `pytest -m "not model"` | Every rule; the flows through the real tools; the toolkit; the golden set replayed |
| Evaluation | `pytest -m model` | With the model: the right tool, arguments and order |

What you write for them:

- **`tests/unit/test_rules.py`**: at least one test per rule id of `RULES`, with the id in
  the name or the docstring of the test (C07; a comment does not count). For each rule:
  the accepted case, the refused case with its `code` and `rule_id`, and the boundary and
  one step past it. For each write: that a refusal wrote nothing, and that a record
  changed after the preview is not written (`CHANGED_SINCE_SHOWN`).
- **`tests/unit/test_flows.py`**: each flow of the domain through the real tools, with
  the scripted model of `tests/support/scripted.py` (no model, no credentials), checked
  on what was written to the store and on the record of the write.
- **`tests/eval/<domain>.test.json`**: the ADK `EvalSet` schema exactly as in
  `orders.test.json` (`eval_set_id`, `eval_cases[]`, each with `conversation[]` of turns
  holding `user_content`, `final_response` and `intermediate_data.tool_uses`, plus
  `session_input`). `test_config.json` asks for `tool_trajectory_avg_score` 1.0: a wrong,
  missing, extra or reordered tool call fails. The set has to cover (C09): every tool;
  for an agent that writes, a confirmation (a `prepare_x` turn, then `submit_x`) and a
  refusal by the user (a `prepare_x` turn, then a turn with no tool call); and something
  no tool does (a case with no tool call). Use messages whose arguments are unambiguous,
  and invented data only.
- **A flow with a second person** cannot be an evaluation case (one user per case): seed
  the in-memory store with a pending request of another user for the evaluation, and
  write `tests/eval/test_two_users.py`, a conversation of two sessions that asserts what
  was written and who decided it.

What the archetype gives, for any domain: `test_toolkit.py` (the guards, through the real
ADK runner), `test_base.py` (the contract of the store), `test_replay.py` (the golden set
replayed without a model: every tool it names exists and accepts its arguments, and every
write it expects is one the toolkit lets through), `test_eval.py` (the evaluation, one
case at a time on a fresh store).

The evaluation gate fails when no backend is configured; it does not pass by not running
(`EVAL_GATE=off` skips it on purpose). It checks the tool trajectory. It does not judge
the wording, the language or the amounts of an answer: read those in a review.

Conformance checks: **C00** the files exist and parse; **C01** tool contract; **C02** no
`print`, `exit`, `input`, process call or `subprocess`; **C03** tool signatures;
**C04** the domain imports no ADK and no agent layer; **C05** no text as `instruction=`;
**C06** model, temperature and app from the archetype, no `AgentTool`, no `mode=`;
**C07** every rule has a literal source and a named test; **C08** no number in the tools
or the instruction, no `float` in the domain; **C09** the evaluation set; **C10** a tool
only delegates to the toolkit; **C11** a write takes a confirmation, runs in `submit` or
`decide`, with the user the toolkit gives; **C12** the files of the archetype are
unchanged; **C13** a pipeline has function nodes and a state test.

---

## 9. Model and configuration

- The model is configuration: `AGENT_MODEL` overrides `DEFAULT_MODEL`. Which versions a
  project can call depends on the project and on the region; a version served on the
  `global` endpoint may not be served on a regional one. `python tools/check_model.py`
  asks the configured backend before anything is deployed.
- `DEFAULT_MODEL` is the name of a version, never an alias (`-latest`) and never a preview
  (C06): an alias can stop resolving or change behaviour without a change in the project.
- Changing the model is a change of behaviour: run the evaluation gate with the new model
  before using it.
- `AGENT_TEMPERATURE` is 0 by default. It reduces variation; it does not make answers
  identical. A model family may document another value: follow its model card and let the
  evaluation decide.
- A domain that needs more reasoning gets a planner with a bounded thinking budget before
  it gets a larger model.

---

## 10. Deployment

The archetype is a plain ADK project. To deploy it, connect the system of record in
`wiring.py`, add the serving code with `agents-cli` and run the preflight:

```bash
agents-cli scaffold enhance . --agent-directory domain_agent --deployment-target agent_runtime
python tools/check_deploy.py       # D01-D08, then fix what it reports
agents-cli deploy
```

`check_deploy.py` exists because each of these faults passes every local test:

| Check | Fault |
|---|---|
| D01 | The manifest has no deployment target |
| D02 | `enhance` lowered the ADK version in `pyproject.toml`, or the lock installs an older one |
| D03 | `google-cloud-aiplatform[agent-engines]` is missing: the server does not start |
| D04 | On Agent Runtime the server does not attach the reasoning-engine routes: Gemini Enterprise gets `404 Not Found` |
| D05 | `App.name` is not the package name: sessions are not found |
| D06 | `wiring.py` still connects an in-memory store |
| D07 | On Cloud Run or GKE the sessions are in memory: another instance does not find what waits for a confirmation |
| D08 | On Cloud Run or GKE the developer UI is served |

What to decide before deploying:

- **The trust boundary.** Every guarantee of section 1 assumes that the platform, not the
  caller, sets the user id of the session. Agent Runtime and Gemini Enterprise do
  (Gemini Enterprise passes the signed-in e-mail). The ADK server itself does not: its
  endpoints take the user id, the session state and the events from the request. Never
  expose it without a layer that authenticates the caller, fixes the user id and rejects
  session state from outside. A caller who can set the session state can skip a preview;
  it still cannot write anything but what a preview would show now, nor twice.
- **Identity.** Who may do what is decided in the use cases from the user id. If the
  legacy system had roles, the use case reads them from the system of record; if the
  legacy user ids differ from the platform's, the store maps them.
- **Storage.** The adapter of the system of record, the isolation of its transactions
  (5.3), and the service account that reaches it. Run `tests/unit/test_base.py` against it.
- **Sessions.** A session keeps every tool result (records of the system of record) for
  as long as it exists: choose the session service and its retention accordingly.
- **Telemetry.** Set `ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS=false` unless traces may hold
  the data (`agents-cli deploy` sets it; other deployments do not).
- **Region.** The models available there (`tools/check_model.py`) and where data may go.
- **Not supported.** Live (bidirectional) sessions, agents wrapped in `AgentTool`, and
  task-mode agents: the confirmation of a write counts the messages of the user in one
  session. ADK's `require_confirmation` is another way to confirm a write, in a client
  that renders it; do not combine it with `toolkit.submit` (the confirmation resumes the
  turn of the preview and is refused).

---

## 11. Anti-patterns

| Never | Instead | Gate |
|---|---|---|
| A rule, limit or code in the instruction or in a tool | A constant and a function in `domain/rules.py` | C08 |
| A text as `instruction=`, with or without doubled braces | `static_instruction=`, or a function of `prompt.py` | C05 |
| A tool that reads `tool_context` (user, state, session) | The toolkit; the callable receives `user` | C10 |
| A tool parameter for the user, the approver or the role | The `user` the toolkit gives | C11 |
| A write that runs from `toolkit.read` or without the toolkit | `prepare_...` and `submit_...` | C10, C11 |
| A `submit` tool with parameters | It writes what `prepare` showed | C11 |
| A use case that writes without `user`, `confirmation`, `authorize`, `record` | The shape of section 5.4 | C11 |
| A preview and a write that check different things | One private function for both | review |
| A synchronous tool | `async def`; the toolkit runs the use case in a thread | C03 |
| A `Decimal`, `date`, `float`, `dict` or optional tool parameter | `str`, `int`, `bool`, lists of keys; parsed in `rules.py` | C03 |
| A use case that returns a `Decimal`, a date or a dataclass | Text formatted by code | unit |
| `float` for money | Integer minor units or `Decimal` | C08 |
| `print`, `sys.exit`, `os._exit`, `input`, `subprocess` | A refusal; `logging` | C02 |
| A name imported in `agent.py` that `tools.py` does not define | Derive the import from `tools.py` | C01 |
| A model alias or preview as default; a model written in `Agent(...)` | A version name in `DEFAULT_MODEL`; `model=MODEL` | C06 |
| An agent wrapped in `AgentTool`; `mode=` on an agent | `sub_agents` | C06 |
| `global_instruction` on an agent | `GlobalInstructionPlugin` on the `App` | C06 |
| A rule with no source, or with a source that is not a literal | Legacy code, a document, or `ASSUMED:OP-<n>` | C07 |
| A rule with no test that names it | The id in the name or docstring of a test | C07 |
| The old evaluation format (`query` / `expected_tool_use`) | The `EvalSet` schema of `orders.test.json` | C09 |
| An evaluation set without a confirmation, a refusal by the user, something unavailable | The cases of section 8 | C09 |
| A changed file of the archetype | Leave it; extend in your own files | C12 |
| A pipeline of model agents that each call one tool | A `Workflow` with function nodes | C13 |
| A rule that runs on a value the user did not give | Optional fields, a code node that asks | review |
| A changed literal, a softened refusal, an "improved" rule | Verbatim; the doubt goes to `OPEN_POINTS.md` | review |
| Real data of the legacy system in seed, tests or evaluation | Invented data | review |
| Menus, option numbers or function keys in the conversation | The user's own words | review |

---

## 12. Order of work for the generator

1. Read the extracted rules. List the operations, the records, the rules with their ids
   and sources, and what the sources do not state.
2. Choose the pattern (section 4).
3. Write `domain/rules.py`: constants, `RULES`, normalizers, formatters.
4. Write `domain/store.py` (records, port, in-memory store with invented data) and adapt
   `wiring.py` and `tests/conftest.py` to the store class.
5. Write `domain/service.py`: the read use cases; for each write, the private function,
   its preview and the write.
6. Write `tests/unit/test_rules.py` and run it (`pytest tests/unit/test_rules.py
   tests/unit/test_base.py`): the rules are proven before any agent code exists.
7. Write `tools.py`, then `agent.py` (import derived from `tools.py`), then `prompt.py`.
8. Write `tests/unit/test_flows.py` and `tests/eval/<domain>.test.json`; delete
   `tests/eval/orders.test.json`. Rewrite `tests/eval/test_two_users.py` for the domain if
   a second person decides, otherwise delete it.
9. Write `OPEN_POINTS.md`. Set `[project].name` in `pyproject.toml`.
10. Run the gates of section 8 in order. Fix the code, never the gate.
