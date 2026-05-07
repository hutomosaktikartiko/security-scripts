import argparse
import os
import re
import subprocess
from dotenv import dotenv_values

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def load_env(path: str) -> dict:
    cfg = dotenv_values(path)
    for k in ("PROJECT_NAME", "SUPABASE_URL", "SUPABASE_ANON_KEY"):
        if not cfg.get(k):
            raise ValueError(f"{k} missing in {path}")
    return cfg


def load_keywords(project: str) -> list[str]:
    words = set()
    for path in (os.path.join(SCRIPT_DIR, "input", "table_keywords.txt"),
                 os.path.join(SCRIPT_DIR, "input", project, "table_keywords.txt")):
        if os.path.exists(path):
            with open(path) as f:
                words.update(
                    l.strip() for l in f
                    if l.strip() and not l.startswith("#")
                )
    return sorted(words)


def extract(so_path: str, keywords: list[str]) -> list[str]:
    result = subprocess.run(
        ["strings", "-n", "4", so_path],
        capture_output=True, text=True, errors="ignore",
    )
    pattern = re.compile(r'^[a-z][a-z_]{2,39}$')
    found = set()
    for line in result.stdout.splitlines():
        s = line.strip()
        if pattern.match(s) and any(kw in s for kw in keywords):
            found.add(s)
    return sorted(found)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--env", required=True)
    args = parser.parse_args()

    env_path = args.env
    if not os.path.isabs(env_path) and not os.path.exists(env_path):
        env_path = os.path.join(SCRIPT_DIR, env_path)

    cfg     = load_env(env_path)
    project = cfg["PROJECT_NAME"]
    so_path = cfg.get("SO_FILE_PATH", "")

    out_dir  = os.path.join(SCRIPT_DIR, "output", project)
    out_file = os.path.join(out_dir, "table_candidates.txt")
    os.makedirs(out_dir, exist_ok=True)

    print(f"\n  Project : {project}")

    if not so_path or not os.path.exists(so_path):
        print(f"  SO file : not found ({so_path})")
        print(f"  Nothing to extract.")
        return

    keywords = load_keywords(project)
    print(f"  Keywords: {len(keywords)}  (global + project)")
    print(f"  SO file : {so_path}")
    candidates = extract(so_path, keywords)
    print(f"  Found   : {len(candidates)} candidates\n")

    for c in candidates:
        print(f"    {c}")

    with open(out_file, "w") as f:
        f.write("\n".join(candidates))

    print(f"\n  Saved : output/{project}/table_candidates.txt")
    print(f"  Next  : python3 table_enumerate.py --env {args.env}")


if __name__ == "__main__":
    main()
