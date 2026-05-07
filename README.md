# security-scripts

Recon & security testing scripts.

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

---

<details>
<summary><strong>supabase/</strong> — Supabase recon & access testing</summary>

### Config

Create a `.env` file per project inside the `supabase/` folder:

```bash
cp supabase/.env.example supabase/.env.yourproject
```

```env
PROJECT_NAME=yourproject
SUPABASE_URL=https://xxxx.supabase.co
SUPABASE_ANON_KEY=eyJ...
SO_FILE_PATH=./resources/yourproject/lib/x86_64/libapp.so  # optional, for APK extraction
```

### Flow

```
table_extract_candidates  ──►  table_enumerate  ──►  table_dump
    (APK binary)                     │                table_write_poc
                                     ▼
                             storage_enumerate  ──►  storage_dump

rpc_extract_candidates    ──►  rpc_enumerate    ──►  rpc_dump
  (binary + sources)
```

### Scripts

| Script | What it does | Input | Output |
| ------ | ------------ | ----- | ------ |
| `table_extract_candidates.py` | Extract table name candidates from APK binary | `SO_FILE_PATH` (binary), `input/table_keywords.txt`, `input/{project}/table_keywords.txt` _(optional, gitignored)_ | `output/{project}/table_candidates.txt` |
| `table_enumerate.py` | Probe candidates → find open tables + schema | `input/table_candidates.txt` (global wordlist), `output/{project}/table_candidates.txt` _(optional, from prev step)_ | `output/{project}/open_tables.txt`, `output/{project}/table_schemas.json` |
| `table_dump.py` | Dump all open tables to JSON | `output/{project}/open_tables.txt` | `output/{project}/table_dump_YYYYMMDD/{table}.json` |
| `table_write_poc.py` | Test INSERT / UPDATE / DELETE access per table | `output/{project}/open_tables.txt`, `output/{project}/table_schemas.json`, `output/{project}/table_dump_*/` _(for UPDATE fallback)_ | `output/{project}/write_poc_YYYYMMDD.txt` |
| `storage_enumerate.py` | Find accessible storage buckets | `input/storage_buckets.txt` (global wordlist), `input/{project}/storage_buckets.txt` _(optional, gitignored)_, `output/{project}/open_tables.txt` _(DB hint)_ | `output/{project}/buckets.txt` |
| `storage_dump.py` | Download files from discovered buckets | `output/{project}/buckets.txt` | `output/{project}/storage_YYYYMMDD/{bucket}/` |
| `rpc_extract_candidates.py` | Extract RPC function name candidates from APK binary and decompiled source | `SO_FILE_PATH` (binary), `SOURCES_PATH` (decompiled source dir) | `output/{project}/rpc_candidates.txt` |
| `rpc_enumerate.py` | Discover exposed RPC functions via OpenAPI spec + wordlist + candidates | `input/rpc_functions.txt`, `input/{project}/rpc_functions.txt` _(optional, gitignored)_, `output/{project}/rpc_candidates.txt` _(optional, from prev step)_ | `output/{project}/rpc_functions.json` |
| `rpc_dump.py` | Call discovered functions, capture output, flag SECURITY DEFINER bypass | `output/{project}/rpc_functions.json` | `output/{project}/rpc_dump_YYYYMMDD/{fn}.json` |
| `auth_enum.py` | Detect auth misconfigurations | — | `output/{project}/auth_enum_YYYYMMDD.txt` |

### Usage

All scripts follow the same pattern:

```bash
python3 supabase/<script>.py --env supabase/.env.yourproject
```

</details>

---

<details>
<summary><strong>secrets/</strong> — Secret scanning per app type</summary>

### Config

Reuses the same `.env` file from `supabase/` or create a dedicated one in `secrets/`:

```env
PROJECT_NAME=yourproject
SO_FILE_PATH=./resources/yourproject/lib/x86_64/libapp.so
SOURCES_PATH=./sources/yourproject
```

### Scripts

| Script | What it does | Input | Output |
| ------ | ------------ | ----- | ------ |
| `apk.py` | Scan APK binary (`.so`) for hardcoded secrets | `SO_FILE_PATH` (binary) | `secrets/output/{project}/apk_scan_YYYYMMDD.txt` |

### Usage

```bash
python3 secrets/<script>.py --env supabase/.env.yourproject
```

### Patterns detected

| Category            | Patterns                                                                |
| ------------------- | ----------------------------------------------------------------------- |
| Auth                | JWT, Private Key, Basic Auth URL, Auth0, Clerk                          |
| Cloud               | AWS, GCP, Azure, DigitalOcean, Heroku, Firebase, Supabase               |
| Payment (global)    | Stripe, PayPal, Braintree, Square                                       |
| Payment (Indonesia) | MidTrans, Xendit, Doku                                                  |
| Comms               | Slack, SendGrid, Twilio, Mailgun, Postmark, OneSignal, Pusher, Intercom |
| Mobile / analytics  | AdMob, GA, AppsFlyer, Branch, Mixpanel, Amplitude, Segment, RevenueCat  |
| Dev tools           | GitHub, GitLab, OpenAI, Anthropic, Sentry, Mapbox, Cloudinary, Algolia  |
| Database            | PostgreSQL, MySQL, MongoDB, Redis, AMQP, Cassandra, CouchDB             |

</details>
