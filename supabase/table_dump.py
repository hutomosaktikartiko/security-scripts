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
PAGE_SIZE  = 1000


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


def output_path(*parts) -> str:
    return os.path.join(SCRIPT_DIR, "output", *parts)


def read_open_tables(project: str) -> list[str]:
    path = output_path(project, "open_tables.txt")
    if not os.path.exists(path):
        raise FileNotFoundError(f"Run table_enumerate.py first — {path} not found")
    with open(path) as f:
        return [l.strip() for l in f if l.strip()]


def dump_table(session: requests.Session, url: str, key: str, table: str, delay: float) -> list:
    rows, offset = [], 0
    while True:
        r = session.get(
            f"{url}/rest/v1/{table}",
            headers={**hdrs(key), "Prefer": "count=exact",
                     "Range": f"{offset}-{offset + PAGE_SIZE - 1}"},
            params={"select": "*"},
            timeout=10,
        )
        if r.status_code not in (200, 206):
            print(f"    [!] {r.status_code} at offset {offset}")
            break

        batch = r.json()
        if not batch:
            break

        rows.extend(batch)
        print(f"    {len(rows)} rows...", end="\r")

        cr = r.headers.get("Content-Range", "")
        if "/" in cr:
            total_str = cr.split("/")[1]
            if total_str != "*" and len(rows) >= int(total_str):
                break

        if len(batch) < PAGE_SIZE:
            break

        offset += PAGE_SIZE
        time.sleep(delay)

    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--env",   required=True)
    parser.add_argument("--table", default=None, help="Single table (default: all from enumerate output)")
    parser.add_argument("--delay", type=float, default=0.1)
    args = parser.parse_args()

    env_path = args.env
    if not os.path.isabs(env_path) and not os.path.exists(env_path):
        env_path = os.path.join(SCRIPT_DIR, env_path)

    cfg     = load_env(env_path)
    project = cfg["PROJECT_NAME"]
    url     = cfg["SUPABASE_URL"]
    key     = cfg["SUPABASE_ANON_KEY"]
    date    = datetime.now().strftime("%Y%m%d")
    out_dir = output_path(project, f"table_dump_{date}")
    os.makedirs(out_dir, exist_ok=True)

    tables = [args.table] if args.table else read_open_tables(project)

    session = make_session()

    print(f"\n  Project : {project}")
    print(f"  Target  : {url}")
    print(f"  Tables  : {tables}")
    print(f"  Output  : output/{project}/table_dump_{date}/\n")

    summary = []
    for table in tables:
        print(f"  Dumping '{table}'...")
        rows = dump_table(session, url, key, table, args.delay)
        dest = os.path.join(out_dir, f"{table}.json")
        with open(dest, "w") as f:
            json.dump(rows, f, indent=2, ensure_ascii=False)
        size_kb = os.path.getsize(dest) / 1024
        print(f"    [+] {len(rows)} rows  →  {table}.json  ({size_kb:.1f} KB)")
        summary.append((table, len(rows), size_kb))

    print(f"\n  {'─' * 50}")
    print(f"  {'Table':<28} {'Rows':>6}  {'Size':>8}")
    print(f"  {'-' * 46}")
    for table, count, size_kb in summary:
        print(f"  {table:<28} {count:>6}  {size_kb:>6.1f} KB")
    total_rows = sum(c for _, c, _ in summary)
    total_kb   = sum(s for _, _, s in summary)
    print(f"  {'-' * 46}")
    print(f"  {'TOTAL':<28} {total_rows:>6}  {total_kb:>6.1f} KB")
    print(f"\n  Saved to output/{project}/table_dump_{date}/")


if __name__ == "__main__":
    main()
