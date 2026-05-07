import argparse
import base64
import json
import os
import re
import subprocess
from datetime import datetime
from dotenv import dotenv_values

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# ── Patterns ──────────────────────────────────────────────────────────────────

PATTERNS = {
    # ── Auth / identity ───────────────────────────────────────────
    "JWT":                 re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
    "Private Key":         re.compile(r"-----BEGIN (RSA |EC |OPENSSH |)PRIVATE KEY-----"),
    "Basic Auth URL":      re.compile(r"https?://[^:@\s\"']{3,}:[^@\s\"']{3,}@[^\s\"']{5,}"),
    "Auth0 Secret":        re.compile(r"(?i)auth0.{0,20}['\"]([A-Za-z0-9_\-]{32,})['\"]"),
    "Clerk Secret":        re.compile(r"sk_(live|test)_[A-Za-z0-9]{40,}"),

    # ── Cloud / infra ─────────────────────────────────────────────
    "AWS Access Key":      re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "AWS Secret Key":      re.compile(r"(?i)aws.{0,20}['\"]([0-9a-zA-Z/+]{40})['\"]"),
    "GCP API Key":         re.compile(r"\bAIza[0-9A-Za-z\-_]{35}\b"),
    "GCP Service Account": re.compile(r'"client_email"\s*:\s*"[^"]+\.iam\.gserviceaccount\.com"'),
    "Azure Conn String":   re.compile(r"DefaultEndpointsProtocol=https;AccountName=[^;]+;AccountKey=[A-Za-z0-9+/=]{80,}"),
    "Azure SAS Token":     re.compile(r"sv=20[0-9]{2}-[0-9]{2}-[0-9]{2}&s[seipr]=.*&sig=[A-Za-z0-9%+/]{40,}"),
    "DigitalOcean Token":  re.compile(r"dop_v1_[A-Za-z0-9]{64}"),
    "Heroku API Key":      re.compile(r"(?i)heroku.{0,20}['\"]([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})['\"]"),
    "Firebase URL":        re.compile(r"https://[a-z0-9-]+-default-rtdb\.firebaseio\.com"),
    "Firebase Legacy FCM": re.compile(r"AAAA[A-Za-z0-9_-]{7}:[A-Za-z0-9_-]{140}"),
    "Supabase URL":        re.compile(r"https://[a-z]{20}\.supabase\.co"),

    # ── Payment (global) ──────────────────────────────────────────
    "Stripe Live":         re.compile(r"sk_live_[0-9a-zA-Z]{24,}"),
    "Stripe Test":         re.compile(r"sk_test_[0-9a-zA-Z]{24,}"),
    "Stripe Pub Live":     re.compile(r"pk_live_[0-9a-zA-Z]{24,}"),
    "PayPal Secret":       re.compile(r"(?i)paypal.{0,20}['\"]([A-Za-z0-9_\-]{32,})['\"]"),
    "Braintree Token":     re.compile(r"(?i)braintree.{0,20}['\"]([A-Za-z0-9]{32,})['\"]"),
    "Square Token":        re.compile(r"sq0[a-z]{3}-[A-Za-z0-9_\-]{22,}"),

    # ── Payment (Indonesia) ───────────────────────────────────────
    "MidTrans Server":     re.compile(r"Mid-server-[A-Za-z0-9_\-]{24,}"),
    "MidTrans Client":     re.compile(r"Mid-client-[A-Za-z0-9_\-]{24,}"),
    "Xendit Key":          re.compile(r"xnd_(development|production)_[A-Za-z0-9_\-]{32,}"),
    "Doku Key":            re.compile(r"(?i)doku.{0,20}['\"]([A-Za-z0-9_\-]{32,})['\"]"),

    # ── Comms / SaaS ──────────────────────────────────────────────
    "Slack Token":         re.compile(r"xox[baprs]-[0-9]{10,}-[0-9A-Za-z\-]{20,}"),
    "Slack Webhook":       re.compile(r"https://hooks\.slack\.com/services/T[A-Za-z0-9]+/B[A-Za-z0-9]+/[A-Za-z0-9]+"),
    "SendGrid Key":        re.compile(r"SG\.[A-Za-z0-9_\-]{22,}\.[A-Za-z0-9_\-]{43,}"),
    "Twilio SID":          re.compile(r"\bAC[a-f0-9]{32}\b"),
    "Twilio Token":        re.compile(r"(?i)twilio.{0,20}['\"]([a-f0-9]{32})['\"]"),
    "Mailgun Key":         re.compile(r"key-[0-9a-zA-Z]{32}"),
    "Postmark Key":        re.compile(r"(?i)postmark.{0,20}['\"]([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})['\"]"),
    "OneSignal Key":       re.compile(r"(?i)onesignal.{0,30}['\"]([A-Za-z0-9_\-]{36,})['\"]"),
    "Pusher Key":          re.compile(r"(?i)pusher.{0,30}(app_key|app_secret)[\"'\s:=]+([A-Za-z0-9]{20,})"),
    "Intercom Key":        re.compile(r"(?i)intercom.{0,20}['\"]([A-Za-z0-9_\-]{32,})['\"]"),

    # ── Mobile / analytics ────────────────────────────────────────
    "AdMob App ID":        re.compile(r"ca-app-pub-[0-9]{16}/[0-9]{10}"),
    "GA Measurement ID":   re.compile(r"\bG-[A-Z0-9]{8,12}\b"),
    "AppsFlyer Key":       re.compile(r"(?i)appsflyer.{0,20}['\"]([A-Za-z0-9_\-]{32,})['\"]"),
    "Branch Key":          re.compile(r"key_(live|test)_[A-Za-z0-9]{32,}"),
    "Mixpanel Token":      re.compile(r"(?i)mixpanel.{0,20}['\"]([A-Za-z0-9]{32})['\"]"),
    "Amplitude Key":       re.compile(r"(?i)amplitude.{0,20}['\"]([A-Za-z0-9]{32})['\"]"),
    "Segment Write Key":   re.compile(r"(?i)segment.{0,20}['\"]([A-Za-z0-9]{32,})['\"]"),
    "RevenueCat Key":      re.compile(r"(?i)revenuecat.{0,20}['\"]([A-Za-z0-9_\-]{32,})['\"]"),

    # ── Dev tools ─────────────────────────────────────────────────
    "GitHub Token":        re.compile(r"gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{80,}"),
    "GitLab Token":        re.compile(r"glpat-[A-Za-z0-9\-_]{20}"),
    "OpenAI Key":          re.compile(r"sk-[A-Za-z0-9]{48,}"),
    "Anthropic Key":       re.compile(r"sk-ant-[A-Za-z0-9\-_]{90,}"),
    "Sentry DSN":          re.compile(r"https://[a-f0-9]{32}@o[0-9]+\.ingest\.sentry\.io/[0-9]+"),
    "Mapbox Token":        re.compile(r"pk\.eyJ1[A-Za-z0-9_\-\.]{50,}"),
    "Cloudinary URL":      re.compile(r"cloudinary://[0-9]+:[A-Za-z0-9_\-]+@[a-z0-9]+"),
    "Algolia App Key":     re.compile(r"(?i)algolia.{0,20}['\"]([A-Za-z0-9]{32})['\"]"),
    "Elasticsearch URL":   re.compile(r"https?://[A-Za-z0-9_\-]+:[A-Za-z0-9_\-]+@[^\s\"']+\.es\.io"),

    # ── Database ──────────────────────────────────────────────────
    "DB Connection":       re.compile(r"(postgres|postgresql|mysql|mongodb|redis|amqp|cassandra|couchdb)://[A-Za-z0-9_\-:.@/?=&]+"),

    # ── Generic ───────────────────────────────────────────────────
    "Generic Secret":      re.compile(
        r"(?i)(secret[_-]?key|api[_-]?key|auth[_-]?token|access[_-]?token|client[_-]?secret)"
        r"[\"'\s:=]+([A-Za-z0-9_\-/+]{16,})"
    ),
}

