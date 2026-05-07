import json
import os
import requests
from datetime import datetime
from config import SUPABASE_URL, HEADERS

PAGE_SIZE = 1000
OUTPUT_DIR = f"./supabase/output/dump_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

def dump_table(table: str) -> list:
    rows = []
    offset = 0

    print(f"\n Dumping '{table}'...")

    while True:
        r = requests.get(
            f"{SUPABASE_URL}/rest/v1/{table}",
            headers={
                **HEADERS,
                "Range": f"{offset}-{offset + PAGE_SIZE - 1}",
                "Prefer": "count=exact",
            },
            params={"select": "*"},
        )

        if r.status_code not in (200, 206):
            print(f"    [!] Failed at offset {offset}: {r.status_code} - {r.text[:100]}")
            break

        batch = r.json()
        if not batch:
            break

        rows.extend(batch)
        print(f"    fetched {len(rows)} rows...", end="\r")

        # Content-Range header: "0-999/2919"
        content_range = r.headers.get("Content-Range", "")
        if "/" in content_range:
            total = int(content_range.split("/")[1])
            if len(rows) >= total:
                break
        
        if len(batch) < PAGE_SIZE:
            break
        
        offset += PAGE_SIZE
    
    print(f"    [+] Total: {len(rows)} rows          ")
    return rows

def save(table:str, rows:list):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    path = f"{OUTPUT_DIR}/{table}.json"
    with open(path, "w") as f:
        json.dump(rows, f, indent=2, ensure_ascii=False)
    size_kb = os.path.getsize(path) / 1024
    print(f"    [+] Saved -> {path} ({size_kb:.1f} KB)")

def main():
    print("=" * 60)
    print("FULL DATA DUMP")
    print("=" * 60)

    try:
        with open("./supabase/output/open_tables.txt") as f:
            open_tables = [line.strip() for line in f if line.strip()]
    except FileNotFoundError:
        print("open_tables.txt not found. Run enumerate first.")
        return

    summary = []

    for table in open_tables:
        rows = dump_table(table)
        save(table, rows)
        summary.append((table, len(rows)))

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"  {'Table':<25} {'Rows':>8}")
    print(f"  {'-'*35}")
    for table, count in summary:
        print(f"  {table:<25} {count:>8}")
    total = sum(c for _, c in summary)
    print(f"  {'-'*35}")
    print(f"  {'TOTAL':<25} {total:>8}")
    print(f"\n  Output directory: {OUTPUT_DIR}/")
    print("=" * 60)

if __name__ == "__main__":
    main()