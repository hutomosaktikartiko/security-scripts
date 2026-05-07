import requests
from config import SUPABASE_URL, HEADERS

INTROSPECTION_QUERY = """
{
    __schema {
        types {
            name
            kind
            fields {
                name
                type {
                    name
                }
            }
        }
    }
}
"""

def graphql_introspect():
    url = f"{SUPABASE_URL}/graphql/v1"
    r = requests.post(url, headers=HEADERS, json={"query": INTROSPECTION_QUERY})

    print(f"Status: {r.status_code}")

    data = r.json()

    if "errors" in data:
        for err in data["errors"]:
            print(f"Error: {err['message']}")
        return

    types = data["data"]["__schema"]["types"]

    # Filter out non-object types and collect field names
    tables = [
        t for t in types
        if t["kind"] == "OBJECT"
        and not t["name"].startswith("__")
        and t["name"][0].isupper()
    ]

    print(f"\nTotal tables found: {len(tables)}")
    print(f"\n=== TABLES & COLUMNS ===")
    for table in sorted(tables, key=lambda x: x["name"]):
        print(f"\n {table['name']}")
        if table.get("fields"):
            for field in table["fields"]:
                print(f"    - {field['name']}: {field['type'].get('name', '?')}")

graphql_introspect()