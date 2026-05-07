import argparse
import os
import re
import subprocess
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
    s.mount("https://", HTTPAdapter(max_retries=Retry(total=2, backoff_factor=1)))
    return s


def hdrs(key: str) -> dict:
    return {"apikey": key, "Authorization": f"Bearer {key}"}


def input_path(*parts) -> str:
    return os.path.join(SCRIPT_DIR, "input", *parts)


def output_path(*parts) -> str:
    return os.path.join(SCRIPT_DIR, "output", *parts)


# ── Sources ───────────────────────────────────────────────────────────────────

def load_wordlist(project: str) -> list[str]:
    words = set()
    for path in (input_path("storage_buckets.txt"),
                 input_path(project, "storage_buckets.txt")):
        if os.path.exists(path):
            with open(path) as f:
                words.update(l.strip() for l in f if l.strip() and not l.startswith("#"))
    return sorted(words)


def extract_from_apk(so_path: str, keywords: list[str]) -> list[str]:
    if not so_path or not os.path.exists(so_path):
        return []
    result  = subprocess.run(["strings", "-n", "4", so_path],
                             capture_output=True, text=True, errors="ignore")
    pattern = re.compile(r'^[a-z][a-z0-9_-]{2,30}$')
    found   = set()
    for line in result.stdout.splitlines():
        s = line.strip()
        if pattern.match(s) and any(kw in s for kw in keywords):
            found.add(s)
    return sorted(found)


def extract_from_db(session: requests.Session, url: str, key: str) -> list[str]:
    buckets     = set()
    url_pattern = re.compile(r'/storage/v1/object/(?:public|sign)/([^/?]+)/')

    r = session.get(f"{url}/rest/v1/", headers=hdrs(key), timeout=8)
    if r.status_code != 200:
        return []

    tables = [p.lstrip("/") for p in r.json().get("paths", {}).keys()]
    for table in tables:
        try:
            r = session.get(
                f"{url}/rest/v1/{table}",
                headers={**hdrs(key), "Range": "0-4"},
                params={"select": "*"},
                timeout=8,
            )
            if r.status_code not in (200, 206):
                continue
            rows = r.json()
            if not isinstance(rows, list):
                continue
            for row in rows:
                for col, val in row.items():
                    if "url" in col.lower() and isinstance(val, str):
                        m = url_pattern.search(val)
                        if m:
                            buckets.add(m.group(1))
        except Exception:
            continue
        time.sleep(0.1)

    return sorted(buckets)


# ── Probe ─────────────────────────────────────────────────────────────────────

def probe(session: requests.Session, url: str, bucket: str, key: str) -> tuple[str, bool]:
    try:
        r = session.get(
            f"{url}/storage/v1/object/public/{bucket}/__probe__",
            headers=hdrs(key), timeout=8,
        )
    except Exception:
        return "error", False

    if r.status_code == 200:
        return "public", True
    try:
        msg = r.json().get("message", "").lower()
    except Exception:
        return "error", False

    if "bucket not found" in msg:
        return "not_found", False
    if "not found" in msg:
        return "exists", True
    if r.status_code in (401, 403):
        return "exists", True
    return "not_found", False


def list_files(session: requests.Session, url: str, bucket: str, key: str) -> list:
    try:
        r = session.post(
            f"{url}/storage/v1/object/list/{bucket}",
            headers={**hdrs(key), "Content-Type": "application/json"},
            json={"prefix": "", "limit": 100, "offset": 0},
            timeout=8,
        )
        if r.status_code == 200:
            data = r.json()
            if isinstance(data, list) and (not data or "name" in data[0]):
                return data
    except Exception:
        pass
    return []


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--env",   required=True)
    parser.add_argument("--delay", type=float, default=0.3)
    args = parser.parse_args()

    cfg     = load_env(args.env)
    project = cfg["PROJECT_NAME"]
    url     = cfg["SUPABASE_URL"]
    key     = cfg["SUPABASE_ANON_KEY"]
    so_path = cfg.get("SO_FILE_PATH", "")

    out_file = output_path(project, "buckets.txt")
    os.makedirs(os.path.dirname(out_file), exist_ok=True)

    session = make_session()

    print(f"\n  Project : {project}")
    print(f"  Target  : {url}")
    print(f"\n  Gathering candidates...")

    src1 = load_wordlist(project)
    print(f"  [1/3] Wordlist   : {len(src1)}")

    src2 = extract_from_apk(so_path, src1)
    print(f"  [2/3] APK binary : {len(src2)}")

    src3 = extract_from_db(session, url, key)
    print(f"  [3/3] DB hint    : {len(src3)}  {src3 if src3 else ''}")

    candidates = sorted(set(src1 + src2 + src3))
    print(f"\n  Total unique     : {len(candidates)}")
    print(f"\n  Probing...\n")
    print(f"  {'Status':<12} {'Bucket':<30} {'Files':<8} Sample")
    print(f"  {'-' * 65}")

    found = []
    for name in candidates:
        status, exists = probe(session, url, name, key)
        time.sleep(args.delay)
        if not exists:
            continue

        files  = list_files(session, url, name, key)
        sample = ", ".join(f["name"] for f in files[:3] if f.get("name"))
        label  = "[public]" if status == "public" else "[exists]"
        print(f"  {label:<12} {name:<30} {len(files):<8} {sample}")
        found.append(name)
        time.sleep(args.delay)

    print(f"\n  {'─' * 65}")
    print(f"  Found  : {len(found)} bucket(s)")

    if found:
        with open(out_file, "w") as f:
            f.write("\n".join(found))
        print(f"  Saved  : output/{project}/buckets.txt")
        print(f"\n  Next   : python3 storage_dump.py --env {args.env}")


if __name__ == "__main__":
    main()
