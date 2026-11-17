"""citewatch demo page (node D5.2, Tech Spec §9, OWNER D-73): is a website cited by AI answers
with web search, and what would help?

Lookup mode (the default) reads the bundled domain cards and never calls a model. Live mode asks
one question of both models behind passkey sign-in (OWNER D-58, D-59) and shows each model's
citations only, never the answer prose (D-17). All logic lives in `citewatch.demo` so it is
testable without a browser; this file is layout only.

Run locally:  uv run --extra demo --extra anthropic --extra openai streamlit run demo/app.py
"""

from __future__ import annotations

import contextlib
import hashlib
import logging
import os
import secrets
import sys
import time
from pathlib import Path
from typing import Any

import streamlit as st
import streamlit.components.v2 as components_v2

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / "src") not in sys.path:  # the hosted app runs from a checkout, not an install
    sys.path.insert(0, str(ROOT / "src"))

from citewatch.cost import load_measured, load_prices  # noqa: E402
from citewatch.demo import component as C  # noqa: E402
from citewatch.demo import settings as S  # noqa: E402
from citewatch.demo.guard import STORE_DOWN, SpendGuard  # noqa: E402
from citewatch.demo.live import (  # noqa: E402
    MAX_QUESTION_CHARS,
    ProviderKeys,
    live_html,
    make_runners,
    run_live,
)
from citewatch.demo.logs import LOG, log_request  # noqa: E402
from citewatch.demo.lookup import (  # noqa: E402
    card_html,
    find,
    label,
    load_bundle,
    not_cited_html,
    top_ten,
)
from citewatch.demo.passkeys import (  # noqa: E402
    AuthRefused,
    CredentialStore,
    Passkeys,
    RegistrationGate,
)
from citewatch.schemas import DomainCard, load_study_config  # noqa: E402

STUDY = ROOT / "studies" / "uk-health"
DASHBOARD = "https://biplob819.github.io/ai-visibility/"
REPO = "https://github.com/biplob819/ai-visibility"
CSS = """
<style>
.cw-card table {border-collapse: collapse; margin: .25rem 0 .75rem 0}
.cw-card th, .cw-card td {padding: .2rem .6rem; border-bottom: 1px solid rgba(128,128,128,.3);
  text-align: left; font-size: .9rem}
.cw-improve li {margin-bottom: .5rem}
.cw-model {border: 1px solid rgba(128,128,128,.35); border-radius: 8px; padding: .75rem;
  margin-bottom: .75rem}
.cw-meta, .cw-note {font-size: .85rem; opacity: .75}
.cw-err {color: #b42318}
.cw-cites blockquote {margin: .25rem 0 .5rem 0; padding-left: .6rem; font-size: .9rem;
  border-left: 3px solid rgba(128,128,128,.4)}
</style>
"""

if not LOG.handlers:  # aggregate lines only (citewatch.demo.logs); Streamlit shows stdout logs
    _h = logging.StreamHandler(sys.stdout)
    _h.setFormatter(logging.Formatter("%(message)s"))
    LOG.addHandler(_h)
    LOG.setLevel(logging.INFO)

passkey_widget = components_v2.component(C.COMPONENT_NAME, css=C.CSS, js=C.JS)


def secret_env() -> dict[str, str]:
    """Secrets from the host's secret store over the environment. Values never leave the
    server and are never shown."""
    env = {k: v for k, v in os.environ.items() if k in S.ALL_SECRETS or k == S.LOCAL_STORE}
    with contextlib.suppress(Exception):  # no secrets file: a local run
        env.update({k: str(v) for k, v in st.secrets.items() if isinstance(v, str | int)})
    return env


@st.cache_resource
def bundle():
    return load_bundle(STUDY / "results" / "domain_cards.json")


@st.cache_resource
def study():
    return (
        load_study_config(STUDY / "study.yaml"),
        load_prices(),
        load_measured(STUDY / "cost_model.yaml"),
    )


@st.cache_resource
def shared_store(kv_url: str, local_path: str):
    """One store client per server process and store setting, shared by every session (it
    holds no visitor data). A failure raises and is not cached, so the next run retries."""
    return S.make_kv(secret_env())


def store():
    env = secret_env()
    try:
        return shared_store(env.get("CITEWATCH_DEMO_KV_URL", ""), env.get(S.LOCAL_STORE, ""))
    except Exception as exc:  # never show the store's message: it can quote the URL
        LOG.warning("demo store unavailable (%s)", type(exc).__name__)
        return None


