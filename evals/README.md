# Evals

A gold-set evaluation of the harness's hiring decisions — measuring **model
judgment quality**, distinct from the `tests/` suite (which checks harness
mechanics with the model mocked).

- **`gold.json`** — labeled `(candidate × job → expected decision)` cases. Labels
  derive from each candidate's **real TEA certification** vs the job's required
  subject/grade.
- **`jobs/`** — eval-only job descriptions (History Teacher/Coach, HS SPED Math,
  Elementary Math). **These are intentionally NOT listed on the deployed website**
  — the deployed jobs are a disjoint set, so we never evaluate on a job a viewer can
  also run on the site.
- **`fixtures/tea/`** — each candidate's real TEA lookup HTML, captured once so the
  eval runs **offline and deterministically** on the credential side while the
  **model is real**.

## Run

```bash
ANTHROPIC_API_KEY=...  python evals/run.py     # Claude
DEEPSEEK_API_KEY=...   python evals/run.py     # DeepSeek
GROQ_API_KEY=...       python evals/run.py     # Gemma
```

Prints per-case PASS/FAIL and an overall score. Because the model is real, the
score is an **eval signal, not a hard gate** — use it to compare models and catch
regressions when prompts or models change.

The cases include **coaching + subject** roles (e.g. History Teacher/Coach): a
strong resume is still rejected when the candidate lacks the required Texas
**subject** certification — exactly what the harness must enforce.
