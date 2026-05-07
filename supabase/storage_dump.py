import argparse
import os
import re
import time
import requests
from dotenv import dotenv_values
from datetime import datetime
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
IMAGE_COLS = ["image_url", "option_a_image_url", "option_b_image_url",
              "option_c_image_url", "option_d_image_url", "option_e_image_url"]


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


def read_buckets(project: str) -> list[str]:
    path = output_path(project, "buckets.txt")
    if not os.path.exists(path):
        raise FileNotFoundError(f"Run storage_enumerate.py first — {path} not found")
    with open(path) as f:
        return [l.strip() for l in f if l.strip()]


def fetch_urls_from_db(session: requests.Session, url: str, key: str) -> set[str]:
    urls, offset, page = set(), 0, 1000
    while True:
        r = session.get(
            f"{url}/rest/v1/questions",
            headers={**hdrs(key), "Range": f"{offset}-{offset + page - 1}"},
            params={"select": ",".join(IMAGE_COLS)},
            timeout=10,
        )
        if r.status_code not in (200, 206):
            break
        rows = r.json()
        if not rows:
            break
        for row in rows:
            for col in IMAGE_COLS:
                val = row.get(col)
                if val and str(val).startswith("http"):
                    urls.add(val)
        if len(rows) < page:
            break
        offset += page
        time.sleep(0.1)
    return urls


def list_files(session: requests.Session, url: str, bucket: str, key: str) -> list:
    all_files, offset = [], 0
    while True:
        try:
            r = session.post(
                f"{url}/storage/v1/object/list/{bucket}",
                headers={**hdrs(key), "Content-Type": "application/json"},
                json={"prefix": "", "limit": 100, "offset": offset},
                timeout=8,
            )
        except Exception:
            break
        if r.status_code != 200:
            break
        batch = r.json()
        if not isinstance(batch, list) or not batch:
            break
        all_files.extend(batch)
        if len(batch) < 100:
            break
        offset += 100
        time.sleep(0.1)
    return all_files


def extract_path(file_url: str) -> str | None:
    m = re.search(r"/storage/v1/object/(?:public|sign)/[^/]+/(.+)", file_url)
    return m.group(1) if m else None


def download(session: requests.Session, file_url: str, dest: str) -> bool:
    try:
        r = session.get(file_url, timeout=15, stream=True)
        if r.status_code != 200:
            return False
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "wb") as f:
            for chunk in r.iter_content(8192):
                f.write(chunk)
        return True
    except Exception:
        return False


def dump_urls(session, urls: list[str], bucket: str, out_dir: str, delay: float):
    ok = fail = skip = 0
    for file_url in urls:
        path = extract_path(file_url)
        if not path:
            skip += 1
            continue
        dest = os.path.join(out_dir, bucket, path)
        if os.path.exists(dest):
            skip += 1
            continue
        success = download(session, file_url, dest)
        print(f"    {'[ok]  ' if success else '[fail]'} {path}")
        ok += success
        fail += not success
        time.sleep(delay)
    return ok, fail, skip


def dump_bucket(session, url: str, key: str, bucket: str, out_dir: str, delay: float):
    print(f"\n  Bucket : {bucket}")
    print(f"  {'─' * 50}")

    print(f"  [1/2] DB pivot")
    db_urls     = fetch_urls_from_db(session, url, key)
    bucket_urls = {u for u in db_urls if f"/{bucket}/" in u}
    print(f"        {len(bucket_urls)} URLs found")
    if bucket_urls:
        ok, fail, skip = dump_urls(session, sorted(bucket_urls), bucket, out_dir, delay)
        print(f"        {ok} ok  {fail} fail  {skip} skip")

    print(f"  [2/2] Direct listing")
    files = list_files(session, url, bucket, key)
    if not files:
        print(f"        Blocked or empty")
    else:
        list_urls = [f"{url}/storage/v1/object/public/{bucket}/{f['name']}"
                     for f in files if f.get("name")]
        print(f"        {len(list_urls)} files found")
        ok, fail, skip = dump_urls(session, list_urls, bucket, out_dir, delay)
        print(f"        {ok} ok  {fail} fail  {skip} skip")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--env",    required=True)
    parser.add_argument("--bucket", default=None, help="Single bucket (default: read from enumerate output)")
    parser.add_argument("--delay",  type=float, default=0.15)
    args = parser.parse_args()

    env_path = args.env
    if not os.path.isabs(env_path) and not os.path.exists(env_path):
        env_path = os.path.join(SCRIPT_DIR, env_path)

    cfg     = load_env(env_path)
    project = cfg["PROJECT_NAME"]
    url     = cfg["SUPABASE_URL"]
    key     = cfg["SUPABASE_ANON_KEY"]
    date    = datetime.now().strftime("%Y%m%d")
    out_dir = output_path(project, f"storage_{date}")

    buckets = [args.bucket] if args.bucket else read_buckets(project)

    session = make_session()

    print(f"\n  Project : {project}")
    print(f"  Target  : {url}")
    print(f"  Buckets : {buckets}")
    print(f"  Output  : output/{project}/storage_{date}/")

    for bucket in buckets:
        dump_bucket(session, url, key, bucket, out_dir, args.delay)

    total = sum(len(fs) for _, _, fs in os.walk(out_dir))
    size  = sum(os.path.getsize(os.path.join(dp, f))
                for dp, _, fs in os.walk(out_dir) for f in fs)
    print(f"\n  Done: {total} files, {size / 1024:.1f} KB → output/{project}/storage_{date}/")


if __name__ == "__main__":
    main()