SEVERITY: dict[str, str] = {
    "JWT":                 "HIGH",
    "Private Key":         "CRITICAL",
    "Basic Auth URL":      "HIGH",
    "Auth0 Secret":        "HIGH",
    "Clerk Secret":        "HIGH",
    "AWS Access Key":      "CRITICAL",
    "AWS Secret Key":      "CRITICAL",
    "GCP API Key":         "MEDIUM",
    "GCP Service Account": "CRITICAL",
    "Azure Conn String":   "CRITICAL",
    "Azure SAS Token":     "HIGH",
    "DigitalOcean Token":  "HIGH",
    "Heroku API Key":      "HIGH",
    "Firebase URL":        "INFO",
    "Firebase Legacy FCM": "HIGH",
    "Supabase URL":        "INFO",
    "Stripe Live":         "CRITICAL",
    "Stripe Test":         "LOW",
    "Stripe Pub Live":     "LOW",
    "PayPal Secret":       "CRITICAL",
    "Braintree Token":     "CRITICAL",
    "Square Token":        "HIGH",
    "MidTrans Server":     "CRITICAL",
    "MidTrans Client":     "LOW",
    "Xendit Key":          "CRITICAL",
    "Doku Key":            "HIGH",
    "Slack Token":         "HIGH",
    "Slack Webhook":       "MEDIUM",
    "SendGrid Key":        "HIGH",
    "Twilio SID":          "MEDIUM",
    "Twilio Token":        "HIGH",
    "Mailgun Key":         "HIGH",
    "Postmark Key":        "HIGH",
    "OneSignal Key":       "MEDIUM",
    "Pusher Key":          "MEDIUM",
    "Intercom Key":        "HIGH",
    "AdMob App ID":        "INFO",
    "GA Measurement ID":   "INFO",
    "AppsFlyer Key":       "MEDIUM",
    "Branch Key":          "MEDIUM",
    "Mixpanel Token":      "MEDIUM",
    "Amplitude Key":       "MEDIUM",
    "Segment Write Key":   "MEDIUM",
    "RevenueCat Key":      "HIGH",
    "GitHub Token":        "HIGH",
    "GitLab Token":        "HIGH",
    "OpenAI Key":          "HIGH",
    "Anthropic Key":       "HIGH",
    "Sentry DSN":          "MEDIUM",
    "Mapbox Token":        "MEDIUM",
    "Cloudinary URL":      "HIGH",
    "Algolia App Key":     "MEDIUM",
    "Elasticsearch URL":   "HIGH",
    "DB Connection":       "CRITICAL",
    "Generic Secret":      "MEDIUM",
}

