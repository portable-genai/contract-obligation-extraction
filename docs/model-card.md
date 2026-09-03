# Model card: Contract Obligation Extraction (Rgc12)

This is a STARTER model card. It records the model boundary as built and the controls that must be
completed before a managed deployment. Unusually for this catalog, there are **two model seams**
and they are in very different states, so they are documented separately.

The deterministic engine is the system of record in both cases: the model proposes and narrates,
code admits and computes.

## Seam 1: extraction (`ExtractionPort`)

- **Would do**: parse the contract's layout with Document AI and read the clause text with a
  long-context model, returning CANDIDATE obligations, dates and proposed flag classifications.
- **Does NOT do**: decide anything. `domain/contracts.py` validates every cited clause anchor and
  `domain/flags.py` decides whether each proposed flag is admissible against a frozen taxonomy. A
  proposed flag outside the taxonomy is dropped rather than coerced; a proposal marked ambiguous
  is routed to a human rather than defaulted.
- **State today: not implemented.** `adapters/gcp/extraction.py` performs its lazy SDK imports and
  then RAISES `NotImplementedError`, because the Document AI processor id, the layout
  configuration and the model endpoint are per-deployment. It names `gemini-3.5-flash` as the
  intended long-context model in `_MODEL`, but nothing calls it. **The managed document path has
  never run.**
- Offline, `adapters/local/extraction.py` replays the canned proposals the corpus carries for a
  known contract, so segmentation, admission, flag validation and the renewal clock all run end to
  end with no model. An unknown contract returns an empty result, which is a fixture's honest
  answer rather than a failure.

## Seam 2: narration (`GenerationPort`)

- **Does**: write a short register summary that restates figures the engine already produced.
- **Does NOT do**: produce a figure, a flag, a date or a severity.
- Held to two hard rules in `domain/narration.py` before the summary is allowed out: schema
  validation, so malformed output is discarded rather than repaired; and groundedness, where
  `grounded_integers` builds the allowed set from the engine-owned facts and `note_is_grounded`
  requires every integer in the summary to be in it. A summary that fails is discarded and
  `fallback_text` builds a deterministic one from the same facts.
- Those checks are module-level pure functions rather than private methods, deliberately, so the
  `narration_groundedness` eval metric measures the RAW model output through the very same
  contract the service enforces. A metric that watched only the filtered output could never go
  red.

## Adapters and profiles

| Profile | Extraction | Narration |
|---|---|---|
| `local` | `adapters/local/extraction.py`: replays the corpus's canned proposals. No model, no network. | `adapters/local/generation.py`: restates the engine facts as a deterministic note. Grounded by construction. |
| `gcp` | `adapters/gcp/extraction.py`: lazy Document AI plus `google.generativeai` imports, then RAISES. Intended model `gemini-3.5-flash`. | `adapters/gcp/generation.py`: a real Gemini call, model pinned in the class as `_MODEL`, currently `gemini-3.5-flash`. |
| `onprem` | fail-fast placeholder: raises, naming what the client must bind. | fail-fast placeholder: raises, naming the client's model gateway. |

Both managed model ids are defaults written into the adapters, not confirmed deployment
decisions. Gemini model ids are regional and an unavailable one fails at call time rather than at
boot, so confirm both are served in your region before you enable either path.

## Remaining controls (TODO, repo owner)

- **Prompt-injection screening** (rule R1). This is the highest-priority item for THIS repo, and
  it is a bigger exposure than in most of the catalog: a contract is untrusted text written by a
  counterparty and fed straight to a model. A clause crafted to read as an instruction could try
  to suppress a liability-cap flag or invent a termination date. The propose-then-admit design
  limits the blast radius (an injected flag outside the taxonomy is dropped, an injected date is
  never used for arithmetic), but limiting a blast radius is not the same as screening. Bind the
  Hrz1 guardrail gateway in front of `ExtractionPort` and fail closed when the screen is
  unavailable.
- **Implement the extraction adapter** and pin its processor, layout configuration, model id and
  version here.
- **Budget, rate limit and a kill switch** (P-10, P-11): a long-context read of a full contract is
  the most expensive call in the system and there is no per-tenant token budget, no request rate
  limit, and no switch that forces deterministic-only operation.
- **Evaluation of the live models**: the offline eval scores six metrics against the canned
  proposals, which measures the pipeline rather than a model's reading. `extraction_accuracy` in
  particular means something different once a real model is bound. Add a managed-profile run
  registered with the Hrz4 promotion gate (P-08, rule R5).
- **Reasoning trace**: the audit record carries the validated register and its clause anchors, not
  the prompt and reply pair. `COMPLIANCE.md` P-07 records that as owed.

Until these are complete the system is safe to run offline (deterministic engine plus canned
proposals plus the stub narrator) and neither managed model path is production-cleared.