def session_id() -> str:
    return st.session_state.setdefault("sid", secrets.token_urlsafe(16))


# --- lookup mode ------------------------------------------------------------------------------


def lookup_view() -> None:
    b = bundle()
    st.write(
        f"Type a website to see how often the two models cited it across the {b.answers} "
        "answers in the UK health study, how fresh its cited pages were, who was cited "
        "instead, and what could help. No model is called."
    )
    domain = st.text_input("Website", placeholder="nhs.uk or https://www.example.org/page")
    intent = st.selectbox(
        "Topic for the most-cited list (shown when the site was not cited)",
        b.intents,
        format_func=label,
    )
    if not domain.strip():
        return
    t0 = time.perf_counter()
    result = find(b, domain, intent)
    if isinstance(result, DomainCard):
        st.markdown(card_html(result), unsafe_allow_html=True)
    else:
        st.markdown(not_cited_html(result, intent), unsafe_allow_html=True)
    # one log line per distinct lookup in a session, not one per rerun (any widget change
    # reruns the page); the session keeps a one-way digest, never the text typed
    seen = st.session_state.setdefault("lookups_logged", set())
    query = f"{intent}\n{' '.join(domain.lower().split())}".encode()
    digest = hashlib.sha256(query).hexdigest()[:24]
    if digest not in seen:
        seen.add(digest)
        log_request("lookup", (time.perf_counter() - t0) * 1000, 0.0)


def top_view() -> None:
    b = bundle()
    intent = st.selectbox("Topic", [None, *b.intents], format_func=lambda i: label(i or "all"))
    rows = top_ten(b, intent)
    st.dataframe(
        [
            {
                "Rank": r.rank,
                "Publisher": r.publisher,
                "Answers citing it": f"{r.answers_citing} of {r.answers}",
                "Share": f"{r.share:.0%}",
            }
            for r in rows
        ],
        hide_index=True,
        width="stretch",
    )
    st.caption("Answers from both models and both runs, pooled.")


# --- passkey sign-in --------------------------------------------------------------------------


def ceremony(kind: str, make: Any) -> tuple[str, Any, str]:
    """This session's pending ceremony of `kind`, made fresh when missing or expired."""
    slot = f"pending_{kind}"
    held = st.session_state.get(slot)
    if held is None or held[1].expires < time.time():
        options, pending = make()
        held = (options, pending, secrets.token_urlsafe(8))
        st.session_state[slot] = held
    return held


def finish(kind: str, response: Any, nonce: str, done: Any) -> None:
    """Handle a component response for this session's pending `kind` ceremony. Any outcome
    uses up the challenge; the page reruns so the button carries a fresh one, and a message
    for the visitor survives the rerun."""
    cred, err = C.parse_response(response, nonce)
    if err is None and cred is None:
        return  # no click yet, or a stale value from an earlier ceremony
    _, pending, _ = st.session_state.pop(f"pending_{kind}")
    if err:
        st.session_state["flash"] = "The passkey step did not finish; try again."
    else:
        try:
            done(pending, cred)
        except AuthRefused as exc:
            st.session_state["flash"] = exc.reason
        except Exception as exc:  # never a traceback: AuthRefused covers the known failures
            LOG.warning("passkey step failed (%s)", type(exc).__name__)
            st.session_state["flash"] = "The passkey step failed; try again later."
    st.rerun()


def signed_in(credential_id: str) -> None:
    st.session_state.pop("grant", None)  # one registration per code entry
    st.session_state["passkey_id"] = credential_id


def sign_in_view(pk: Passkeys, gate: RegistrationGate) -> None:
    st.subheader("Sign in with your passkey")
    if flash := st.session_state.pop("flash", None):
        st.warning(flash)
    options, _, nonce = ceremony("sign_in", pk.authentication_options)
    res = passkey_widget(
        key="cw-sign-in",
        data=C.component_data("get", options, nonce, "Sign in with a passkey"),
        on_response_change=lambda: None,
    )
    finish(
        "sign_in",
        res.get("response"),
        nonce,
        lambda pending, cred: signed_in(pk.finish_authentication(pending, cred).credential_id),
    )

    with st.expander("New here? Register a passkey (needs a code from the owner)"):
        grant = st.session_state.get("grant")
        if grant is None or grant.expires < time.time():
            with st.form("code"):
                code = st.text_input("Registration code", type="password")
                go = st.form_submit_button("Check code")
            if go:
                try:
                    st.session_state["grant"] = gate.check(session_id(), code)
                    st.rerun()
                except AuthRefused as exc:
                    st.error(exc.reason)
            return
        options, _, nonce = ceremony(
            "register", lambda: pk.registration_options(grant, session_id())
        )
        res = passkey_widget(
            key="cw-register",
            data=C.component_data("create", options, nonce, "Create a passkey for this demo"),
            on_response_change=lambda: None,
        )
        finish(
            "register",
            res.get("response"),
            nonce,
            lambda pending, cred: signed_in(pk.finish_registration(pending, cred).credential_id),
        )


