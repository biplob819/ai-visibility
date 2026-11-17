# B4.4 run state

**Now:** GREEN (verifier pass 5, 2026-11-17).

## Log
- 2026-11-17 — history audit: 104 commits, 2,778 file versions, no findings.

- 2026-11-17 — verifier pass 1: every README number traced and links resolve; REL-01 DISPROVED (H the rerun command used a placeholder contact that `init` refuses; M the SDK extras and the run gate's needs, including the paid smoke run, were not documented); REL-02 confirmed for current history but the audit was narrow (M: exemptions, too few markers and patterns, commit messages unchecked); REL-03 DISPROVED minor (M Claude's support sample is 24; L D-61's reading change, refetch count, date-check exclusions, undecided bullets, stale pooling). Fixed: README rerun section rewritten and tested offline; `doctor` reports missing provider SDKs; deviations completed with D-80; dashboard calls the 90% target the study's. Audit hardening in a lane.

- 2026-11-17 — verifier pass 2 (focused): REL-01..03 CONFIRMED (README rerun works as written; every pass-1 audit plant caught; no way past LINE_ALLOW). Findings: M a page cut off before </body> in a non-.html file slipped past the audit; M §8.2's 30% demotion trigger fired unrecorded; L-M fixture globs crossed folders, CSV body columns, .ndjson and other keys unchecked, the gate fell back to the flagship pre-registration; L README said --example writes the post. Fixed per D-82, D-83.

- 2026-11-17 — passes 3–5 (focused): pass 3 found the real-history audit flagging its own committed test (fixed: page-body rules skip Python sources; a cut-off page must start as a document) — lesson L-38; pass 4 found a stored page could hide in a .py (fixed: each embedded document is measured; generators allow-listed with caps); pass 5 REL-02 CONFIRMED (122 commits OK). REL-01..03 CONFIRMED; OPEN HIGH/MEDIUM: 0 (D-26 met). Rows flipped green.

## Known limits
- ALLOWED_PAGES caps are by path and size, not content (docs/signal-spec.html up to 64 KB; its builder up to 32 KB).
- Plain-text articles and UTF-16 files outside the studies folder are not page-checked; a blob at several paths is named by its first path for text findings.
- A page built in Python from many one-line string pieces with no </html> is measured only to the end of its first line (low; needs deliberate construction).
