# Track 2 Technical Report Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce copy-ready form fields and a polished four-page English PDF describing NFL-Auditor accurately.

**Architecture:** Keep the report content in Markdown, keep form fields in a
small standalone file, and generate the fixed-layout A4 PDF through a
dependency-free PyMuPDF script. The report separates implemented mechanisms from
deferred live validation.

**Tech Stack:** Markdown, Python 3.14, PyMuPDF.

---

### Task 1: Draft the submission content

**Files:**
- Create: `submission/ralphthon-track2-form-fields.md`
- Create: `submission/ralphthon-track2-technical-report.md`

- [ ] Write the final English title and a 150–220 word abstract.
- [ ] Draft four pages covering architecture, deterministic audit, scientific
  committee, deployment, verification status, and limitations.
- [ ] Check that no credential, private assignment identity, placeholder, or
  unverified completion claim appears.

### Task 2: Build the PDF

**Files:**
- Create: `submission/build_technical_report.py`
- Create: `submission/ralphthon-track2-technical-report.pdf`

- [ ] Implement a fixed four-page A4 renderer using built-in PyMuPDF fonts,
  restrained color, architecture boxes, headings, bullets, and page footers.
- [ ] Run:

```bash
source .venv/bin/activate
python submission/build_technical_report.py
```

Expected: the PDF is written with exactly four pages.

### Task 3: Validate the artifact

- [ ] Open the generated PDF programmatically and assert page count is four.
- [ ] Extract text and verify the title, all major section headings, and the
  limitations statement are present.
- [ ] Read the rendered first and last pages as images to catch clipping or
  unreadable layout before handoff.
