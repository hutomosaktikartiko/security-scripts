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
    s.mount("https://", HTTPAdapter(max_retries=Retry(total=2, backoff_factor=1)))
    return s


def hdrs(key: str) -> dict:
    return {"apikey": key, "Authorization": f"Bearer {key}"}


def input_path(*parts) -> str:
    return os.path.join(SCRIPT_DIR, "input", *parts)


def output_path(*parts) -> str:
    return os.path.join(SCRIPT_DIR, "output", *parts)


def load_candidates(project: str) -> list[str]:
    words = set()
    for path in (input_path("table_candidates.txt"),
                 output_path(project, "table_candidates.txt")):
        if os.path.exists(path):
            with open(path) as f:
                words.update(
                    l.strip() for l in f
                    if l.strip() and not l.startswith("#")
                )
    return sorted(words)


def get_row_count(session: requests.Session, url: str, key: str, table: str):
    r = session.get(
        f"{url}/rest/v1/{table}",
        headers={**hdrs(key), "Prefer": "count=exact"},
        params={"select": "*", "limit": "1"},
        timeout=8,
    )
    if r.status_code not in (200, 206):
        return None, r.status_code

    cr = r.headers.get("content-range", "")
    if "/" in cr:
        total = cr.split("/")[1]
        return (int(total) if total != "*" else "?"), r.status_code
    return 0, r.status_code


def infer_type(col: str, val) -> str:
    if isinstance(val, bool):  return "boolean"
    if isinstance(val, int):   return "integer"
    if isinstance(val, float): return "float"
    if isinstance(val, dict):  return "json"
    if isinstance(val, list):  return "array"
    col = col.lower()
    if col == "id" or col.endswith("_id"):             return "uuid"
    if col.endswith("_at"):                            return "timestamp"
    if col.startswith("is_") or col.startswith("has_"): return "boolean"
    if col.endswith("_url"):                           return "string"
    if col.endswith("_count") or col.endswith("_index"): return "integer"
    return "string"


def get_schema(session: requests.Session, url: str, key: str, table: str) -> list:
    r = session.get(
        f"{url}/rest/v1/{table}",
        headers=hdrs(key),
        params={"select": "*", "limit": "10"},
        timeout=8,
    )
    try:
        rows = r.json()
    except Exception:
        return []
    if not rows or not isinstance(rows, list):
        return []

    col_values: dict[str, list] = {}
    for row in rows:
        for col, val in row.items():
            if col not in col_values:
                col_values[col] = []
            if val is not None:
                col_values[col].append(val)

    schema = []
    for col in rows[0].keys():
        nonnull = col_values.get(col, [])
        schema.append((col, infer_type(col, nonnull[0] if nonnull else None)))
    return schema


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

    out_file = output_path(project, "open_tables.txt")
    os.makedirs(os.path.dirname(out_file), exist_ok=True)

    candidates = load_candidates(project)

    print(f"\n  Project    : {project}")
    print(f"  Target     : {url}")
    print(f"  Candidates : {len(candidates)}\n")
    print(f"  {'Status':<8} {'Table':<35} Rows")
    print(f"  {'-' * 55}")

    session = make_session()
    found, blocked, not_found = [], [], []

    for table in candidates:
        count, status = get_row_count(session, url, key, table)
        time.sleep(args.delay)

        if status in (200, 206):
            schema = get_schema(session, url, key, table)
            found.append((table, count, schema))
            print(f"  [OPEN]   {table:<35} {count}")
        elif status in (401, 403):
            blocked.append(table)
            print(f"  [AUTH]   {table:<35} need login")
        else:
            not_found.append(table)

    print(f"\n  {'-' * 55}")
    print(f"  Open (no auth) : {len(found)}")
    print(f"  Auth required  : {len(blocked)}")
    print(f"  Not found      : {len(not_found)}")

    if not found:
        return

    SEP = "  " + "─" * 60
    print(f"\n{SEP}")
    print(f"  OPEN TABLES — DETAIL")
    print(SEP)

    for table, count, schema in sorted(found, key=lambda x: (-(x[1] if isinstance(x[1], int) else 0))):
        print(f"\n  Table  : {table}  ({count} rows)")
        if schema:
            print(f"    {'Column':<30} Type")
            print(f"    {'-' * 42}")
            for col, tipe in schema:
                print(f"    {col:<30} {tipe}")
        print(f"  {'─' * 55}")

    with open(out_file, "w") as f:
        f.write("\n".join(t for t, _, _ in found))

    schemas = {t: [{"col": c, "type": tp} for c, tp in s] for t, _, s in found}
    schema_file = output_path(project, "table_schemas.json")
    with open(schema_file, "w") as f:
        json.dump(schemas, f, indent=2)

    print(f"\n  Saved : output/{project}/open_tables.txt")
    print(f"          output/{project}/table_schemas.json")
    print(f"  Next  : python3 table_dump.py --env {args.env}")
    print(f"          python3 table_write_poc.py --env {args.env}")


if __name__ == "__main__":
    main()
