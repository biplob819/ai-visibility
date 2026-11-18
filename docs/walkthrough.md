# Walkthrough GIF: the screens it shows

`docs/assets/walkthrough.gif` replaces the planned 90-second video (OWNER D-86). It is silent,
loops, and holds each screen for 2.5 seconds (22.5 seconds in all, 960 px wide). Every screen is
a real capture of the committed outputs, with no keys and no spend.

| # | Screen | Source |
|---|---|---|
| 1 | Dashboard: what the study found | `studies/uk-health/results/site/index.html` |
| 2 | Dashboard: who gets cited (nhs.uk 83% vs 10%) | same, "Who gets cited" |
| 3 | Dashboard: stale answers | same, "Stale answers" |
| 4 | Dashboard: do the two models cite the same sources | same, overlap section |
| 5 | Dashboard: how far to trust these numbers | same, "How far to trust these numbers" |
| 6 | CLI: report, init, doctor and a dry run | `docs/assets/screenshots/cli.png` |
| 7 | Demo: looking up nhs.uk | `demo/app.py`, run locally, lookup mode |
| 8 | Demo: what could help (the domain card) | same, scrolled |
| 9 | Post: the opening | `studies/uk-health/results/site/post/index.html` |

Captured at 1280×800 with headless Chrome (screenshots and the DevTools protocol for the demo
lookup), joined with ffmpeg at a 128-colour palette.
