import argparse
import json
import os
import uuid
import requests
from datetime import datetime
from dotenv import dotenv_values
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
MARKER     = "[SECURITY_TEST]"


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


def read_schemas(project: str) -> dict:
    path = output_path(project, "table_schemas.json")
    if not os.path.exists(path):
        return {}
    with open(path) as f:
        return json.load(f)


def fetch_dump_row(project: str, table: str) -> tuple[str | None, dict | None, str | None]:
    """Return (row_id, full_row, update_col) from the latest dump, or (None, None, None)."""
    proj_dir = output_path(project)
    if not os.path.exists(proj_dir):
        return None, None, None

    dump_dirs = sorted(
        (d for d in os.listdir(proj_dir) if d.startswith("table_dump_")),
        reverse=True,
    )
    for dump_dir in dump_dirs:
        path = os.path.join(proj_dir, dump_dir, f"{table}.json")
        if not os.path.exists(path):
            continue
        with open(path) as f:
            rows = json.load(f)
        if not rows:
            continue
        row = rows[0]
        row_id = row.get("id")
        if not row_id:
            continue
        update_col = next(
            (k for k, v in row.items()
             if isinstance(v, str)
             and k != "id"
             and not k.endswith("_id")
             and not k.endswith("_at")),
            None,
        )
        return row_id, row, update_col

    return None, None, None


DUMMY = {
    "uuid":      lambda: str(uuid.uuid4()),
    "timestamp": lambda: "2099-01-01T00:00:00Z",
    "boolean":   lambda: False,
    "integer":   lambda: 0,
    "float":     lambda: 0.0,
    "json":      lambda: {},
    "array":     lambda: [],
    "string":    lambda: f"{MARKER} test",
}


def resolve_fk(session: requests.Session, url: str, key: str,
               col_name: str, cache: dict) -> str | None:
    base = col_name[:-3]  # strip "_id"
    for ref_table in (base + "s", base):
        if ref_table in cache:
            return cache[ref_table]
        try:
            r = session.get(
                f"{url}/rest/v1/{ref_table}",
                headers=hdrs(key),
                params={"select": "id", "limit": "1"},
                timeout=5,
            )
            if r.status_code == 200:
                rows = r.json()
                val = rows[0].get("id") if rows else None
                cache[ref_table] = val
                return val
            cache[ref_table] = None
        except Exception:
            cache[ref_table] = None
    return None


def build_payload(test_id: str, schema: list[dict],
                  session: requests.Session, url: str, key: str,
                  fk_cache: dict) -> dict:
    payload = {}
    for col in schema:
        name, tipe = col["col"], col["type"]
        if name == "id":
            payload[name] = test_id
        elif name.endswith("_id") and tipe == "uuid":
            real_id = resolve_fk(session, url, key, name, fk_cache)
            payload[name] = real_id if real_id else str(uuid.uuid4())
        else:
            payload[name] = DUMMY.get(tipe, DUMMY["string"])()
    return payload


def classify(status: int) -> str:
    if status in (401, 403):
        return "protected"
    if status in (200, 201, 204):
        return "VULNERABLE"
    if status in (400, 409, 422):
        return "reachable (validation error)"
    return f"unknown ({status})"


def test_insert(session: requests.Session, url: str, key: str, table: str,
                schema: list[dict], fk_cache: dict) -> tuple[str, str | None]:
    test_id = str(uuid.uuid4())
    payload = build_payload(test_id, schema, session, url, key, fk_cache) if schema else {"id": test_id}
    r = session.post(
        f"{url}/rest/v1/{table}",
        headers={**hdrs(key), "Prefer": "return=representation"},
        json=payload,
        timeout=8,
    )
    label = classify(r.status_code)
    row_id = None
    if r.status_code in (200, 201):
        try:
            inserted = r.json()
            row_id = inserted[0].get("id") if inserted else test_id
        except Exception:
            row_id = test_id
    return label, row_id


def test_update_owned(session: requests.Session, url: str, key: str,
                      table: str, row_id: str, schema: list[dict]) -> str:
    """UPDATE on a row we just inserted — no restore needed."""
    update_col = next(
        (c["col"] for c in schema if c["type"] == "string" and c["col"] != "id"),
        None,
    )
    if not update_col:
        return "untestable (no string column)"
    r = session.patch(
        f"{url}/rest/v1/{table}",
        headers={**hdrs(key), "Prefer": "return=representation"},
        params={"id": f"eq.{row_id}"},
        json={update_col: f"{MARKER} update"},
        timeout=8,
    )
    return classify(r.status_code)