SEVERITY_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "INFO": 4}


# ── JWT helpers ───────────────────────────────────────────────────────────────

def decode_jwt(token: str) -> dict | None:
    try:
        payload = token.split(".")[1] + "=="
        return json.loads(base64.urlsafe_b64decode(payload))
    except Exception:
        return None


def analyze_jwt(token: str) -> tuple[str, str]:
    """Return (severity, detail_string)."""
    payload = decode_jwt(token)
    if not payload:
        return "LOW", f"  token : {token}"

    role = payload.get("role", "unknown")
    ref  = payload.get("ref", "?")

    if role == "service_role":
        sev  = "CRITICAL"
        note = "SERVICE ROLE — bypasses ALL Row Level Security"
    elif role == "anon":
        sev  = "INFO"
        note = "anon key — limited access, expected in client apps"
    else:
        sev  = "HIGH"
        note = f"unknown role: {role}"

    detail = (
        f"  role    : {role}\n"
        f"  project : {ref}\n"
        f"  token   : {token}\n"
        f"  note    : {note}"
    )
    return sev, detail


# ── Core ──────────────────────────────────────────────────────────────────────

def extract_strings(so_path: str) -> list[str]:
    result = subprocess.run(
        ["strings", "-n", "8", so_path],
        capture_output=True, text=True, errors="ignore",
    )
    return result.stdout.splitlines()


