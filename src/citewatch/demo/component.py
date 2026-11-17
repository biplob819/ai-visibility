"""The browser half of passkey sign-in: a Streamlit components-v2 element (inline JS, no build).

Streamlit has no WebAuthn. A v2 component runs in the app's own document rather than in an
iframe, so `navigator.credentials` sees the app's origin and no iframe permission policy is in
the way (v1 component iframes allow `publickey-credentials-get` but not `-create`). The page
passes the options JSON that py_webauthn generated; on the visitor's click (browsers require a
user gesture) the component runs `navigator.credentials.create` or `.get`, encodes the result as
WebAuthn JSON (base64url fields) and returns it as a trigger value. Verification happens on the
server (`citewatch.demo.passkeys`); the browser is never trusted with the outcome.
"""

from __future__ import annotations

import json

COMPONENT_NAME = "citewatch_passkey"

CSS = """
.cw-passkey button {
  font: inherit; padding: .5rem 1rem; border-radius: .5rem; cursor: pointer;
  border: 1px solid var(--st-primary-color, #ff4b4b); background: transparent;
  color: var(--st-text-color, inherit);
}
.cw-passkey button:disabled { opacity: .6; cursor: default; }
.cw-passkey p { margin: .4rem 0 0 0; font-size: .9rem; opacity: .8; }
"""

JS = r"""
const b64urlToBuf = (s) => {
  const pad = '='.repeat((4 - (s.length % 4)) % 4);
  const bin = atob((s + pad).replace(/-/g, '+').replace(/_/g, '/'));
  return Uint8Array.from(bin, (c) => c.charCodeAt(0)).buffer;
};
const bufToB64url = (buf) => {
  if (!buf) return null;
  let bin = '';
  new Uint8Array(buf).forEach((b) => { bin += String.fromCharCode(b); });
  return btoa(bin).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
};
const creationOptions = (o) => ({
  ...o,
  challenge: b64urlToBuf(o.challenge),
  user: { ...o.user, id: b64urlToBuf(o.user.id) },
  excludeCredentials: (o.excludeCredentials || []).map((c) => ({ ...c, id: b64urlToBuf(c.id) })),
});
const requestOptions = (o) => ({
  ...o,
  challenge: b64urlToBuf(o.challenge),
  allowCredentials: (o.allowCredentials || []).map((c) => ({ ...c, id: b64urlToBuf(c.id) })),
});
const credentialJSON = (cred, mode) => {
  const r = cred.response;
  const response = { clientDataJSON: bufToB64url(r.clientDataJSON) };
  if (mode === 'create') {
    response.attestationObject = bufToB64url(r.attestationObject);
    response.transports = r.getTransports ? r.getTransports() : [];
  } else {
    response.authenticatorData = bufToB64url(r.authenticatorData);
    response.signature = bufToB64url(r.signature);
    response.userHandle = bufToB64url(r.userHandle);
  }
  return {
    id: cred.id,
    rawId: bufToB64url(cred.rawId),
    type: cred.type,
    response,
    clientExtensionResults: cred.getClientExtensionResults ? cred.getClientExtensionResults() : {},
    authenticatorAttachment: cred.authenticatorAttachment || null,
  };
};

export default function (component) {
  const { data, setTriggerValue, parentElement } = component;
  let root = parentElement.querySelector('.cw-passkey');
  if (!root) {
    root = document.createElement('div');
    root.className = 'cw-passkey';
    parentElement.appendChild(root);
  }
  root.replaceChildren();
  if (!data || !data.options) return;
  const button = document.createElement('button');
  button.type = 'button';
  button.textContent = data.label;
  const message = document.createElement('p');
  root.append(button, message);
  if (!window.PublicKeyCredential || !navigator.credentials) {
    button.disabled = true;
    message.textContent = 'This browser does not support passkeys.';
    return;
  }
  button.onclick = async () => {
    button.disabled = true;
    message.textContent = 'Waiting for your passkey...';
    const options = JSON.parse(data.options);
    try {
      const cred = data.mode === 'create'
        ? await navigator.credentials.create({ publicKey: creationOptions(options) })
        : await navigator.credentials.get({ publicKey: requestOptions(options) });
      message.textContent = 'Checking...';
      setTriggerValue('response', JSON.stringify({
        nonce: data.nonce, credential: credentialJSON(cred, data.mode),
      }));
    } catch (e) {
      button.disabled = false;
      const name = (e && e.name) || 'Error';
      message.textContent = 'The passkey step did not finish (' + name + '). Try again.';
      setTriggerValue('response', JSON.stringify({ nonce: data.nonce, error: name }));
    }
  };
}
"""


def component_data(mode: str, options_json: str, nonce: str, label: str) -> dict[str, str]:
    """What the page passes to the component on mount."""
    if mode not in ("create", "get"):
        raise ValueError("mode is 'create' or 'get'")
    json.loads(options_json)  # must be the JSON py_webauthn produced
    return {"mode": mode, "options": options_json, "nonce": nonce, "label": label}


def parse_response(raw: str | None, nonce: str) -> tuple[dict[str, object] | None, str | None]:
    """(credential, None) for this ceremony's response, (None, error name) for a browser-side
    failure, (None, None) when there is nothing for this ceremony (no click yet, or a stale
    value from an earlier one)."""
    if not raw:
        return None, None
    try:
        d = json.loads(raw)
    except ValueError:
        return None, "unreadable"
    if not isinstance(d, dict) or d.get("nonce") != nonce:
        return None, None
    if d.get("error"):
        return None, str(d["error"])[:40]
    cred = d.get("credential")
    return (cred, None) if isinstance(cred, dict) else (None, "unreadable")
