# Publishing the name placeholder (OWNER D-29)

Run from your own terminal, with your PyPI token:

```
cd packaging/pypi-placeholder
uv build
uv publish        # asks for the token, or set UV_PUBLISH_TOKEN
```

The wheel and sdist contain only this folder's README and an empty `citewatch` module at 0.0.1.
The real package (`src/citewatch`, v0.1.0) is released at node B4.5.
