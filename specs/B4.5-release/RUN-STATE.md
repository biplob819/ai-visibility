# B4.5 run state

**Now:** green. All 11 criteria confirmed; no high or medium finding open.

## Log
- 2026-11-17 — lane 2 merged (3f1e9a6): thresholds (D-77), responsible use, community files, versioning, public API contract.

- 2026-11-17 — guides (quickstart, own study, dates, cost), published-package smoke workflow on 3 OS, `scripts/check_links.py` (40 links online OK), CLI screenshot, release README (install, guides, links); OSS-03 end to end merged (German one-provider study through the real CLI and gate G1 on recorded fixtures, no network). Converge PASS.

- 2026-11-17 — verifier pass 1: OSS-03..07, THR-01/02 CONFIRMED (wheel works from plain pip on 3.11 and 3.12 with no keys; floor cannot be lowered; no telemetry); OSS-01 DISPROVED (H: git URL in the `support` extra would make PyPI refuse the upload); OSS-02/08 PENDING-RELEASE; OSS-09 DISPROVED (M: no demo screenshot or link yet; link checker missed bare URLs and PyPI's 200 challenge page). Also M versioning overclaimed compatibility, M no 0.1.0 changelog entry; lows. Fixed per D-84; the demo screenshot and link wait on the deploy.

- 2026-11-17 — verifier pass 2 (focused): all 7 checks PASS (wheel and sdist metadata clean, twine check passes, EvalKit still installed in the repo and CI, score byte-identical, plain-wheel score degrades with a note; pinned action SHA is release/v1). M: 23 relative README links would 404 on PyPI — fixed (absolute blob URLs, each checked to name a real file). OSS-03..07, THR-01/02 CONFIRMED; OSS-01/02/08 PENDING-RELEASE (owner: PyPI publisher, tag); OSS-09 pending only the demo screenshot and link.

## Known limits
- The published package has no support-judging extra until EvalKit 0.3 is on PyPI (D-84); the repository reproduces it with the pinned commit.
- A pip-only user cannot write `cost_model.yaml` (the measuring script lives in the repository), and packaged prices go stale seven days after release until a study adds its own `prices.yaml`.

- 2026-11-19 — CI fixed on all three platforms (D-87); main green at 5c6c034. Owner added the PyPI pending publisher and approved the tag. `v0.1.0` pushed: release workflow build + publish succeeded (trusted publishing, no token); PyPI serves `citewatch-0.1.0-py3-none-any.whl` and `citewatch-0.1.0.tar.gz`; published-smoke passed on ubuntu, macos, windows (`uvx citewatch==0.1.0 --version`, `report --example`); a clean local `uvx citewatch==0.1.0` reproduces both. Demo live at https://citewatch.streamlit.app (D5.2): README gains a Demo section, screenshot and link (OSS-09); changelog and install wording restored to released.

- 2026-11-19 — final verifier pass: OSS-01, 02, 08 CONFIRMED (tag v0.1.0 on green 5c6c034, OIDC publish with provenance, wheel metadata clean, 3-OS smoke on the published package; changelog figures match summary.json). OSS-09 confirmed for the README; High: the PyPI page carried the pre-release README (the tagged one). Fixed by v0.1.1 (tag on green 46c082b; PyPI page now has the demo section and screenshot and no "not on PyPI yet"; smoke 3 OS on 0.1.1). Medium (HEAD CI red at ef35bf5) resolved: 46c082b green. Lows kept as known limits: the link checker installs a process-wide cookie opener and treats any status below 400 as alive; Git Bash on Windows reports no terminal, so a code typed there is visible (piped input never reaches stdout or stderr, now tested); the wheel contract test needs the package index.
