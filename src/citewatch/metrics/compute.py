"""Tech Spec §6 metrics, each with its §6.6 interval (MET-01..MET-07).

Every bootstrapped figure is built from per-question arrays (index = position in
`StudyData.qids`), so one resample matrix W gives every interval (see `stats`).
"""

from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass

import numpy as np

from citewatch.schemas import (
    CitationsRow,
    ComparisonRow,
    ConcentrationRow,
    FreshnessRow,
    OverdueRow,
    OverlapRow,
    ShareRow,
    StabilityRow,
    StaleRow,
)

from .data import Answer, StudyData
from .stats import ALPHA, Arr, boot_ratio, holm, jaccard, make_interval, p_two_sided, percentiles

TOP = 10
POOLED_TOP = 20
NHS = "nhs.uk"


@dataclass
class Ctx:
    data: StudyData
    w: Arr  # (B, Q) resample counts
    stale_days: int

    def __post_init__(self) -> None:
        self.index = {q: i for i, q in enumerate(self.data.qids)}
        self.by: dict[tuple[int, str], dict[str, Answer]] = defaultdict(dict)
        for a in self.data.answers:
            self.by[(a.run, a.model)][a.qid] = a

    @property
    def q(self) -> int:
        return len(self.index)

    def slice(self, run: int, model: str, intent: str | None) -> list[Answer]:
        return [
            a
            for a in self.by[(run, model)].values()
            if a.valid and (intent is None or a.intent == intent)
        ]

    def vec(self) -> Arr:
        return np.zeros(self.q)


def _intents(ctx: Ctx) -> list[str | None]:
    return [None, *sorted({q.intent for q in ctx.data.questions})]


# --- MET-01 shares -----------------------------------------------------------------------------


def _share_arrays(ctx: Ctx, answers: list[Answer], kind: str) -> tuple[list[str], Arr, Arr, Arr]:
    """Publishers, numerator (Q, P), denominator (Q,), and integer counts (Q, P) for k."""

    def pubs_of(a: Answer) -> Iterable[str]:
        return a.consulted_publishers if kind == "consulted" else a.publishers

    pubs = sorted({p for a in answers for p in pubs_of(a)})
    col = {p: j for j, p in enumerate(pubs)}
    num = np.zeros((ctx.q, len(pubs)))
    cnt = np.zeros((ctx.q, len(pubs)))
    den = ctx.vec()
    for a in answers:
        i = ctx.index[a.qid]
        if kind == "weighted":
            if not a.cites:
                continue  # weighted share: answers with citations only
            den[i] += 1
            for c in a.cites:
                num[i, col[c.publisher]] += 1 / len(a.cites)
            for p in a.publishers:
                cnt[i, col[p]] += 1
        else:
            den[i] += 1  # zero-citation answers stay in the denominator
            for p in pubs_of(a):
                num[i, col[p]] += 1
                cnt[i, col[p]] += 1
    return pubs, num, den, cnt


def shares(ctx: Ctx) -> list[ShareRow]:
    rows: list[ShareRow] = []
    for run in ctx.data.runs():
        for model in ctx.data.models():
            for intent in _intents(ctx):
                answers = ctx.slice(run, model, intent)
                for kind in ("presence", "weighted", "consulted"):
                    pubs, num, den, cnt = _share_arrays(ctx, answers, kind)
                    n = int(den.sum())
                    if n == 0 or not pubs:
                        continue
                    point = num.sum(axis=0) / n
                    lo, hi = percentiles(boot_ratio(ctx.w, num, den))
                    for j, p in enumerate(pubs):
                        rows.append(
                            ShareRow(
                                publisher=p,
                                model=model,
                                intent=intent,
                                run=run,
                                kind=kind,  # type: ignore[arg-type]
                                share=make_interval(
                                    float(point[j]),
                                    float(lo[j]),
                                    float(hi[j]),
                                    n=n,
                                    k=None if kind == "weighted" else int(cnt[:, j].sum()),
                                ),
                            )
                        )
    return rows


# --- MET-02 citations per answer and concentration -----------------------------------------------


