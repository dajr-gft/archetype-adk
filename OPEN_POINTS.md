# Open points

What the legacy sources do not state. A rule whose source is `ASSUMED:OP-<n>` in
`domain_agent/domain/rules.py` is implemented from the assumption written here, and stays
an assumption until the owner of the legacy system answers. The conformance gate (C07)
fails when an assumed rule has no entry in this file.

Nothing is assumed silently: behaviour that no source states is either left out of the
agent or listed here with the question that settles it.

| Id | Rule | What is assumed | Why it is not known | Question for the owner of the system |
|---|---|---|---|---|
| OP-001 | BR-006 | An approval is refused when the order changed after the request was created. | The approval program was not delivered; only its screens are documented. | What does the approval do when the order was changed in the meantime? |

The entry above belongs to the illustrative `orders` domain. A generated agent replaces
it with the open points of its own domain, or leaves the table empty.
