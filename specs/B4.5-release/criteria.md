# B4.5 acceptance criteria

**OSS-01** `citewatch` is on PyPI, published by GitHub Actions trusted publishing from a version tag.
**OSS-02** `uvx citewatch --version` and `citewatch report --example` pass against the published package on Linux, macOS and Windows.
**OSS-03** `citewatch init` never overwrites; a study with custom intents, another country and one provider runs end to end on recorded fixtures.
**OSS-04** Docs: quickstart (example report in under 5 minutes, no keys), run your own study, how dates are resolved and their limits, controlling cost.
**OSS-05** The politeness floor cannot be lowered by config, flag or environment; docs on purpose (not for gaming AI answers), no telemetry, privacy.
**OSS-06** CONTRIBUTING, SECURITY, CODE_OF_CONDUCT, issue and PR templates.
**OSS-07** Semver policy; public API and an import contract test against the built wheel.
**OSS-08** Tag v0.1.0 with the flagship study's results and changelog.
**OSS-09** Release README: screenshots of the dashboard, demo and CLI; a step-by-step guide; every important link in one place, each checked to resolve.
**THR-01** Thresholds in `study.yaml`; `citewatch score` exits 1 naming each failed rule; no rules means exit 0.
**THR-02** Example GitHub Actions workflow failing on a threshold; a docs page on thresholds.
