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
```

### Scripts

| Script                        | What it does                                               |
| ----------------------------- | ---------------------------------------------------------- |
| `table_extract_candidates.py` | Extract table name candidates from APK binary              |
| `table_enumerate.py`          | Probe candidates → find open tables + schema               |
| `table_dump.py`               | Dump all open tables to JSON                               |
| `table_write_poc.py`          | Test INSERT / UPDATE / DELETE access per table             |
| `storage_enumerate.py`        | Find accessible storage buckets (wordlist + APK + DB hint) |
| `storage_dump.py`             | Download files from discovered buckets                     |

### Usage

```bash
# 1. Extract table candidates from APK (optional)
python3 supabase/table_extract_candidates.py --env supabase/.env.yourproject

# 2. Enumerate open tables
python3 supabase/table_enumerate.py --env supabase/.env.yourproject

# 3. Dump table data
python3 supabase/table_dump.py --env supabase/.env.yourproject

# 4. Test write access
python3 supabase/table_write_poc.py --env supabase/.env.yourproject

# 5. Find storage buckets
python3 supabase/storage_enumerate.py --env supabase/.env.yourproject

# 6. Download storage files
python3 supabase/storage_dump.py --env supabase/.env.yourproject
```

### Input files

| File                                  | Description                                  |
| ------------------------------------- | -------------------------------------------- |
| `input/table_candidates.txt`          | Global table name wordlist                   |
| `input/table_keywords.txt`            | Keywords for filtering APK strings           |
| `input/storage_buckets.txt`           | Global bucket name wordlist                  |
| `input/{project}/table_keywords.txt`  | Project-specific keywords _(gitignored)_     |
| `input/{project}/storage_buckets.txt` | Project-specific bucket names _(gitignored)_ |

### Output

All results saved to `supabase/output/{project}/` _(gitignored)_:

```
output/yourproject/
├── table_candidates.txt     # from table_extract_candidates
├── open_tables.txt          # from table_enumerate
├── table_schemas.json       # from table_enumerate
├── table_dump_YYYYMMDD/     # from table_dump
│   └── {table}.json
├── write_poc_YYYYMMDD.txt   # from table_write_poc
├── buckets.txt              # from storage_enumerate
└── storage_YYYYMMDD/        # from storage_dump
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
```

### Scripts

| Script   | What it does                                  |
| -------- | --------------------------------------------- |
| `apk.py` | Scan APK binary (`.so`) for hardcoded secrets |

### Usage

```bash
python3 secrets/apk.py --env supabase/.env.yourproject
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

### Output

Results saved to `secrets/output/{project}/` _(gitignored)_:

```
secrets/output/yourproject/
└── apk_scan_YYYYMMDD.txt
```

</details>
