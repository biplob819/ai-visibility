# Versioning

citewatch follows [Semantic Versioning 2.0.0](https://semver.org/). Versions are
`MAJOR.MINOR.PATCH`; while the major version is 0, a minor release may break the public API,
and the changelog says how.

## The public API

Only these are covered by semver. Everything else (other modules, functions whose names start
with `_`, the layout of `data/`, log formats, the dashboard's HTML) may change in any release.

| Name | Where | What it is |
|---|---|---|
| `citewatch.schemas` | the module and every name in its `__all__` | the results format: `StudyConfig`, `StudySummary`, `DomainCard`, `Citation`, `AnswerRecord`, `ThresholdRule`, the metric rows, and their loaders |
| `canonical_url(url) -> str` | `citewatch`, `citewatch.extract.urls` | the canonical form citewatch counts pages by |
| `publisher_of(url_or_domain) -> (publisher, group)` | `citewatch`, `citewatch.extract.urls` | the publisher a URL is credited to |
| `UrlError` | `citewatch`, `citewatch.extract.urls` | raised by both for a URL they cannot read |
| `lookup(query, cards, answers, intent=None)` | `citewatch`, `citewatch.cards` | a publisher's domain card, or a `NotCited` result |
| `read_cards(path)`, `NotCited` | `citewatch`, `citewatch.cards` | read `domain_cards.json`; the not-cited result |
| The `citewatch` command | console script | its commands, options, `--json` keys and exit codes (0 done, 1 a threshold failed, 2 error, 3 cost cap, 4 judging pending) |
| `study.yaml` | study folder | the fields `StudyConfig` accepts, including `thresholds` selectors |

A test builds the wheel, installs it in a clean virtual environment with no extras, and
imports exactly these names (`tests/test_public_api.py`).

## What each kind of release may change

| Release | May | May not |
|---|---|---|
| PATCH (0.1.0 → 0.1.1) | fix bugs, tighten validation that was plainly wrong, update `prices.yaml`, improve messages | add or remove public names, change a metric's definition |
| MINOR (0.1 → 0.2) | add public names, optional `study.yaml` fields, `summary.json` fields and `--json` keys, threshold selectors; while at 0.x, also break the API with a changelog note | remove a field from the results format without a major schema version |
| MAJOR (0.x → 1.0, 1.x → 2.0) | remove or rename public names, change metric definitions | — |

## The results format has its own version

`summary.json` carries `schema_version` (now `1.0`). A citewatch release reads
any file of the same schema major version; a new major schema version is refused with a
message naming both versions. Adding an optional field is a minor change; removing or
redefining one is a major change.

A change that would make two studies' numbers mean different things (how a share, a stale
rate or an interval is computed) is a metric-definition change: it is called out in the
changelog and needs a major release once citewatch is 1.0.

## The politeness floor is not versioned

The fetch rules in [responsible-use.md](responsible-use.md) are not part of the API and never
loosen in any release, of any kind. A release may make them stricter.

## Deprecation

Once at 1.0, a public name is deprecated for at least one minor release (with a
`DeprecationWarning`) before it is removed in the next major release.
