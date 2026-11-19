# Measured improvements

Changes made during the build whose effect was measured before and after. Each figure comes
from the record linked beside it; `tests/test_project_page.py` checks each one against that
record.

| What was measured | Before | After | The change | Record |
|---|---|---|---|---|
| Pre-run cost estimate per study run | $19 (modelled: 3 searches, 25k input tokens per answer) | $7.92 (measured in the 20-answer smoke run) | The estimate reads the smoke run's measured averages, with 25% headroom. The two study runs then cost $7.55 and $7.48 | Lesson L-34; [8f8eb9a](https://github.com/biplob819/ai-visibility/commit/8f8eb9a1f16be61969a8d75bb2168b7828cc081d); `specs/S3.1-study-runs/RUN-STATE.md` |
| Support-check citations an AI judge could judge | 25 of 47 | 48 of 49, for each judge | Kept page text breaks lines at block elements, so the judges' exact-quote check works; 58 sample pages were refetched and every citation judged again (OWNER D-61) | [e4ce231](https://github.com/biplob819/ai-visibility/commit/e4ce23105a34bd2ba052304ad3509923084a046c); `specs/M3.2-support/RUN-STATE.md` |
| Shortest gap between requests to one site when a run resumes | 0.4 s | 1.025 s or more | The per-host rate limiter is seeded from the fetch log, so a resumed run waits for the last run's request; checked under slow connects, slow headers and redirects | [c5ba88d](https://github.com/biplob819/ai-visibility/commit/c5ba88dde8432825bf7f6a2b27d250bdbe21cf20); `specs/A2.2-fetcher/RUN-STATE.md` |