def citations(ctx: Ctx) -> list[CitationsRow]:
    rows = []
    for run in ctx.data.runs():
        for model in ctx.data.models():
            for intent in _intents(ctx):
                answers = ctx.slice(run, model, intent)
                if not answers:
                    continue
                num, raw, den = ctx.vec(), ctx.vec(), ctx.vec()
                for a in answers:
                    i = ctx.index[a.qid]
                    num[i] += len(a.cites)
                    raw[i] += a.raw_citations
                    den[i] += 1
                n = int(den.sum())
                vals = boot_ratio(ctx.w, num, den)
                lo, hi = percentiles(vals[:, None])
                rows.append(
                    CitationsRow(
                        model=model,
                        intent=intent,
                        run=run,
                        unique_per_answer=make_interval(
                            float(num.sum() / n), float(lo[0]), float(hi[0]), n=n
                        ),
                        raw_per_answer=float(raw.sum() / n),
                        zero_citation=sum(not a.cites for a in answers),
                    )
                )
    return rows


def concentration(ctx: Ctx) -> list[ConcentrationRow]:
    rows = []
    for run in ctx.data.runs():
        for model in ctx.data.models():
            _, num, den, _ = _share_arrays(ctx, ctx.slice(run, model, None), "weighted")
            n = int(den.sum())
            if n == 0:
                continue
            point = num.sum(axis=0) / n
            top_point = float(np.sort(point)[::-1][:TOP].sum())
            vals = np.nan_to_num(boot_ratio(ctx.w, num, den))
            top_vals = -np.sort(-vals, axis=1)[:, :TOP].sum(axis=1)
            lo, hi = percentiles(top_vals[:, None])
            rows.append(
                ConcentrationRow(
                    model=model,
                    run=run,
                    top10_share=make_interval(top_point, float(lo[0]), float(hi[0]), n=n),
                    hhi=float((point**2).sum()),
                )
            )
    return rows


# --- MET-03 freshness, MET-04 stale answers -------------------------------------------------------


def _lag(ctx: Ctx, a: Answer, url: str) -> int | str | None:
    """Lag in days; None when undated; 'after' when the page changed after the answer."""
    page = ctx.data.pages.get(url)
    if page is None or page.effective_date is None:
        return None
    days = (a.answered_at.date() - page.effective_date).days
    return "after" if days < 0 else days


def _signed_lag(ctx: Ctx, a: Answer, url: str) -> int | None:
    page = ctx.data.pages.get(url)
    if page is None or page.effective_date is None:
        return None
    return (a.answered_at.date() - page.effective_date).days


def freshness(ctx: Ctx) -> list[FreshnessRow]:
    rows = []
    for model in [None, *ctx.data.models()]:
        lags: dict[str, list[int]] = defaultdict(list)
        dated: dict[str, set[str]] = defaultdict(set)
        after: Counter[str] = Counter()
        seen: set[str] = set()
        for a in ctx.data.answers:
            if not a.valid or (model is not None and a.model != model):
                continue
            for c in a.cites:
                seen.add(c.publisher)
                lag = _lag(ctx, a, c.url)
                if lag == "after":
                    after[c.publisher] += 1
                elif isinstance(lag, int):
                    lags[c.publisher].append(lag)
                    dated[c.publisher].add(c.url)
        for p in sorted(seen):
            xs = sorted(lags[p])
            if xs:
                q = (
                    statistics.quantiles(xs, n=4, method="inclusive")
                    if len(xs) > 1
                    else [xs[0]] * 3
                )
                med, iqr = float(statistics.median(xs)), (float(q[0]), float(q[2]))
            else:
                med, iqr = None, None
            rows.append(
                FreshnessRow(
                    publisher=p,
                    model=model,
                    dated_pages=len(dated[p]),
                    median_lag_days=med,
                    iqr_days=iqr,
                    modified_after_answer=after[p],
                )
            )
    return rows


