import argparse
import os
import re
import subprocess
from dotenv import dotenv_values

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# Filter for binary scan — must start with an action verb prefix
RPC_PREFIXES = (
    "get_", "fetch_", "list_", "find_", "search_", "query_",
    "create_", "insert_", "add_",
    "update_", "edit_", "set_",
    "delete_", "remove_",
    "submit_", "check_", "verify_", "validate_",
    "calculate_", "compute_", "generate_", "export_",
    "enroll_", "admin_",
)

# Supabase RPC call patterns in source code
SOURCE_PATTERNS = [
    re.compile(r'\.rpc\(\s*[\'"]([a-z][a-z0-9_]{1,49})[\'"]\s*[,)]'),
    re.compile(r'\brpc\(\s*[\'"]([a-z][a-z0-9_]{1,49})[\'"]\s*[,)]'),
]

BINARY_NAME_PATTERN = re.compile(r'^[a-z][a-z_]{2,49}$')

SOURCE_EXTENSIONS = {
    ".dart", ".java", ".kt", ".js", ".ts",
    ".json", ".xml", ".yaml", ".yml", ".smali",
}


def load_env(path: str) -> dict:
    cfg = dotenv_values(path)
    for k in ("PROJECT_NAME", "SUPABASE_URL", "SUPABASE_ANON_KEY"):
        if not cfg.get(k):
            raise ValueError(f"{k} missing in {path}")
    return cfg


def output_path(*parts) -> str:
    return os.path.join(SCRIPT_DIR, "output", *parts)


def scan_binary(so_path: str) -> list[str]:
    result = subprocess.run(
        ["strings", "-n", "4", so_path],
        capture_output=True, text=True, errors="ignore",
    )
    found = set()
    for line in result.stdout.splitlines():
        s = line.strip()
        if BINARY_NAME_PATTERN.match(s) and s.startswith(RPC_PREFIXES):
            found.add(s)
    return sorted(found)


def scan_sources(sources_path: str) -> list[str]:
    found = set()
    for root, _, files in os.walk(sources_path):
        for fname in files:
            if os.path.splitext(fname)[1].lower() not in SOURCE_EXTENSIONS:
                continue
            fpath = os.path.join(root, fname)
            try:
                with open(fpath, encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                for pattern in SOURCE_PATTERNS:
                    for match in pattern.finditer(content):
                        found.add(match.group(1))
            except Exception:
                continue
    return sorted(found)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--env", required=True)
    args = parser.parse_args()

    env_path = args.env
    if not os.path.isabs(env_path) and not os.path.exists(env_path):
        env_path = os.path.join(SCRIPT_DIR, env_path)

    cfg          = load_env(env_path)
    project      = cfg["PROJECT_NAME"]
    so_path      = cfg.get("SO_FILE_PATH", "")
    sources_path = cfg.get("SOURCES_PATH", "")

    out_dir  = output_path(project)
    out_file = os.path.join(out_dir, "rpc_candidates.txt")
    os.makedirs(out_dir, exist_ok=True)

    print(f"\n  Project : {project}")

    binary_results  = []
    sources_results = []

    # 1. Binary scan
    if so_path and os.path.exists(so_path):
        print(f"  [1/2] Binary scan ({so_path})...", end=" ", flush=True)
        binary_results = scan_binary(so_path)
        print(f"{len(binary_results)} candidate(s)")
        for c in binary_results:
            print(f"    {c}")
    else:
        print(f"  [1/2] Binary scan... skipped (SO_FILE_PATH not set or not found)")

    # 2. Source scan
    if sources_path and os.path.exists(sources_path):
        print(f"  [2/2] Source scan ({sources_path})...", end=" ", flush=True)
        sources_results = scan_sources(sources_path)
        print(f"{len(sources_results)} candidate(s)")
        for c in sources_results:
            print(f"    {c}")
    else:
        print(f"  [2/2] Source scan... skipped (SOURCES_PATH not set or not found)")

    merged = sorted(set(binary_results) | set(sources_results))

    if not merged:
        print(f"\n  No candidates found.")
        return

    print(f"\n  {'─' * 45}")
    print(f"  Binary   : {len(binary_results)}")
    print(f"  Sources  : {len(sources_results)}")
    print(f"  Total    : {len(merged)} (deduplicated)")

    with open(out_file, "w") as f:
        f.write("\n".join(merged))

    print(f"\n  Saved : output/{project}/rpc_candidates.txt")
    print(f"  Next  : python3 rpc_enumerate.py --env {args.env}")


if __name__ == "__main__":
    main()