# --- live mode --------------------------------------------------------------------------------


def live_view() -> None:
    env = secret_env()
    if problem := S.live_problem(env):
        st.info(problem)
        return
    kv = store()
    if kv is None:
        st.warning(STORE_DOWN)
        return
    try:
        pk = Passkeys(
            env["CITEWATCH_DEMO_RP_ID"], env["CITEWATCH_DEMO_ORIGIN"], CredentialStore(kv)
        )
        gate = RegistrationGate(
            kv, env["CITEWATCH_DEMO_CODE_HASH"], env["CITEWATCH_DEMO_CODE_SALT"]
        )
    except ValueError:  # a malformed RP ID or origin: say so, never show the values
        st.info("Live mode is not configured correctly on this deployment; lookup mode works.")
        return
    identity = st.session_state.get("passkey_id")
    if not identity:
        sign_in_view(pk, gate)
        return
    guard = SpendGuard(kv)
    cfg, prices, measured = study()
    owner_ok = S.has_owner_keys(env)
    left = guard.remaining_today()
    budget = "unavailable" if left is None else f"${left:.2f} of ${guard.daily_cap:.2f}"
    st.caption(
        f"Signed in with a passkey. Owner's budget left today: {budget} · each question may "
        f"cost at most ${guard.per_request_cap:.2f} · {guard.rate_limit} questions per hour."
    )
    choices = (["The owner's keys"] if owner_ok else []) + ["My own API keys"]
    pay = st.radio("Run on", choices, horizontal=True)
    own = pay == "My own API keys"
    key_a = key_o = ""
    with st.form("live"):
        question = st.text_area("Question", max_chars=MAX_QUESTION_CHARS)
        if own:
            st.caption(
                "Your keys are used for this request only: held in this session's memory, "
                "never logged, stored or shown, and sent only to the provider. The per-request "
                "limit still applies; your questions do not use the owner's budget."
            )
            key_a = st.text_input("Anthropic API key", type="password")
            key_o = st.text_input("OpenAI API key", type="password")
        go = st.form_submit_button(f"Ask {' and '.join(cfg.models)}")
    if st.button("Sign out"):
        st.session_state.pop("passkey_id", None)
        st.rerun()
    if not go:
        return
    keys = ProviderKeys(key_a, key_o) if own else S.owner_keys(env)
    try:
        with st.spinner("Asking both models with web search..."):
            result = run_live(
                question,
                identity=identity,
                cfg=cfg,
                guard=guard,
                runners=make_runners(keys, cfg.models),
                prices=prices,
                measured=measured,
                owner_keys=not own,
            )
    except Exception as exc:  # never a traceback: it could carry request text
        LOG.warning("live request failed (%s)", type(exc).__name__)
        st.error("Something went wrong with this request. Lookup mode always works.")
        return
    st.markdown(live_html(result), unsafe_allow_html=True)
    st.caption("Citations only: the answers' text is not shown (a study rule, D-17).")


def main() -> None:
    st.set_page_config(page_title="citewatch demo", layout="centered")
    # also in demo/.streamlit/config.toml: an uncaught error shows a generic message only
    st.set_option("client.showErrorDetails", "none")
    st.markdown(CSS, unsafe_allow_html=True)
    st.title("Is your site cited by AI answers?")
    st.caption(
        f"From citewatch's UK health study: {bundle().answers} answers from two models with "
        "web search. "
        f"[Findings]({DASHBOARD}) · [Code and data]({REPO}). Research, not medical advice."
    )
    look, top, live = st.tabs(["Look up a site", "Top ten by topic", "Live question"])
    with look:
        lookup_view()
    with top:
        top_view()
    with live:
        live_view()


main()
