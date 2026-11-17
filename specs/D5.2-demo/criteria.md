# D5.2 acceptance criteria

**DEM-01** A Streamlit page in `demo/`: lookup by default (card, cited instead, improvement rows; not-cited message with top publishers for an intent), a top-ten picker by intent; no model is called.
**DEM-02** Live mode behind passkey (WebAuthn) sign-in, registration gated by the owner's numeric code (OWNER D-59), through the spend guard; both models with the §7.1 settings; citations only, never answer prose (D-17).
**DEM-03** Logs hold only time, mode, latency and cost; secrets come only from the host's secret store.
**DEM-04** Deployed to Streamlit Community Cloud, with a passkey registered and one live question answered.
**DEM-05** Visitors may use their own API keys, but still need a passkey; the keys stay in session memory only, never logged, stored or echoed; the per-request cap applies; only owner-key calls count toward the owner's daily cap.
