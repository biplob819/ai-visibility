## What this changes and why

<!-- One concern per pull request. Link the issue it closes, if any. -->

## How it is tested

<!-- The test that fails without this change, and which marker group it is in. -->

## Checklist

- [ ] `uv run ruff check .`, `uv run ruff format --check .`, `uv run pyright` and `uv run pytest -q` pass
- [ ] No API key, `.env`, page HTML or page text is committed (secret scan and storage audit pass)
- [ ] Tests make no provider calls and fetch no real pages
- [ ] The politeness floor is unchanged or stricter (docs/responsible-use.md)
- [ ] Nothing here advises on gaming AI answers, and no telemetry is added
- [ ] Public API or results-format changes are noted in `changelog.md` (docs/versioning.md)
