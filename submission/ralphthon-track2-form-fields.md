# Title

NFL-Auditor: Evidence-Bound Scientific Reviewing with Deterministic Auditing and a Grounded Multi-Agent Committee

# Abstract

Automated paper review must combine scientific judgment with resistance to
fabricated evidence, prompt injection, and operational failure. We present
NFL-Auditor, a hybrid Track 2 review system for evaluating Ralphthon Track 1
papers in the ICML review format. Its deterministic layer converts each PDF
into a canonical, content-addressed document; quarantines concealed PDF and
Unicode/HTML payloads before analysis; extracts claims, tables, citations, and
numeric results; and runs reproducible consistency, arithmetic, evidence,
positioning, and integrity checks. Every deterministic verdict is linked to a
stable claim or finding identifier and frozen independently of model output.

Scientific quality is assessed by three concurrent specialists: a theorist for
problem–method fit, an experimentalist for claim–experiment alignment and
validity, and a scope/ablation reviewer for generalization and design choices.
A fourth area-chair call reconciles their structured assessments into grounded
strengths, weaknesses, author questions, and all six platform scores. Strict
schema and citation validation reject unsupported output, while proven
integrity breaches retain hard score caps. Failures are isolated per paper and
fall back to the deterministic review. A guidance-driven API adapter validates
the fixed ten-paper assignment set, preserves local artifacts, and separates
review preparation from time-gated submission.