def stale(ctx: Ctx) -> list[StaleRow]:
    rows = []
    for model in ctx.data.models():
        for intent in _intents(ctx):
            prim, sec, den = ctx.vec(), ctx.vec(), ctx.vec()
            undated = 0
            k_prim = k_sec = 0
            for run in ctx.data.runs():
                for a in ctx.slice(run, model, intent):
                    if not a.time_sensitive:
                        continue
                    # every dated citation counts, including pages dated after the answer: they
                    # are excluded from lag only (pre-registration, v1 M1); their lag is negative
                    lags = [x for c in a.cites if (x := _signed_lag(ctx, a, c.url)) is not None]
                    if not lags:
                        undated += 1
                        continue
                    i = ctx.index[a.qid]
                    den[i] += 1
                    if min(lags) > ctx.stale_days:  # its newest dated citation is stale
                        prim[i] += 1
                        k_prim += 1
                    if max(lags) > ctx.stale_days:
                        sec[i] += 1
                        k_sec += 1
            n = int(den.sum())
            if n == 0:
                continue
            for definition, num, k in (("primary", prim, k_prim), ("secondary", sec, k_sec)):
                lo, hi = percentiles(boot_ratio(ctx.w, num, den)[:, None])
                rows.append(
                    StaleRow(
                        model=model,
                        intent=intent,
                        definition=definition,  # type: ignore[arg-type]
                        rate=make_interval(k / n, float(lo[0]), float(hi[0]), n=n, k=k),
                        undated=undated,
                    )
                )
    return rows


def overdue(ctx: Ctx) -> list[OverdueRow]:
    """Share of cited NHS (page, answer) pairs whose `review_due` is before the answer (§6.3,
    D-56); an NHS page with no review date counts as not overdue."""
    rows = []
    for model in [None, *ctx.data.models()]:
        num, den = ctx.vec(), ctx.vec()
        for a in ctx.data.answers:
            if not a.valid or (model is not None and a.model != model):
                continue
            for c in a.cites:
                if NHS not in (c.publisher, c.group):
                    continue  # NHS overdue is over cited NHS pages (D-56)
                page = ctx.data.pages.get(c.url)
                i = ctx.index[a.qid]
                den[i] += 1
                due = None if page is None else page.review_due
                num[i] += due is not None and due < a.answered_at.date()
        n = int(den.sum())
        if n == 0:
            continue
        k = int(num.sum())
        lo, hi = percentiles(boot_ratio(ctx.w, num, den)[:, None])
        rows.append(
            OverdueRow(
                model=model, share=make_interval(k / n, float(lo[0]), float(hi[0]), n=n, k=k)
            )
        )
    return rows


# --- MET-05 overlap, MET-06 stability -------------------------------------------------------------


def _pair_jaccard(
    ctx: Ctx, left: dict[str, Answer], right: dict[str, Answer], intent: str | None
) -> tuple[Arr, Arr, int]:
    """Per-question Jaccard of publisher sets, the included-question mask, and how many
    questions were excluded because both answers cite nothing."""
    num, den = ctx.vec(), ctx.vec()
    excluded = 0
    for qid, a in left.items():
        b = right.get(qid)
        if b is None or not a.valid or not b.valid or (intent is not None and a.intent != intent):
            continue
        j = jaccard(a.publishers, b.publishers)
        if j is None:
            excluded += 1
            continue
        i = ctx.index[qid]
        num[i] += j
        den[i] += 1
    return num, den, excluded


