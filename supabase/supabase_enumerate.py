import requests
from config import SUPABASE_URL, HEADERS

def get_row_count(table):
    r = requests.get(
        f"{SUPABASE_URL}/rest/v1/{table}?limit=1",
        headers={**HEADERS, "Prefer": "count=exact"}
    )
    if r.status_code not in (200, 206):
        return None, r.status_code

    content_range = r.headers.get("content-range", "")
    if "/" in content_range:
        total = content_range.split("/")[1]
        return int(total) if total != "*" else "?", r.status_code

    return 0, r.status_code


def get_allowed_methods(table):
    r = requests.options(f"{SUPABASE_URL}/rest/v1/{table}", headers=HEADERS)
    allow = r.headers.get("allow", "")

    crud = []
    if "GET"    in allow: crud.append("READ")
    if "POST"   in allow: crud.append("CREATE")
    if "PATCH"  in allow: crud.append("UPDATE")
    if "DELETE" in allow: crud.append("DELETE")
    return crud


def infer_type_from_value(val):
    if isinstance(val, bool):  return "boolean"
    if isinstance(val, int):   return "integer"
    if isinstance(val, float): return "float"
    if isinstance(val, dict):  return "json"
    if isinstance(val, list):  return "array"
    return "string"


def infer_type_from_name(col):
    col = col.lower()
    if col == "id" or col.endswith("_id"):    return "uuid"
    if col.endswith("_at"):                   return "timestamp"
    if col.startswith("is_"):                 return "boolean"
    if col.endswith("_url"):                  return "string"
    if col.endswith("_count") or col.endswith("_index"): return "integer"
    return "string"


def get_schema(table):
    # Get several rows to increase the chance of finding non-null values
    r = requests.get(f"{SUPABASE_URL}/rest/v1/{table}?limit=10", headers=HEADERS)
    try:
        rows = r.json()
    except Exception:
        return []

    if not rows or not isinstance(rows, list):
        return []

    # Collect all values per column from all rows
    col_values = {}
    for row in rows:
        for col, val in row.items():
            if col not in col_values:
                col_values[col] = []
            if val is not None:
                col_values[col].append(val)

    schema = []
    for col in rows[0].keys():
        non_null = col_values.get(col, [])
        if non_null:
            tipe = infer_type_from_value(non_null[0])
        else:
            # All rows are null — fallback to column name
            tipe = infer_type_from_name(col)
        schema.append((col, tipe))
    return schema

SEP  = "  " + "-" * 60
SEP2 = "  " + "=" * 60

def print_table_summary(table, count, methods, schema):
    method_str = ", ".join(methods) if methods else "none"
    print(f"\n  Table   : {table}")
    print(f"  Rows    : {count}")
    print(f"  Methods : {method_str}")
    if schema:
        print(f"  Schema  :")
        print(f"    {'Column':<30} Type")
        print(f"    {'-'*42}")
        for col, tipe in schema:
            print(f"    {col:<30} {tipe}")
    print(SEP)

def enumerate_tables():
    try:
        with open("./supabase/candidates.txt") as f:
            candidates = [line.strip() for line in f if line.strip()]
    except FileNotFoundError:
        print("candidates.txt not found. Run cara3a_extract.py first.")
        return

    print(f"\nTesting {len(candidates)} candidates...\n")
    print(f"  {'Status':<8} {'Table':<35} Info")
    print(SEP)

    found, blocked, not_found = [], [], []

    for table in candidates:
        count, status = get_row_count(table)

        if status in (200, 206):
            methods  = get_allowed_methods(table)
            schema   = get_schema(table)
            found.append((table, count, methods, schema))
            print(f"  [OPEN]   {table:<35} {count} rows  |  {', '.join(methods)}")
        elif status == 401:
            blocked.append(table)
            print(f"  [AUTH]   {table:<35} need login")
        else:
            not_found.append(table)
            print(f"  [404]    {table:<35} not found")

    print(SEP)
    print(f"  OPEN (no auth needed)  : {len(found)}")
    print(f"  AUTH (login required)  : {len(blocked)}")
    print(f"  Not found              : {len(not_found)}")

    if not found:
        return

    print(f"\n{SEP2}")
    print(f"  DETAIL: OPEN TABLES")
    print(SEP2)

    for table, count, methods, schema in sorted(found, key=lambda x: -x[1]):
        print_table_summary(table, count, methods, schema)


enumerate_tables()
