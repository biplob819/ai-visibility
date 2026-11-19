# D5.3 run state

**Now:** green. PRJ-01..03 confirmed over two verifier passes; no high or medium finding open.

## Log
- 2026-11-19 — node started after B4.5 and D5.2 went green; drafts approved (OWNER D-85), GIF in place (OWNER D-86), demo linked; tests written.

- 2026-11-19 — verifier pass 1: PRJ-02 CONFIRMED; PRJ-01, PRJ-03 NOT CONFIRMED. High: portfolio.yml did not fit the site's `portfolio add` schema (crash on an images map; missing tagline, kind, year; unknown status and link keys); "one to five review passes" false (A2.2 took nine). Medium: "84 in all" and "three days" stale; tests did not pin the notes' figures. Low: run-1 shares unlabelled; $45 vs $38; "Cloudflare Pages" alt text. Fixed: portfolio.yml rebuilt in the site's schema from its live entry (dry-run `portfolio add` passes, writes nothing), with D-63/D-80/D-62/D-70 wording; notes corrected; tests pin the manifest schema, decision count, budget, pass range and note links.

- 2026-11-19 — verifier pass 2: PRJ-01, 02, 03 CONFIRMED; every pass-1 fix holds (dry-run `portfolio add` exits 0, site tree unchanged). Medium: no test on portfolio.yml's figures (12 mutations survived); the case study's H1 would become a second H1 on the site. Fixed: a test recomputes every number in portfolio.yml from summary.json or the study's set-up and pins the coverage miss, unsettled support, D-63 and D-70 wording (spot mutations now fail); the case study opens with the site's `## Write-up` heading, and its question count and runs are pinned. Lows kept: some set-up facts in the notes (days, node and lesson counts, gates, date sources) and the shot list's timing are unpinned; the pass-count test counts "verifier pass N" mentions.

