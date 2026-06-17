"""
Homebot API Client  v0.1.0
==========================
HTTP client for the Homebot Open API (https://api.homebotapp.com), used to
enroll seller leads on the Homebot Market Digest by creating Client + Home
records.

The API is JSON:API (media type application/vnd.api+json). Every request and
response body wraps the resource in a `data` envelope:

    { "data": { "type": "clients", "attributes": { ... } } }

Auth (primary): an Open API token sent as
    Authorization: open-api-token-v1 <token>

Operations this client covers (from homebot-openapi spec, 73 ops total):
    GET  /clients?filter[email]=<email>     find_client_by_email  (dedupe)
    POST /clients                           create_client
    POST /clients/{id}/homes                create_home
    POST /clients/{id}/market-interests     create_market_interest

UNVERIFIED against the live API (the reconstructed spec did not capture these):
  - the literal `data.type` values ("clients"/"homes"/"market-interests" by
    JSON:API convention) -- configurable in config/homebot.json
  - that Client+Home is exactly what triggers Market Digest enrollment
Prove both with the diagnostic before trusting a bulk push.
"""

import json
import os

import requests


class HomebotError(Exception):
    """Non-2xx response from the API. Carries status and parsed JSON:API errors."""

    def __init__(self, status, body):
        self.status = status
        self.body = body
        detail = ""
        if isinstance(body, dict) and body.get("errors"):
            parts = []
            for e in body["errors"]:
                parts.append(f"{e.get('status','')} {e.get('title','')} {e.get('detail','')}".strip())
            detail = " | ".join(parts)
        elif body:
            detail = str(body)[:300]
        super().__init__(f"HTTP {status}: {detail}")


def load_config(project_dir=None):
    project_dir = project_dir or os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(project_dir, "config", "homebot.json"), encoding="utf-8") as f:
        return json.load(f)


class HomebotClient:
    def __init__(self, base_url, token, auth_scheme="open-api-token-v1",
                 content_type="application/vnd.api+json", resource_types=None,
                 timeout=20):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.auth_scheme = auth_scheme
        self.content_type = content_type
        self.types = resource_types or {
            "client": "clients", "home": "homes", "market_interest": "market-interests"}
        self.timeout = timeout
        self.session = requests.Session()

    @classmethod
    def from_config(cls, project_dir=None):
        cfg = load_config(project_dir)
        token = os.environ.get("HOMEBOT_API_TOKEN") or cfg.get("api_token", "")
        return cls(
            cfg["base_url"], token,
            auth_scheme=cfg.get("auth_scheme", "open-api-token-v1"),
            content_type=cfg.get("content_type", "application/vnd.api+json"),
            resource_types=cfg.get("resource_types"),
            timeout=cfg.get("timeout_seconds", 20),
        ), cfg

    # ── low-level ────────────────────────────────────────────────────────────

    def _headers(self):
        return {
            "Authorization": f"{self.auth_scheme} {self.token}",
            "Accept": self.content_type,
            "Content-Type": self.content_type,
        }

    def has_token(self):
        return bool(self.token)

    def _request(self, method, path, params=None, body=None):
        if not self.token:
            raise HomebotError(0, {"errors": [{"title": "No API token",
                "detail": "Set api_token in config/homebot.json or HOMEBOT_API_TOKEN env."}]})
        url = f"{self.base_url}{path}"
        data = json.dumps(body).encode("utf-8") if body is not None else None
        r = self.session.request(method, url, params=params, data=data,
                                headers=self._headers(), timeout=self.timeout)
        try:
            parsed = r.json() if r.content else {}
        except ValueError:
            parsed = {"_raw": r.text[:500]}
        if not (200 <= r.status_code < 300):
            raise HomebotError(r.status_code, parsed)
        return parsed

    def _envelope(self, type_key, attributes):
        return {"data": {"type": self.types[type_key],
                         "attributes": {k: v for k, v in attributes.items() if v is not None}}}

    # ── operations ───────────────────────────────────────────────────────────

    def find_client_by_email(self, email):
        """Return the first matching client resource dict, or None."""
        resp = self._request("GET", "/clients", params={"filter[email]": email})
        data = resp.get("data")
        if isinstance(data, list):
            return data[0] if data else None
        return data or None

    def create_client(self, attributes):
        """Create a client. Returns the created resource dict (incl. 'id')."""
        resp = self._request("POST", "/clients", body=self._envelope("client", attributes))
        return resp.get("data", resp)

    def create_home(self, client_id, attributes):
        resp = self._request("POST", f"/clients/{client_id}/homes",
                            body=self._envelope("home", attributes))
        return resp.get("data", resp)

    def delete_client(self, client_id):
        """Delete a client. Used for cleanup of test records."""
        return self._request("DELETE", f"/clients/{client_id}")

    def create_market_interest(self, client_id, zipcode):
        resp = self._request("POST", f"/clients/{client_id}/market-interests",
                            body=self._envelope("market_interest", {"zipcode": zipcode}))
        return resp.get("data", resp)


if __name__ == "__main__":
    # No-network smoke check: build client from config, assemble a sample
    # envelope, and report whether a token is present.
    client, cfg = HomebotClient.from_config()
    print("base_url:", client.base_url)
    print("auth header:", client._headers()["Authorization"].split()[0], "(token "
          + ("present" if client.has_token() else "MISSING -- set it before live calls") + ")")
    print("content-type:", client.content_type)
    print("resource types:", client.types)
    sample = client._envelope("client", {
        "first-name": "Jordan", "last-name": "Sample",
        "email": "jordan@example.com", "lead-source": cfg["defaults"]["lead_source"],
        "locale": cfg["defaults"]["locale"], "buyers-access": None})
    print("sample client envelope:")
    print(json.dumps(sample, indent=1))
    print("OK (no network call made)")
