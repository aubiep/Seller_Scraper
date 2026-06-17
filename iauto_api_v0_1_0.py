"""
iAuto API Client  v0.1.0
========================
HTTP client for the UUNA TEK iAuto-01 handwriting machine's local API.

Endpoints (from API_Guide_Document.xlsx, the manufacturer spec):
  GET  /login?uin=<user>&passwd=<pass>     -> {"error":0} on success
  GET  /machine_status[?mids=<id,...>]     -> [{"mid","status","prog","total_prog"}]
  POST /write_template  (multipart)        -> {"error":N}
         parts: file = the JSON template, mid = machine id (optional)

The spec's Java reference posts the file as a multipart FileBody and each param
(mid) as a text StringBody, RFC6532 / UTF-8. The `requests` library produces an
equivalent multipart body: the file goes in `files=`, mid goes in `data=`.

write_template error codes:
   0  success
  -1  parameter error
  -2  no available machines
  -3  service busy
   1  failed to generate writing file (retry)
   2  need to log in to the software again

CONFIRMED live in prior sessions: /machine_status returns valid JSON with no auth.
ASSUMED, to be proven by the Phase 1 diagnostic on the real machine:
  - /login accepts these credentials and returns {"error":0}
  - /write_template accepts an external multipart POST and writes the letter
  - whether posting a template auto-starts the write (the write_template spec
    lists no start/clear params, unlike write_svg, so we assume it does)
  - the correct per-part content type for the file (we send application/json;
    the Java sample used multipart/form-data, switch FILE_CONTENT_TYPE if needed)
"""

import json
import os

import requests

FILE_CONTENT_TYPE = "application/json"

ERROR_MEANINGS = {
    0: "success",
    -1: "parameter error",
    -2: "no available machines",
    -3: "service busy",
    1: "failed to generate writing file (retry)",
    2: "need to log in to the software again",
}


class IAutoError(Exception):
    """Raised when the machine returns a non-success error code."""

    def __init__(self, code, context=""):
        self.code = code
        self.meaning = ERROR_MEANINGS.get(code, "unknown error code")
        msg = f"{context}: error={code} ({self.meaning})" if context else \
              f"error={code} ({self.meaning})"
        super().__init__(msg)


def load_config(project_dir=None):
    """Read config/machine.json and config/credentials.json. Returns a dict."""
    project_dir = project_dir or os.path.dirname(os.path.abspath(__file__))
    cfg_dir = os.path.join(project_dir, "config")
    with open(os.path.join(cfg_dir, "machine.json"), encoding="utf-8") as f:
        machine = json.load(f)
    creds = {}
    cred_path = os.path.join(cfg_dir, "credentials.json")
    if os.path.exists(cred_path):
        with open(cred_path, encoding="utf-8") as f:
            creds = json.load(f)
    return {"machine": machine, "credentials": creds}


class IAutoClient:
    def __init__(self, base_url, mid=None, timeout=15):
        self.base_url = base_url.rstrip("/")
        self.mid = mid
        self.timeout = timeout
        self.session = requests.Session()

    @classmethod
    def from_config(cls, project_dir=None):
        cfg = load_config(project_dir)
        m = cfg["machine"]
        return cls(m["base_url"], mid=m.get("mid"),
                   timeout=m.get("timeout_seconds", 15)), cfg["credentials"]

    # ── endpoints ────────────────────────────────────────────────────────────

    def login(self, uin, passwd):
        """Log in. Raises IAutoError if the machine reports a non-zero code."""
        r = self.session.get(f"{self.base_url}/login",
                             params={"uin": uin, "passwd": passwd},
                             timeout=self.timeout)
        r.raise_for_status()
        data = r.json()
        code = data.get("error")
        if code != 0:
            raise IAutoError(code, "login failed")
        return data

    def machine_status(self, mids=None):
        """Return the status list. No auth required."""
        params = {}
        if mids:
            params["mids"] = mids if isinstance(mids, str) else ",".join(mids)
        r = self.session.get(f"{self.base_url}/machine_status",
                            params=params, timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    def write_template(self, template_bytes, filename="template.json", mid=None,
                       raise_on_error=False):
        """
        POST a merged JSON template to the machine. Returns the parsed response
        with an added 'error_meaning'. Set raise_on_error=True to raise
        IAutoError on a non-zero code instead of returning it.
        """
        mid = mid if mid is not None else self.mid
        files = {"file": (filename, template_bytes, FILE_CONTENT_TYPE)}
        data = {}
        if mid:
            data["mid"] = mid
        r = self.session.post(f"{self.base_url}/write_template",
                            files=files, data=data, timeout=self.timeout)
        r.raise_for_status()
        result = r.json()
        code = result.get("error")
        result["error_meaning"] = ERROR_MEANINGS.get(code, "unknown error code")
        if raise_on_error and code != 0:
            raise IAutoError(code, "write_template failed")
        return result


if __name__ == "__main__":
    # Smoke check that does NOT touch the network: build a client from config
    # and confirm the multipart body assembles. Run the diagnostic for a live test.
    client, creds = IAutoClient.from_config()
    print("base_url:", client.base_url)
    print("mid:", client.mid)
    print("credentials present:", bool(creds.get("uin")))
    req = requests.Request(
        "POST", f"{client.base_url}/write_template",
        files={"file": ("template.json", b'{"x":1}', FILE_CONTENT_TYPE)},
        data={"mid": client.mid or ""},
    ).prepare()
    ctype = req.headers.get("Content-Type", "")
    print("multipart content-type:", ctype.split(";")[0])
    print("body has file part:", b'name="file"' in req.body)
    print("body has mid part:", b'name="mid"' in req.body)
    print("OK (no network call made)")