def overlap(ctx: Ctx) -> tuple[list[OverlapRow], dict[str, int]]:
    rows: list[OverlapRow] = []
    excluded: dict[str, int] = {}
    models, runs = ctx.data.models(), ctx.data.runs()
    for intent in _intents(ctx):
        tag = intent or "all"
        cross_parts: list[tuple[Arr, Arr]] = []
        if len(models) == 2:
            m1, m2 = models
            for run in runs:
                num, den, ex = _pair_jaccard(ctx, ctx.by[(run, m1)], ctx.by[(run, m2)], intent)
                excluded[f"cross_model:{tag}:run{run}"] = ex
                if den.sum() == 0:
                    continue
                cross_parts.append((num, den))
                vals = boot_ratio(ctx.w, num, den)
                lo, hi = percentiles(vals[:, None])
                rows.append(
                    OverlapRow(
                        intent=intent,
                        run=run,
                        kind="cross_model",
                        value=make_interval(
                            float(num.sum() / den.sum()),
                            float(lo[0]),
                            float(hi[0]),
                            n=int(den.sum()),
                        ),
                    )
                )
                rows.extend(_pooled(ctx, run, m1, m2, intent))
        selfs: list[tuple[Arr, Arr]] = []
        if len(runs) >= 2:
            r1, r2 = runs[0], runs[1]
            for m in models:
                num, den, ex = _pair_jaccard(ctx, ctx.by[(r1, m)], ctx.by[(r2, m)], intent)
                excluded[f"self:{m}:{tag}"] = ex
                if den.sum() == 0:
                    continue
                selfs.append((num, den))
                lo, hi = percentiles(boot_ratio(ctx.w, num, den)[:, None])
                rows.append(
                    OverlapRow(
                        intent=intent,
                        kind="self",
                        model=m,
                        value=make_interval(
                            float(num.sum() / den.sum()),
                            float(lo[0]),
                            float(hi[0]),
                            n=int(den.sum()),
                        ),
                    )
                )
        if cross_parts and len(selfs) == 2:
            cnum = np.sum([p[0] for p in cross_parts], axis=0)
            cden = np.sum([p[1] for p in cross_parts], axis=0)

            def norm(nums: list[Arr], dens: list[Arr], w: Arr) -> Arr:
                cross = (w @ nums[0]) / (w @ dens[0])
                s1 = (w @ nums[1]) / (w @ dens[1])
                s2 = (w @ nums[2]) / (w @ dens[2])
                return cross / ((s1 + s2) / 2)

            nums = [cnum, selfs[0][0], selfs[1][0]]
            dens = [cden, selfs[0][1], selfs[1][1]]
            point_w = np.ones((1, ctx.q))
            with np.errstate(divide="ignore", invalid="ignore"):
                point = float(norm(nums, dens, point_w)[0])
                vals = norm(nums, dens, ctx.w)
            if np.isfinite(point):
                lo, hi = percentiles(vals[:, None])
                rows.append(
                    OverlapRow(
                        intent=intent,
                        kind="normalised",
                        value=make_interval(point, float(lo[0]), float(hi[0]), n=int(cden.sum())),
                    )
                )
    return rows, excluded


def _top_sets(point_or_vals: Arr, pubs: list[str], k: int) -> list[set[str]]:
    """Each row's top-k publishers by share, with every publisher tied at the cut included,
    so the set never depends on name order (D-56)."""
    arr = np.nan_to_num(np.atleast_2d(point_or_vals))
    out = []
    for row in arr:
        if not len(row):
            out.append(set())
            continue
        cut = np.sort(row)[::-1][min(k, len(row)) - 1]
        out.append({pubs[j] for j in np.nonzero((row >= cut) & (row > 0))[0]})
    return out


def top_with_ties(shares: dict[str, float], k: int = TOP) -> list[str]:
    """The top-k publishers by share plus any tied with the k-th (D-56), in rank then name order."""
    ranked = sorted(shares.items(), key=lambda kv: (-kv[1], kv[0]))
    if len(ranked) <= k:
        return [p for p, _ in ranked]
    cut = ranked[k - 1][1]
    return [p for p, s in ranked if s >= cut]


def _pooled(ctx: Ctx, run: int, m1: str, m2: str, intent: str | None) -> list[OverlapRow]:
    """Jaccard of each model's top-20 publishers by presence share, labelled as pooled."""
    sides = []
    for m in (m1, m2):
        pubs, num, den, _ = _share_arrays(ctx, ctx.slice(run, m, intent), "presence")
        if den.sum() == 0:
            return []
        point = num.sum(axis=0) / den.sum()
        vals = boot_ratio(ctx.w, num, den)
        sides.append((pubs, point, vals))
    (p1, pt1, v1), (p2, pt2, v2) = sides
    a, b = _top_sets(pt1, p1, POOLED_TOP)[0], _top_sets(pt2, p2, POOLED_TOP)[0]
    point = jaccard(a, b)
    if point is None:
        return []
    ta, tb = _top_sets(v1, p1, POOLED_TOP), _top_sets(v2, p2, POOLED_TOP)
    vals = np.array(
        [jaccard(x, y) if (x or y) else np.nan for x, y in zip(ta, tb, strict=True)], dtype=float
    )
    lo, hi = percentiles(vals[:, None])
    return [
        OverlapRow(
            intent=intent,
            run=run,
            kind="pooled_top20",
            value=make_interval(float(point), float(lo[0]), float(hi[0]), n=len(a | b)),
        )
    ]