def test_update_existing(session: requests.Session, url: str, key: str,
                         table: str, row_id: str,
                         original_val: str, update_col: str) -> str:
    """UPDATE on an existing dump row — restore original value after."""
    r = session.patch(
        f"{url}/rest/v1/{table}",
        headers={**hdrs(key), "Prefer": "count=exact"},
        params={"id": f"eq.{row_id}"},
        json={update_col: f"{MARKER} update"},
        timeout=8,
    )

    if r.status_code not in (200, 204):
        return classify(r.status_code)

    # Confirm at least 1 row was actually affected
    cr = r.headers.get("content-range", "")
    affected = int(cr.split("/")[1]) if "/" in cr else 0
    if affected == 0:
        return "protected (0 rows affected)"

    # Row was changed — restore immediately
    restore = session.patch(
        f"{url}/rest/v1/{table}",
        headers={**hdrs(key), "Prefer": "count=exact"},
        params={"id": f"eq.{row_id}"},
        json={update_col: original_val},
        timeout=8,
    )
    if restore.status_code in (200, 204):
        return "VULNERABLE (restored)"
    return "VULNERABLE (restore failed — fix manually)"


def test_delete(session: requests.Session, url: str, key: str, table: str, row_id: str) -> str:
    r = session.delete(
        f"{url}/rest/v1/{table}",
        headers={**hdrs(key), "Prefer": "count=exact"},
        params={"id": f"eq.{row_id}"},
        timeout=8,
    )
    if r.status_code not in (200, 204):
        return classify(r.status_code)
    cr = r.headers.get("content-range", "")
    affected = int(cr.split("/")[1]) if "/" in cr else 0
    return "VULNERABLE" if affected > 0 else "protected (0 rows affected)"


def run_poc(session: requests.Session, url: str, key: str, table: str,
            schema: list[dict], fk_cache: dict, project: str) -> dict:
    print(f"\n  Table : {table}")
    print(f"  {'─' * 45}")

    insert_label, row_id = test_insert(session, url, key, table, schema, fk_cache)
    print(f"    INSERT : {insert_label}")

    if row_id:
        # Happy path: we own this row — test freely, cleanup via DELETE
        update_label = test_update_owned(session, url, key, table, row_id, schema)
        print(f"    UPDATE : {update_label}")

        delete_label = test_delete(session, url, key, table, row_id)
        print(f"    DELETE : {delete_label}")
        if "VULNERABLE" in delete_label:
            print(f"    Cleanup: [OK] test row removed")
        else:
            print(f"    Cleanup: [WARN] could not delete test row — remove id={row_id} manually")
    else:
        # INSERT failed — cascade to dump row for UPDATE test
        dump_id, dump_row, update_col = fetch_dump_row(project, table)

        if dump_id and update_col:
            original_val = dump_row[update_col]
            print(f"    UPDATE : testing on existing row  id={dump_id[:8]}…  col={update_col}")
            update_label = test_update_existing(
                session, url, key, table, dump_id, original_val, update_col,
            )
        else:
            update_label = "untestable (no dump — run table_dump.py first)"

        print(f"    UPDATE : {update_label}")
        print(f"    DELETE : untestable (insert failed)")
        delete_label = "untestable (insert failed)"

    return {"table": table, "insert": insert_label, "update": update_label, "delete": delete_label}


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

    tables   = read_open_tables(project)
    schemas  = read_schemas(project)
    session  = make_session()
    fk_cache = {}

    print(f"\n  Project : {project}")
    print(f"  Target  : {url}")
    print(f"  Tables  : {len(tables)}")
    print(f"  Marker  : '{MARKER}'  (test rows are auto-cleaned if DELETE succeeds)")
    print(f"  {'═' * 55}")

    results = [
        run_poc(session, url, key, table, schemas.get(table, []), fk_cache, project)
        for table in tables
    ]

    print(f"\n  {'═' * 55}")

    lines = [
        f"write_poc  {project}  {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"target     {url}",
        f"{'═' * 55}",
        f"{'Table':<30} {'INSERT':<35} {'UPDATE':<35} DELETE",
        f"{'-' * 105}",
    ]
    for r in results:
        lines.append(f"{r['table']:<30} {r['insert']:<35} {r['update']:<35} {r['delete']}")

    out_file = output_path(project, f"write_poc_{datetime.now().strftime('%Y%m%d')}.txt")
    with open(out_file, "w") as f:
        f.write("\n".join(lines))

    print(f"  Saved : output/{project}/write_poc_{datetime.now().strftime('%Y%m%d')}.txt")


if __name__ == "__main__":
    main()
