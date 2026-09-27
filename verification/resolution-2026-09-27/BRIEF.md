# Evidence completion brief (2026-09-27)

After all waves were applied and the research route ran, 228 entries are still not
verified because the research route requires EVERY field of the current cdl.bib entry to
equal a researched value backed by a verbatim quote found in a saved source body
(bibcheck/research_route.py; design in verification/research-route-2026-09-27/README.md).
queue.json lists each key with the route's reasons (e.g. "journal: no research row covers
this field", "pages: the entry value differs from the latest evidenced value").

For each key in your batch:
- Read the CURRENT entry via `DEVELOPER_DIR=/Library/Developer/CommandLineTools git show HEAD:cdl.bib`.
- For each field the reasons name, find the value as printed in the official record under the
  rules in verification/resolution-plan-2026-09-22/README.md (all sections and every (default)
  line) and verification/resolution-2026-09-26/BRIEF.md (evidence forms: next_start,
  several quotes via evidence/extra_evidence, browser/scan notes), and write a `set` with URL +
  verbatim quote. If the current value is right, `set` it anyway with its evidence (that is
  what the route needs). If a value differs from the evidence, `set` the evidenced value (it
  will be applied). If an optional field cannot be confirmed, `remove` it. If the work itself
  cannot be verified, `drop` it (rule 1).
- Quotes must be fetchable by script so validate.py can save the body (prefer Crossref/PubMed/
  LoC/publisher pages); browser-read or scan-transcribed only when nothing else exists, and say
  so in notes.
- Test each quote with the post-check's checker before writing:
  `.venv/bin/python -c "import sys; sys.path.insert(0,'verification/research-2026-09-25'); import postcheck as pc; ..."`
  (see how postcheck.resolution_quote is called in tests/test_research_postcheck.py).

Output: verification/resolution-2026-09-26/batch-NN.json (NN = 27 + your batch number), a list
of rows in the resolution schema with "key", "wave": null, "decision", "set", "remove",
"notes". Keep NCBI ≤1 req/s. No abstracts; as printed within house form.
