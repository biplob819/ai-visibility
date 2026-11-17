# Contributing to citewatch

Thanks for helping. citewatch measures which web pages AI answers with web search cite and
how fresh they are. Bug reports, new date sources, docs fixes and studies in other countries
are all welcome.

## Ground rules

- **Responsible use comes first.** Changes that loosen the politeness floor (robots.txt,
  1 request per second per host, 8 in flight, 2 retries, only cited URLs, a user agent with a
  contact) are not accepted, nor are options to do so. Changes may only make it stricter.
  See [docs/responsible-use.md](docs/responsible-use.md).
- **No advice on gaming AI answers** in code, reports or docs (B9).
- **No telemetry**, ever.
- **No secrets or page bodies in the repository.** Never commit a `.env`, an API key, or
  page HTML or text. The secret scan and the storage audit check this.
- **No spend in tests.** Tests use recorded provider fixtures and a fake web; they never call
  a provider or fetch a real page.
- Be kind: see the [Code of Conduct](CODE_OF_CONDUCT.md).

## Set up

You need [uv](https://docs.astral.sh/uv/) and Python 3.11, 3.12 or 3.13.

```sh
git clone https://github.com/biplob819/ai-visibility
cd ai-visibility
uv sync --all-extras
uv run citewatch report --example   # the bundled study, no keys needed
```

## Before you open a pull request

Run what CI runs:

```sh
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest -q
uv run python scripts/secret_scan.py
uv run python scripts/storage_audit.py
uv run python scripts/fetch_audit.py
uv build
```

Tests are grouped with markers (`pytest -m polite`, `-m safety`, `-m golden`, `-m contract`,
`-m data`, `-m onboarding`); unmarked tests are unit tests. Every change to code under
`src/` needs a test that fails without it.

## What a good change looks like

- One concern per pull request, with a short description of why.
- A test for the behaviour, not only the code path. For a bug, a test that reproduces it.
- Public API changes (see [docs/versioning.md](docs/versioning.md)) say so in the pull
  request and get a `changelog.md` entry.
- Results-format changes (`citewatch.schemas`) keep old `summary.json` files readable within
  a major version.
- Plain, short English in messages and docs. Every number with its count.

## Reporting bugs and asking for features

Use the issue templates. For a security problem, or a fetch that broke the politeness rules,
see [SECURITY.md](SECURITY.md).

## Licence

By contributing you agree that your contribution is released under the project's
[MIT licence](LICENSE).
