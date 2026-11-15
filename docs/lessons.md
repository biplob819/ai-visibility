# Lessons

Append-only. Each entry: what happened, the rule it produced, and where the rule is enforced. L-1 to L-12 are inherited from EvalKit (`~/EvalKit/docs/lessons.md`) before this project wrote any code.

| ID | Lesson | Rule | Enforced in |
| --- | --- | --- | --- |
| L-1 | A gate that has never failed is a gate nobody has checked (EvalKit L-1, from Kova) | Every gate ships a `--self-test` that feeds it bad input and expects FAIL | `node_converge.py --self-test`, `tests/harness/` |
| L-2 | EvalKit's proofs gate once accepted a test name found only in a comment, a string, a prefix or a skipped test (EvalKit L-2) | Proofs resolve through `ast` to a real, unskipped `def test_*` under `tests/`; `logical` is never n/a | `node_converge.proof_problems` |
| L-3 | A failed `git diff` against a bad base was read as "no changes" (EvalKit L-3) | A tool error inside a gate is a FAIL | `node_converge.changed_files` |
| L-4 | Self-tests passed with the tools missing (EvalKit L-4) | A self-test requires the planted defect's identity (rule code, file, test name) in the output | `node_converge.self_test` |
| L-5 | Windows turned LF into CRLF and read text as cp1252 (EvalKit L-7, L-32) | `.gitattributes` forces LF; every text read and write names `encoding="utf-8"` | `.gitattributes`, `tests/harness/test_text_encoding.py` |
| L-6 | Scripted edits silently matched nothing after a reformat (EvalKit L-11) | Every scripted edit asserts its match count before writing | builder practice |
| L-7 | A NaN cost estimate switched the spend cap off (EvalKit L-12) | Every money value is checked finite and non-negative before it reaches a cap | N1.2 cost model |
| L-8 | A background verifier rebuilt the shared venv mid-converge (EvalKit L-15) | Verifiers run with a private `UV_PROJECT_ENVIRONMENT` | `docs/harness/verifier-prompt.md` |
| L-9 | A data card stated future work in the present tense (EvalKit L-16) | Docs say only what is true now and name the node that makes the rest true | verifier checklist |
| L-10 | Fakes flatter than the real SDK hid a wrong error path (EvalKit L-17) | Test fakes are built from the SDK's own models | N1.2 fixtures |
| L-11 | EvalKit's first real 200-case run exposed a design error no test had caught (EvalKit L-37) | Run a small real slice early (A2.4 smoke run) before any full run | graph: S3.1 depends on A2.4 |
| L-12 | Three release checks passed while the thing they checked was broken (EvalKit L-40) | A check must exercise the thing it checks, not grep for it | verifier checklist |
