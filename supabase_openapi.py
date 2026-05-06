import requests
from config import SUPABASE_URL, HEADERS

def fetch_openapi():
    url = f"{SUPABASE_URL}/rest/v1"
    r = requests.get(url, headers=HEADERS)

    print(f"Status: {r.status_code}")

    if r.status_code != 200:
        print(f"Failed  : {r.json().get('message')}")
        print(f"Hint    : {r.json().get('hint', '-')}")
        return

    spec = r.json()
    paths = spec.get("paths", {})
    
    if not paths:
        print("No paths found.")
        return

    print(f"Total endpoints: {len(paths)}")
    print(f"\n=== EXPOSED TABLES ===")
    for path, methods in sorted(paths.items()):
        allowed = [m.upper() for m in methods if m != "parameters"]
        print(f" {path:<30} [{', '.join(allowed)}]")

fetch_openapi()