def scan(strings: list[str]) -> list[dict]:
    seen: set[str] = set()
    findings: list[dict] = []

    for line in strings:
        for name, pattern in PATTERNS.items():
            for match in pattern.finditer(line):
                val = match.group(1) if match.lastindex and match.lastindex >= 1 and name in (
                    "AWS Secret Key", "PayPal Secret", "Twilio Token",
                    "OneSignal Key", "Generic Secret",
                ) else match.group(0)

                key = f"{name}:{val}"
                if key in seen:
                    continue
                seen.add(key)

                if name == "JWT":
                    sev, detail = analyze_jwt(val)
                else:
                    sev    = SEVERITY.get(name, "MEDIUM")
                    detail = f"  value  : {val}\n  context: {line.strip()[:120]}"

                findings.append({
                    "category": name,
                    "severity": sev,
                    "value":    val,
                    "detail":   detail,
                })

    findings.sort(key=lambda x: (SEVERITY_ORDER.get(x["severity"], 9), x["category"]))
    return findings


# ── Output ────────────────────────────────────────────────────────────────────

def render(findings: list[dict], project: str, so_path: str) -> str:
    SEP  = "─" * 60
    SEP2 = "═" * 60

    by_sev: dict[str, int] = {}
    for f in findings:
        by_sev[f["severity"]] = by_sev.get(f["severity"], 0) + 1

    summary = "  " + "  ".join(
        f"{sev}: {by_sev[sev]}"
        for sev in ("CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO")
        if sev in by_sev
    ) if by_sev else "  no findings"

    blocks = [
        f"apk secret scan — {project}",
        f"target   : {so_path}",
        f"date     : {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"findings : {len(findings)}",
        SEP2,
    ]

    for f in findings:
        blocks.append(f"\n[{f['severity']}] {f['category']}")
        blocks.append(f['detail'])
        blocks.append(SEP)

    blocks.append(f"\nSUMMARY\n{summary}")

    return "\n".join(blocks)


def _hint(f: dict) -> str:
    if f["category"] == "JWT":
        payload = decode_jwt(f["value"])
        if payload:
            return f"role={payload.get('role','?')}  project={payload.get('ref','?')}"
        return f["value"][:40]
    if f["category"] in ("Supabase URL", "Firebase URL", "DB Connection", "Basic Auth URL",
                         "Slack Webhook", "Sentry DSN", "Cloudinary URL"):
        return f["value"]
    return f["value"][:60] if len(f["value"]) > 60 else f["value"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--env", required=True)
    args = parser.parse_args()

    env_path = args.env
    if not os.path.isabs(env_path) and not os.path.exists(env_path):
        env_path = os.path.join(SCRIPT_DIR, env_path)

    cfg     = dotenv_values(env_path)
    project = cfg.get("PROJECT_NAME", "unknown")
    so_path = cfg.get("SO_FILE_PATH", "")

    if not so_path or not os.path.exists(so_path):
        print(f"  SO_FILE_PATH not found: {so_path}")
        return

    out_dir  = os.path.join(SCRIPT_DIR, "output", project)
    out_file = os.path.join(out_dir, f"apk_scan_{datetime.now().strftime('%Y%m%d')}.txt")
    os.makedirs(out_dir, exist_ok=True)

    print(f"\n  Project : {project}")
    print(f"  Target  : {so_path}")
    print(f"  Scanning...\n")

    strings  = extract_strings(so_path)
    print(f"  Strings extracted : {len(strings):,}")

    findings = scan(strings)
    print(f"  Findings          : {len(findings)}\n")

    for f in findings:
        hint = _hint(f)
        marker = " !!!" if f["severity"] == "CRITICAL" else ""
        print(f"  [{f['severity']:<8}] {f['category']:<18} {hint}{marker}")

    content = render(findings, project, so_path)
    with open(out_file, "w") as fh:
        fh.write(content)

    print(f"\n  Saved : secrets/output/{project}/apk_scan_{datetime.now().strftime('%Y%m%d')}.txt")


if __name__ == "__main__":
    main()
