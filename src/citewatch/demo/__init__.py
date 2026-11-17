"""The citewatch demo (node D5.2, Tech Spec §9, OWNER D-58, D-59, D-73).

Lookup mode reads the bundled domain cards and never calls a model (DEM-01). Live mode asks one
question of both models behind passkey sign-in and a spend guard, and shows citations only, never
the answer prose (DEM-02, D-17). Everything a visitor can trigger lives in these modules so it is
testable without a browser; `demo/app.py` is a thin Streamlit page over them.
"""
