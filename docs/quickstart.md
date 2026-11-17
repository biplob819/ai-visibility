# Quickstart: an example report in under five minutes, no keys

You need Python 3.11 or newer. Nothing here calls an AI provider or spends money.

```bash
pip install citewatch                 # or: uvx citewatch --version
citewatch --version
citewatch report --example            # writes citewatch-example/index.html
```

Open `citewatch-example/index.html` in a browser. It is the dashboard of the bundled UK health
study: which publishers two AI search models cited for 100 questions, how fresh those pages
were, how much the models agree, and how far to trust each number (every share carries its
count and a 95% interval).

From a clone of the repository instead:

```bash
git clone https://github.com/biplob819/ai-visibility && cd ai-visibility
uv sync
uv run citewatch report --example
uv run citewatch report --study studies/uk-health --title "UK health"   # dashboard and post
```

Next: [run your own study](own-study.md), [how dates are resolved](dates.md),
[controlling cost](cost.md), [thresholds in CI](thresholds.md),
[responsible use](responsible-use.md).