def stability(ctx: Ctx) -> list[StabilityRow]:
    runs = ctx.data.runs()
    if len(runs) < 2:
        return []
    r1, r2 = runs[0], runs[1]
    rows = []
    for m in ctx.data.models():
        num, den, _ = _pair_jaccard(ctx, ctx.by[(r1, m)], ctx.by[(r2, m)], None)
        if den.sum():
            lo, hi = percentiles(boot_ratio(ctx.w, num, den)[:, None])
            rows.append(
                StabilityRow(
                    model=m,
                    metric="self_jaccard",
                    value=make_interval(
                        float(num.sum() / den.sum()), float(lo[0]), float(hi[0]), n=int(den.sum())
                    ),
                )
            )
        s1 = _presence_by_pub(ctx, r1, m)
        s2 = _presence_by_pub(ctx, r2, m)
        if s1 is None or s2 is None:
            continue
        top = top_with_ties({p: float(k) for p, k in _counts(s1).items()})
        for p in top:
            d_point, d_vals, n = _diff(ctx, s2, s1, p)
            lo, hi = percentiles(d_vals[:, None])
            rows.append(
                StabilityRow(
                    model=m,
                    publisher=p,
                    metric="share_change",
                    value=make_interval(d_point, float(lo[0]), float(hi[0]), n=n),
                )
            )
    return rows


PresenceArrays = tuple[dict[str, float], list[str], Arr, Arr]


def _presence_by_pub(
    ctx: Ctx, run: int, model: str, qids: set[str] | None = None
) -> PresenceArrays | None:
    answers = [a for a in ctx.slice(run, model, None) if qids is None or a.qid in qids]
    pubs, num, den, _ = _share_arrays(ctx, answers, "presence")
    if den.sum() == 0:
        return None
    point = num.sum(axis=0) / den.sum()
    return {p: float(point[j]) for j, p in enumerate(pubs)}, pubs, num, den


def _counts(arrs: PresenceArrays) -> dict[str, int]:
    """Answers citing each publisher, as exact integers (for ranking without float ties)."""
    _, pubs, num, _ = arrs
    return {p: round(float(num[:, j].sum())) for j, p in enumerate(pubs)}


def _column(arrs: PresenceArrays, publisher: str) -> Arr:
    _, pubs, num, _ = arrs
    return num[:, pubs.index(publisher)] if publisher in pubs else np.zeros(num.shape[0])


def _diff(ctx: Ctx, a: PresenceArrays, b: PresenceArrays, publisher: str) -> tuple[float, Arr, int]:
    """Paired difference of presence share a − b for one publisher, with resampled values."""
    na, da = _column(a, publisher), a[3]
    nb, db = _column(b, publisher), b[3]
    point = float(na.sum() / da.sum() - nb.sum() / db.sum())
    with np.errstate(divide="ignore", invalid="ignore"):
        vals = (ctx.w @ na) / (ctx.w @ da) - (ctx.w @ nb) / (ctx.w @ db)
    return point, vals, int(min(da.sum(), db.sum()))


# --- MET-07 model comparisons ---------------------------------------------------------------------


def comparisons(ctx: Ctx) -> list[ComparisonRow]:
    """Paired bootstrap difference in presence share between the two models over the questions
    both answered validly, for the top-10 publishers of each run; Holm across the ten."""
    models = ctx.data.models()
    if len(models) != 2:
        return []
    m1, m2 = models
    rows = []
    for run in ctx.data.runs():
        shared = {
            q
            for q, a in ctx.by[(run, m1)].items()
            if a.valid and (b := ctx.by[(run, m2)].get(q)) is not None and b.valid
        }
        a = _presence_by_pub(ctx, run, m1, shared)
        b = _presence_by_pub(ctx, run, m2, shared)
        if a is None or b is None:
            continue
        # rank on integer counts: both sides share one denominator (the shared questions), and
        # float shares split exact ties by an ulp (v2 M1)
        pooled = Counter(_counts(a)) + Counter(_counts(b))
        top = top_with_ties({p: float(k) for p, k in pooled.items()})
        found = []
        for p in top:
            point, vals, n = _diff(ctx, a, b, p)
            lo, hi = percentiles(vals[:, None])
            found.append(
                (p, make_interval(point, float(lo[0]), float(hi[0]), n=n), p_two_sided(vals))
            )
        adjusted = holm([f[2] for f in found])
        for (p, iv, pv), padj in zip(found, adjusted, strict=True):
            rows.append(
                ComparisonRow(
                    publisher=p,
                    run=run,
                    model_a=m1,
                    model_b=m2,
                    difference=iv,
                    p_value=pv,
                    p_holm=padj,
                    separated=padj < ALPHA,
                )
            )
    return rows
