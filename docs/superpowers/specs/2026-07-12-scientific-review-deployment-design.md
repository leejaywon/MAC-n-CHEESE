# Scientific Review and Ten-Paper Deployment Design

**Goal:** Make each live Ralphthon review assess scientific quality—not only
mechanical integrity—while preserving a safe fallback and proving the exact
ten-paper API flow before the write window.

## 1. Product contract

Live execution uses `--mode best` with a guaranteed OpenAI-compatible API key.
Each paper receives:

1. the existing deterministic S1–S4 audit;
2. three parallel specialist reviews over sanitized, role-targeted evidence;
3. one grounded area-chair meta-review over specialist outputs and evidence;
4. a grounded final review whose main sections and six API scores incorporate
   both layers.

Specialist, meta-review, or retrieval failure affects only that paper. At least
two specialists must succeed before the meta-review runs; otherwise the
deterministic review remains valid and submittable. No scientific call may
suppress a mechanical finding or weaken an integrity cap.

## 2. Scientific evidence packet

Build a section-aware packet from `parsed_paper["analysis_text"]`:

- title and abstract;
- problem/motivation and stated contribution;
- method/approach;
- experiments/evaluation/results, including Markdown tables;
- ablations/analysis;
- limitations/ethics;
- related work and references.

Split retained text into paragraph/table spans with stable IDs such as
`paper:L120-L134`. Prefer the sections above under
`RALPH_BEST_MAX_CHARS` (default 60,000), then derive role-specific packets for
the theorist, experimentalist, and scope/ablation specialist. Record omitted
sections. Raw hidden content never enters any packet.

## 3. Committee and strict scientific judgment

Run three specialist calls concurrently:

- **theorist:** problem definition, assumptions, logical method–problem fit;
- **experimentalist:** claim–experiment alignment, controls, baselines,
  confounds, statistics;
- **scope/ablation reviewer:** generalization, design-choice justification,
  ablations, and limitations.

Each specialist returns grounded partial assessments. A fourth area-chair call
receives their JSON, deterministic findings, and prioritized evidence spans. It
returns strict JSON with:

- a paper-specific summary;
- five required assessment axes:
  - problem–method fit;
  - claim–experiment alignment;
  - experimental-design validity;
  - scope/generalization;
  - design-choice and ablation justification;
- grounded strengths and weaknesses;
- three to five numbered author questions, each with
  `assessment_if_resolved`;
- all six direct platform scores and grounded rationales:
  Soundness, Presentation, Significance, Originality (1–4),
  Overall (1–6), and Confidence (1–5).

Every factual assessment and score rationale cites an allowed paper span,
mechanical finding, contradicted/supported claim, or retrieved arXiv ID.
Unknown IDs, empty rationales, out-of-range values, and malformed objects are
rejected.

## 4. Merge and scoring policy

Scientific output is merged into the official Summary, Strengths, Weaknesses,
and Questions sections—not rendered as an isolated appendix.

The validated model may raise or lower deterministic scores because the audit
anchor cannot distinguish scientific quality on evidence-free PDFs. Hard
constraints remain:

- a proven integrity breach caps Soundness and Overall at 2;
- mechanical contradictions and findings remain visible;
- Originality accusations cannot be based solely on retrieved post-date work;
- score–text contradictions invalidate the scientific score set;
- failed validation falls back to deterministic scores.

Preserve the deterministic `review_identity` and `verdict_digest`. Add a
separate `judgment_identity` over rubric version, model ID, prompt hash, response
hash, and validated structured judgment so the final best-mode result is
auditable without pretending model output is deterministic.

## 5. Ten-paper execution

Follow the canonical live skill exactly:

- fetch `/api/ralphthon/v1/skill.md` at startup and before every mutating POST;
- exchange one human-issued setup token in memory;
- fetch assignments only when guidance permits;
- require exactly ten unique ordinals for a full run;
- download only returned scoped HTTPS PDF URLs;
- prepare all reviews before the 16:35 KST write window;
- refresh status before every POST;
- write only in `[16:35, 17:00)`;
- stop on terminal `next_action:none` or `all_reviews_submitted`.

Resume must work when guidance reports `get_assignments`,
`download_and_review_assignments`, `submit_review`, or `reviews_remaining`.
`--only` is exempt from the ten-result output requirement but still validates
that the server assignment set contains ten unique ordinals.

## 6. Failure and latency policy

- Run up to ten paper preparations concurrently.
- Within each paper, run three bounded specialist calls concurrently followed
  by one bounded meta-review call.
- Apply per-call timeout and isolate exceptions.
- Never retry validation or 4xx errors; retry only transport/5xx failures.
- Preserve prepared payloads when posting is blocked.
- Continue after one specialist failure; fall back when fewer than two
  specialists succeed or the meta-review fails.
- Do not let one failed committee cancel other papers.

The launch target is ten prepared, schema-valid reviews comfortably before
16:35. If a committee fails, submit its deterministic fallback rather than miss
the window.

## 7. Verification

Required automated coverage:

1. Specialist and meta-review schema validation and grounding rejection.
2. Full-tail/priority-section evidence packet.
3. Each of the five scientific axes appears in valid output.
4. Scientific strengths/weaknesses/questions merge into official sections.
5. Grounded score raises/lowers work; integrity caps cannot be bypassed.
6. One specialist failure still permits meta-review; two failures or malformed
   meta output fall back per paper.
7. Mock API returns ordinals 1–10 and dry-run posts 10/10.
8. Resume from already allocated and partially submitted states.
9. Exactly-ten and unique-ordinal guards.
10. 16:59:59 writable and 17:00:00 closed.
11. Ten-paper timed replay using frozen public PDFs.
12. Existing deterministic, injection, eval, and submission suites remain green.

## 8. Deployment gate

Code is deployable only when:

- the full hermetic suite passes;
- deterministic eval does not regress;
- ten-paper mock dry-run posts 10/10;
- a ten-PDF replay produces ten grounded reviews inside the time budget;
- live `--no-post` with a real bearer confirms ten assigned PDFs and ten valid
  payloads before the write window.

The final live POST remains a human-authorized operation because it requires the
human-owned setup token.
