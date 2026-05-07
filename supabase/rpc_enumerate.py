import argparse
import json
import os
import time
import requests
from dotenv import dotenv_values
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


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


def input_path(*parts) -> str:
    return os.path.join(SCRIPT_DIR, "input", *parts)


def output_path(*parts) -> str:
    return os.path.join(SCRIPT_DIR, "output", *parts)


def load_wordlist(project: str) -> list[str]:
    words = set()
    for path in (input_path("rpc_functions.txt"),
                 input_path(project, "rpc_functions.txt"),
                 output_path(project, "rpc_candidates.txt")):
        if os.path.exists(path):
            with open(path) as f:
                words.update(l.strip() for l in f if l.strip() and not l.startswith("#"))
    return sorted(words)


def fetch_openapi(session: requests.Session, url: str, key: str) -> list[dict]:
    """Extract RPC functions from PostgREST OpenAPI spec at /rest/v1/."""
    try:
        r = session.get(f"{url}/rest/v1/", headers=hdrs(key), timeout=10)
        if r.status_code != 200:
            return []
        paths = r.json().get("paths", {})
        fns = []
        for path, methods in paths.items():
            if not path.startswith("/rpc/"):
                continue
            name   = path[5:]
            params = []
            for p in methods.get("post", {}).get("parameters", []):
                if p.get("in") == "body":
                    props  = p.get("schema", {}).get("properties", {})
                    params = list(props.keys())
            fns.append({"name": name, "params": params})
        return fns
    except Exception:
        return []


def probe(session: requests.Session, url: str, key: str, name: str) -> tuple[int, dict | None]:
    try:
        r = session.post(f"{url}/rest/v1/rpc/{name}", headers=hdrs(key),
                         json={}, timeout=8)
        try:
            return r.status_code, r.json()
        except Exception:
            return r.status_code, None
    except Exception:
        return 0, None


def classify(status: int) -> str:
    if status == 200:          return "OPEN"
    if status in (400, 422):  return "EXISTS"   # function exists, needs params
    if status in (401, 403):  return "AUTH"
    return "NOT_FOUND"


def extract_params_from_error(body: dict | None) -> list[str]:
    """PostgREST sometimes hints the expected signature in the error message."""
    if not isinstance(body, dict):
        return []
    msg = body.get("message", body.get("hint", ""))
    if "(" in msg and ")" in msg:
        sig = msg[msg.index("(") + 1: msg.index(")")]
        if sig:
            return [p.strip().split()[-1] for p in sig.split(",") if p.strip()]
    return []


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--env",   required=True)
    parser.add_argument("--delay", type=float, default=0.2)
    args = parser.parse_args()

    env_path = args.env
    if not os.path.isabs(env_path) and not os.path.exists(env_path):
        env_path = os.path.join(SCRIPT_DIR, env_path)

    cfg     = load_env(env_path)
    project = cfg["PROJECT_NAME"]
    url     = cfg["SUPABASE_URL"]
    key     = cfg["SUPABASE_ANON_KEY"]

    out_file = output_path(project, "rpc_functions.json")
    os.makedirs(os.path.dirname(out_file), exist_ok=True)

    session = make_session()

    print(f"\n  Project : {project}")
    print(f"  Target  : {url}\n")

    # 1. OpenAPI
    print(f"  [1/2] OpenAPI spec...", end=" ", flush=True)
    openapi_fns   = fetch_openapi(session, url, key)
    openapi_names = {fn["name"] for fn in openapi_fns}
    print(f"{len(openapi_fns)} function(s) found")

    # 2. Wordlist
    wordlist = load_wordlist(project)
    to_probe = [w for w in wordlist if w not in openapi_names]
    print(f"  [2/2] Wordlist probe ({len(to_probe)} names)...\n")
    print(f"  {'Tag':<10} {'Function':<35} Source")
    print(f"  {'-' * 60}")

    results = []

    for fn in openapi_fns:
        status, body = probe(session, url, key, fn["name"])
        tag    = classify(status)
        params = fn["params"] or extract_params_from_error(body)
        results.append({"name": fn["name"], "params": params,
                         "status": status, "tag": tag, "source": "openapi"})
        print(f"  [{tag:<8}] {fn['name']:<35} openapi")
        time.sleep(args.delay)

    for name in to_probe:
        status, body = probe(session, url, key, name)
        tag = classify(status)
        if tag == "NOT_FOUND":
            time.sleep(args.delay)
            continue
        params = extract_params_from_error(body)
        results.append({"name": name, "params": params,
                         "status": status, "tag": tag, "source": "wordlist"})
        print(f"  [{tag:<8}] {name:<35} wordlist")
        time.sleep(args.delay)

    counts = {k: sum(1 for r in results if r["tag"] == k)
              for k in ("OPEN", "EXISTS", "AUTH")}

    print(f"\n  {'-' * 60}")
    print(f"  Open (callable) : {counts['OPEN']}")
    print(f"  Exists (params) : {counts['EXISTS']}")
    print(f"  Auth required   : {counts['AUTH']}")

    with open(out_file, "w") as f:
        json.dump(results, f, indent=2)

    print(f"\n  Saved : output/{project}/rpc_functions.json")
    if counts["OPEN"] + counts["EXISTS"] > 0:
        print(f"  Next  : python3 rpc_dump.py --env {args.env}")


if __name__ == "__main__":
    main()
