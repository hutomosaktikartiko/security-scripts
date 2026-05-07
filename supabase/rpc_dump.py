import argparse
import json
import os
import time
import requests
from datetime import datetime
from dotenv import dotenv_values
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

DUMMY_VALUES = {
    "uuid":      "00000000-0000-0000-0000-000000000000",
    "integer":   1,
    "float":     1.0,
    "boolean":   True,
    "string":    "test",
    "timestamp": "2024-01-01T00:00:00Z",
    "json":      {},
    "array":     [],
}

SENSITIVE_FIELDS = {
    "email", "phone", "password", "encrypted_password", "role",
    "raw_user_meta_data", "confirmed_at", "last_sign_in_at",
    "secret", "token", "api_key", "private_key",
}


def load_env(path: str) -> dict:
    cfg = dotenv_values(path)
    for k in ("PROJECT_NAME", "SUPABASE_URL", "SUPABASE_ANON_KEY"):
        if not cfg.get(k):
            raise ValueError(f"{k} missing in {path}")
    return cfg


def make_session() -> requests.Session:
    s = requests.Session()
    s.mount("https://", HTTPAdapter(max_retries=Retry(total=2, backoff_factor=0.5)))
    return s


def hdrs(key: str) -> dict:
    return {"apikey": key, "Authorization": f"Bearer {key}",
            "Content-Type": "application/json"}


def output_path(*parts) -> str:
    return os.path.join(SCRIPT_DIR, "output", *parts)


def guess_type(name: str) -> str:
    n = name.lower()
    if n == "id" or n.endswith("_id"):                       return "uuid"
    if n.endswith("_at"):                                    return "timestamp"
    if n.startswith("is_") or n.startswith("has_"):         return "boolean"
    if n in ("limit", "offset", "page", "size", "count") or n.endswith("_count"):
        return "integer"
    return "string"


def build_payload(params: list[str]) -> dict:
    return {p: DUMMY_VALUES[guess_type(p)] for p in params}


def call_fn(session: requests.Session, url: str, key: str,
            name: str, payload: dict) -> tuple[int, any]:
    try:
        r = session.post(f"{url}/rest/v1/rpc/{name}", headers=hdrs(key),
                         json=payload, timeout=10)
        try:
            return r.status_code, r.json()
        except Exception:
            return r.status_code, r.text
    except Exception as e:
        return 0, str(e)


def load_open_tables(project: str) -> set[str]:
    path = output_path(project, "open_tables.txt")
    if not os.path.exists(path):
        return set()
    with open(path) as f:
        return {l.strip() for l in f if l.strip()}


def detect_bypass(body: any) -> str | None:
    """Flag responses that contain sensitive fields — potential SECURITY DEFINER bypass."""
    if not isinstance(body, list) or not body or not isinstance(body[0], dict):
        return None
    cols = set(body[0].keys())
    hit  = cols & SENSITIVE_FIELDS
    if hit:
        return f"sensitive fields: {', '.join(sorted(hit))}"
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--env", required=True)
    args = parser.parse_args()

    env_path = args.env
    if not os.path.isabs(env_path) and not os.path.exists(env_path):
        env_path = os.path.join(SCRIPT_DIR, env_path)

    cfg     = load_env(env_path)
    project = cfg["PROJECT_NAME"]
    url     = cfg["SUPABASE_URL"]
    key     = cfg["SUPABASE_ANON_KEY"]

    rpc_file = output_path(project, "rpc_functions.json")
    if not os.path.exists(rpc_file):
        print(f"\n  rpc_functions.json not found — run rpc_enumerate.py first")
        return

    with open(rpc_file) as f:
        functions = json.load(f)

    to_call = [fn for fn in functions if fn["tag"] in ("OPEN", "EXISTS")]
    if not to_call:
        print(f"\n  No callable functions found — nothing to dump")
        return

    date    = datetime.now().strftime("%Y%m%d")
    out_dir = output_path(project, f"rpc_dump_{date}")
    os.makedirs(out_dir, exist_ok=True)

    session = make_session()

    print(f"\n  Project   : {project}")
    print(f"  Target    : {url}")
    print(f"  Functions : {len(to_call)}\n")
    print(f"  {'Status':<8} {'Function':<35} Notes")
    print(f"  {'─' * 65}")

    findings = []

    for fn in to_call:
        name    = fn["name"]
        params  = fn.get("params", [])
        payload = build_payload(params)

        status, body = call_fn(session, url, key, name, payload)

        # If payload didn't help, retry with empty
        if status in (400, 422) and payload:
            s2, b2 = call_fn(session, url, key, name, {})
            if s2 == 200:
                status, body = s2, b2

        row_count = len(body) if isinstance(body, list) else None
        bypass    = detect_bypass(body) if status == 200 else None

        note = ""
        if row_count is not None:
            note = f"{row_count} row(s)"
        if bypass:
            note += f"  !! {bypass}"

        tag = "OPEN" if status == 200 else str(status)
        print(f"  [{tag:<6}] {name:<35} {note}")

        record = {
            "name":    name,
            "params":  params,
            "payload": payload,
            "status":  status,
            "rows":    row_count,
            "bypass":  bypass,
            "body":    body,
        }
        findings.append(record)

        if status == 200 and body is not None:
            with open(os.path.join(out_dir, f"{name}.json"), "w") as f:
                json.dump(body, f, indent=2)

        time.sleep(0.2)

    open_fns   = [r for r in findings if r["status"] == 200]
    bypass_fns = [r for r in findings if r["bypass"]]

    print(f"\n  {'─' * 65}")
    print(f"  Callable : {len(open_fns)}")

    if bypass_fns:
        print(f"\n  !! SECURITY DEFINER BYPASS CANDIDATES")
        for r in bypass_fns:
            print(f"     {r['name']} — {r['bypass']}")

    summary_file = os.path.join(out_dir, "_summary.json")
    with open(summary_file, "w") as f:
        json.dump(findings, f, indent=2)

    if open_fns:
        print(f"\n  Saved : output/{project}/rpc_dump_{date}/")


if __name__ == "__main__":
    main()
