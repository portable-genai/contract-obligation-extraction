# The Rgc8 contract-register feed (versioned proposal)

Rgc12 produces a structured obligation register per contract. The firm-wide Third-Party / Vendor
Risk system, **Rgc8** (`third-party-risk-ddq`), consumes that register for the
contractual terms behind a vendor's inherent/residual risk rating. Rgc8 is not built yet, so this
document freezes the wire shape as a **recorded proposal**, not an agreement. A contract test
(`tests/unit/test_contracts.py::test_the_rgc8_feed_carries_a_schema_version`) holds the shape and
its version stable so a later change is a deliberate, reviewed one.

## Where the shape comes from

The feed is not a bespoke serialiser. It is the shared kernel's envelope over a register snapshot:

```
register_envelope(register) == obligation_register.schema.envelope(
    "contract_obligation_register", register.snapshot
)
```

`obligation-register-kit` owns the canonical, byte-identical serialisation (sorted keys, ISO dates,
enum values), so the regulatory system of record (Rgc7) and this contractual extractor speak one
wire vocabulary. The kernel stamps every envelope with its `SCHEMA_VERSION`.

## The envelope

```json
{
  "schema_version": "1.0",
  "kind": "contract_obligation_register",
  "payload": {
    "version": 1,
    "effective_from": "2026-01-01",
    "graph": { "obligations": [ ... ], "nodes": [ ... ], "edges": [ ... ] },
    "note": ""
  }
}
```

- `schema_version` is the kernel's, bumped on any change to a serialised field name, a dropped
  field or an enum member. A consumer pins it.
- `kind` distinguishes a contractual register from Rgc7's regulatory one.
- `payload` is a `RegisterSnapshot`: a versioned, effective-dated pin of the whole obligation
  graph. Each obligation carries its `id`, `title`, `text`, `owner`, `citation` (the source
  contract id and clause number), `effective_from` and any `deadline`.

## What is NOT on the feed, by design

- **The risk-flag classification and the deadline status** are Rgc12's own view rows, not part of
  the kernel graph. They are exposed on the REST/agent response (`flags`, `deadline`,
  `needs_review`) for a human reviewer; the kernel feed carries the obligations and their clause
  citations, which is the contract that must stay stable for Rgc8. When Rgc8 is built, the flag and
  deadline projection becomes part of the agreed contract and moves under version control here.
- **Anything unreviewed.** The register a surface returns is the extractor's proposal admitted by
  the engine; every material register sets `requires_human_review` and routes to Hrz7. Rgc8 should
  treat an un-approved register as provisional.

## Consuming it

Until Rgc8 exists, a consumer reads the feed from `POST /v1/register` (the `feed` field of the
response) or the `extract_contract_register` agent tool. Pin `schema_version`; treat an unknown
version as a hard error, not a best-effort parse.
