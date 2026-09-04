# FAQ index

Answers to the questions different teams ask when evaluating, adopting or reviewing this
repository as a contract-to-register base. Each file is written for a specific audience; skim the
one that matches your role.

| FAQ | For | Answers |
|---|---|---|
| [security-faq.md](security-faq.md) | AppSec / security review | server-side identity, what a contract is as an input, secrets, supply chain, the audit chain |
| [portability-faq.md](portability-faq.md) | Architecture / cloud / exit planning | no-lock-in, the three profiles, the sovereign exit, the frozen feed envelope |
| [features-faq.md](features-faq.md) | Product / legal ops / delivery | what the engine extracts and decides, what the model is allowed to propose, and the boundary with `third-party-risk-ddq` and `obligations-control-mapping` |
| [adoption-faq.md](adoption-faq.md) | Engineering leads forking the repo | rename, upstream fixes, the taxonomy, what stays open |
| [compliance-faq.md](compliance-faq.md) | Compliance / legal / model risk | why an extracted obligation is traceable, maker-checker, residency, retention, model-risk evidence |

These FAQs deliberately do **not** re-document capabilities owned by sibling systems in the GRC
catalog. Where a concern belongs to another repo (the vendor-risk consumer `third-party-risk-ddq`, the firm-wide
obligation graph `obligations-control-mapping`, the guardrail gateway `agent-guardrail-gateway`, the human-review console `human-review-console`, the eval
platform `model-quality-gate`), the FAQ points at it and explains the boundary rather than duplicating it. See
[features-faq.md](features-faq.md) for the full "what this repo owns vs what it integrates" map.
The register's wire shape has its own document, [`../rgc8-feed.md`](../rgc8-feed.md).

Authority order for anything these pages disagree with: [`SPEC.md`](../../SPEC.md), then
[`ARCHITECTURE.md`](../../ARCHITECTURE.md), then [`COMPLIANCE.md`](../../COMPLIANCE.md), then
[`README.md`](../../README.md). These pages restate; they do not decide.
