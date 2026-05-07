import argparse
import os
import time
import uuid
import requests
from datetime import datetime
from dotenv import dotenv_values
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

OAUTH_PROVIDERS = [
    "google", "apple", "github", "facebook", "twitter",
    "discord", "spotify", "gitlab", "bitbucket", "azure",
    "linkedin", "notion", "twitch", "zoom",
]
RATE_LIMIT_PROBES = 15
OTP_BRUTE_PROBES  = 10


# ── Bootstrap ─────────────────────────────────────────────────────────────────

def load_env(path: str) -> dict:
    cfg = dotenv_values(path)
    for k in ("PROJECT_NAME", "SUPABASE_URL", "SUPABASE_ANON_KEY"):
        if not cfg.get(k):
            raise ValueError(f"{k} missing in {path}")
    return cfg


def make_session() -> requests.Session:
    s = requests.Session()
    s.mount("https://", HTTPAdapter(max_retries=Retry(total=2, backoff_factor=0.5)))
    return s


def hdrs(key: str) -> dict:
    return {"apikey": key, "Authorization": f"Bearer {key}",
            "Content-Type": "application/json"}


def output_path(*parts) -> str:
    return os.path.join(SCRIPT_DIR, "output", *parts)


def fake_email() -> str:
    return f"sec-test-{uuid.uuid4().hex[:8]}@example.com"


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_providers(session: requests.Session, url: str, key: str) -> dict:
    """Detect enabled auth providers via /auth/v1/settings and OAuth probes."""
    enabled, disabled = [], []

    # Try settings endpoint first
    r = session.get(f"{url}/auth/v1/settings", headers=hdrs(key), timeout=8)
    if r.status_code == 200:
        data = r.json()
        external = data.get("external", {})
        for provider, val in external.items():
            (enabled if val else disabled).append(provider)
        return {
            "source":   "settings",
            "enabled":  enabled,
            "disabled": disabled,
            "email_pw": data.get("disable_signup") is False,
            "raw":      data,
        }

    # Fallback: probe each OAuth provider individually
    for provider in OAUTH_PROVIDERS:
        try:
            r = session.get(
                f"{url}/auth/v1/authorize",
                params={"provider": provider, "redirect_to": "https://example.com"},
                headers=hdrs(key),
                allow_redirects=False,
                timeout=8,
            )
            if r.status_code in (302, 301):
                enabled.append(provider)
            else:
                msg = ""
                try:
                    msg = r.json().get("error_description", "")
                except Exception:
                    pass
                if "not enabled" in msg.lower() or "unsupported" in msg.lower():
                    disabled.append(provider)
        except Exception:
            pass
        time.sleep(0.1)

    return {"source": "probe", "enabled": enabled, "disabled": disabled}


def test_signup(session: requests.Session, url: str, key: str) -> dict:
    """Check if public signup is open."""
    email = fake_email()
    r = session.post(
        f"{url}/auth/v1/signup",
        headers=hdrs(key),
        json={"email": email, "password": "TestPassword123!"},
        timeout=8,
    )
    if r.status_code in (200, 201):
        return {"open": True, "status": r.status_code, "email": email}
    msg = ""
    try:
        msg = r.json().get("message", r.json().get("error_description", ""))
    except Exception:
        pass
    return {"open": False, "status": r.status_code, "message": msg}


def test_email_enum(session: requests.Session, url: str, key: str,
                    known_email: str | None) -> dict:
    """Check if /recover and /otp leak whether an email is registered."""
    unknown = fake_email()
    results = {}

    for endpoint in ("recover", "otp"):
        path    = f"{url}/auth/v1/{endpoint}"
        payload = {"email": unknown} if endpoint == "recover" else {"email": unknown, "create_user": False}

        r_unknown = session.post(path, headers=hdrs(key), json=payload, timeout=8)
        time.sleep(0.3)

        if known_email:
            kp = {"email": known_email} if endpoint == "recover" else {"email": known_email, "create_user": False}
            r_known = session.post(path, headers=hdrs(key), json=kp, timeout=8)
        else:
            r_known = None

        vulnerable = False
        detail     = ""
        if r_known:
            if r_unknown.status_code != r_known.status_code:
                vulnerable = True
                detail = f"status differs: registered={r_known.status_code} unknown={r_unknown.status_code}"
            else:
                try:
                    msg_k = r_known.json().get("message", "")
                    msg_u = r_unknown.json().get("message", "")
                    if msg_k != msg_u:
                        vulnerable = True
                        detail = f"message differs: registered='{msg_k}' unknown='{msg_u}'"
                    else:
                        detail = f"same response ({r_unknown.status_code}) — protected"
                except Exception:
                    detail = "could not parse response"
        else:
            detail = f"no known email to compare — status={r_unknown.status_code}"

        results[endpoint] = {
            "vulnerable": vulnerable,
            "detail":     detail,
            "status":     r_unknown.status_code,
        }
        time.sleep(0.3)

    return results


def test_phone_enum(session: requests.Session, url: str, key: str) -> dict:
    """Check if /otp with phone leaks whether a number is registered."""
    unknown_phone = "+10000000001"
    known_phone   = "+10000000002"  # placeholder; compare status codes only

    results = {}
    for phone in (unknown_phone, known_phone):
        payload = {"phone": phone, "create_user": False}
        try:
            r = session.post(f"{url}/auth/v1/otp", headers=hdrs(key),
                             json=payload, timeout=8)
            results[phone] = {"status": r.status_code, "body": r.text[:200]}
        except Exception as e:
            results[phone] = {"status": 0, "body": str(e)}
        time.sleep(0.3)

    s1 = results[unknown_phone]["status"]
    s2 = results[known_phone]["status"]
    if s1 == 422 or s1 == 400:
        detail    = "phone OTP not enabled or disabled"
        enabled   = False
        vulnerable = False
    elif s1 != s2:
        detail    = f"status differs: phone1={s1} phone2={s2}"
        enabled   = True
        vulnerable = True
    else:
        detail    = f"same response ({s1}) — protected"
        enabled   = s1 not in (422, 400)
        vulnerable = False

    return {"enabled": enabled, "vulnerable": vulnerable, "detail": detail,
            "statuses": {unknown_phone: s1, known_phone: s2}}


def test_password_policy(session: requests.Session, url: str, key: str) -> dict:
    """Try weak passwords during signup to detect missing password policy."""
    weak_passwords = [
        ("1 char",     "a"),
        ("6 digits",   "123456"),
        ("common",     "password"),
        ("no special", "Password1"),
    ]
    results = {}
    for label, pw in weak_passwords:
        email = fake_email()
        r = session.post(f"{url}/auth/v1/signup", headers=hdrs(key),
                         json={"email": email, "password": pw}, timeout=8)
        accepted = r.status_code in (200, 201)
        msg = ""
        try:
            msg = r.json().get("message", r.json().get("error_description", ""))
        except Exception:
            pass
        results[label] = {"accepted": accepted, "status": r.status_code, "message": msg}
        time.sleep(0.2)

    weak_accepted = [l for l, v in results.items() if v["accepted"]]
    return {
        "vulnerable":     bool(weak_accepted),
        "weak_accepted":  weak_accepted,
        "detail":         f"accepted weak passwords: {weak_accepted}" if weak_accepted else "all weak passwords rejected",
        "results":        results,
    }


def test_admin_api(session: requests.Session, url: str, key: str) -> dict:
    """Check if /auth/v1/admin/users is accessible with the anon key."""
    r = session.get(f"{url}/auth/v1/admin/users", headers=hdrs(key), timeout=8)
    exposed = r.status_code == 200
    count   = None
    if exposed:
        try:
            data  = r.json()
            users = data.get("users", data) if isinstance(data, dict) else data
            count = len(users) if isinstance(users, list) else "unknown"
        except Exception:
            pass
    return {
        "exposed": exposed,
        "status":  r.status_code,
        "count":   count,
        "detail":  f"EXPOSED — {count} user(s) returned" if exposed else f"protected ({r.status_code})",
    }


def test_otp_brute(session: requests.Session, url: str, key: str,
                   signup_email: str | None) -> dict:
    """Send repeated /verify attempts to check if OTP brute force is rate-limited."""
    if not signup_email:
        return {"skipped": True, "detail": "no registered email (signup closed)"}

    statuses = []
    for i in range(OTP_BRUTE_PROBES):
        token = str(100000 + i).zfill(6)
        try:
            r = session.post(
                f"{url}/auth/v1/verify",
                headers=hdrs(key),
                json={"email": signup_email, "token": token, "type": "signup"},
                timeout=5,
            )
            statuses.append(r.status_code)
        except Exception:
            statuses.append(0)

    limited = 429 in statuses
    return {
        "limited":  limited,
        "statuses": statuses,
        "detail":   f"rate limited after {statuses.index(429)+1} attempt(s)"
                    if limited else f"no rate limit in {OTP_BRUTE_PROBES} attempts",
    }


def test_rate_limit(session: requests.Session, url: str, key: str) -> dict:
    """Send repeated requests to check if rate limiting is in place."""
    endpoints = {
        "/auth/v1/token?grant_type=password": {"email": fake_email(), "password": "wrong"},
        "/auth/v1/recover":                   {"email": fake_email()},
    }
    results = {}
    for path, payload in endpoints.items():
        statuses = []
        for _ in range(RATE_LIMIT_PROBES):
            try:
                r = session.post(f"{url}{path}", headers=hdrs(key), json=payload, timeout=5)
                statuses.append(r.status_code)
            except Exception:
                statuses.append(0)
        limited = 429 in statuses
        results[path] = {
            "limited":  limited,
            "statuses": statuses,
            "detail":   f"blocked after {statuses.index(429)+1} req" if limited else f"no 429 in {RATE_LIMIT_PROBES} requests",
        }
        time.sleep(0.5)
    return results


# ── Render ────────────────────────────────────────────────────────────────────

def render(results: dict, project: str, url: str) -> str:
    SEP  = "─" * 60
    SEP2 = "═" * 60

    lines = [
        f"auth enum — {project}",
        f"target  : {url}",
        f"date    : {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        SEP2,
    ]

    # Providers
    prov = results["providers"]
    lines += [f"\n[PROVIDERS]  (source: {prov['source']})"]
    if prov["enabled"]:
        lines.append(f"  enabled  : {', '.join(prov['enabled'])}")
    if prov.get("disabled"):
        lines.append(f"  disabled : {', '.join(prov['disabled'])}")
    lines.append(SEP)

    # Signup
    su = results["signup"]
    label = "VULNERABLE — open signup" if su["open"] else f"protected ({su.get('message', su['status'])})"
    lines += [f"\n[SIGNUP]\n  {label}", SEP]

    # Email enumeration
    lines.append(f"\n[EMAIL ENUMERATION]")
    for ep, res in results["email_enum"].items():
        flag  = "VULNERABLE" if res["vulnerable"] else "protected"
        lines.append(f"  /{ep:<10} {flag} — {res['detail']}")
    lines.append(SEP)

    # Rate limiting
    lines.append(f"\n[RATE LIMITING]")
    for path, res in results["rate_limit"].items():
        flag = "rate limited" if res["limited"] else "NO RATE LIMIT"
        lines.append(f"  {path}")
        lines.append(f"    {flag} — {res['detail']}")
    lines.append(SEP)

    # Phone enumeration
    ph = results["phone_enum"]
    lines.append(f"\n[PHONE ENUMERATION]")
    if ph.get("enabled"):
        flag = "VULNERABLE" if ph["vulnerable"] else "protected"
        lines.append(f"  {flag} — {ph['detail']}")
    else:
        lines.append(f"  phone OTP not enabled — {ph['detail']}")
    lines.append(SEP)

    # Password policy
    pp = results["password_policy"]
    lines.append(f"\n[PASSWORD POLICY]")
    if pp.get("vulnerable"):
        lines.append(f"  VULNERABLE — {pp['detail']}")
    else:
        lines.append(f"  enforced — {pp['detail']}")
    for label, v in pp.get("results", {}).items():
        status = "accepted" if v["accepted"] else "rejected"
        lines.append(f"    {label:<12} {status} ({v['status']}){' — ' + v['message'] if v['message'] else ''}")
    lines.append(SEP)

    # Admin API
    adm = results["admin_api"]
    lines.append(f"\n[ADMIN API EXPOSURE]")
    lines.append(f"  {adm['detail']}")
    lines.append(SEP)

    # OTP brute force
    otp = results["otp_brute"]
    lines.append(f"\n[OTP BRUTE FORCE]")
    if otp.get("skipped"):
        lines.append(f"  skipped — {otp['detail']}")
    else:
        flag = "rate limited" if otp["limited"] else "NO RATE LIMIT"
        lines.append(f"  {flag} — {otp['detail']}")
    lines.append(SEP)

    # Summary
    issues = []
    if results["signup"]["open"]:
        issues.append("CRITICAL : open signup")
    if results["admin_api"]["exposed"]:
        issues.append(f"CRITICAL : admin API exposed — {results['admin_api']['count']} user(s)")
    for ep, res in results["email_enum"].items():
        if res["vulnerable"]:
            issues.append(f"HIGH     : email enumeration via /{ep}")
    if results["phone_enum"].get("enabled") and results["phone_enum"]["vulnerable"]:
        issues.append("HIGH     : phone enumeration via /otp")
    if results["password_policy"].get("vulnerable"):
        issues.append(f"HIGH     : weak password accepted — {results['password_policy']['detail']}")
    if not results["otp_brute"].get("skipped") and not results["otp_brute"]["limited"]:
        issues.append("MEDIUM   : OTP brute force not rate-limited")
    for path, res in results["rate_limit"].items():
        if not res["limited"]:
            issues.append(f"MEDIUM   : no rate limit on {path.split('?')[0]}")

    lines += [f"\n{SEP2}", "SUMMARY"]
    if issues:
        lines += [f"  {i}" for i in issues]
    else:
        lines.append("  no critical issues found")

    return "\n".join(lines)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--env", required=True)
    args = parser.parse_args()

    env_path = args.env
    if not os.path.isabs(env_path) and not os.path.exists(env_path):
        env_path = os.path.join(SCRIPT_DIR, env_path)

    cfg     = load_env(env_path)
    project = cfg["PROJECT_NAME"]
    url     = cfg["SUPABASE_URL"]
    key     = cfg["SUPABASE_ANON_KEY"]

    out_file = output_path(project, f"auth_enum_{datetime.now().strftime('%Y%m%d')}.txt")
    os.makedirs(os.path.dirname(out_file), exist_ok=True)

    session = make_session()

    print(f"\n  Project : {project}")
    print(f"  Target  : {url}\n")

    print(f"  [1/8] Providers...", end=" ", flush=True)
    providers = test_providers(session, url, key)
    print(f"enabled: {providers['enabled'] or 'none detected'}")

    print(f"  [2/8] Signup...", end=" ", flush=True)
    signup = test_signup(session, url, key)
    print(f"{'OPEN' if signup['open'] else 'closed'}")

    known_email = signup.get("email") if signup["open"] else None

    print(f"  [3/8] Email enumeration...", end=" ", flush=True)
    email_enum = test_email_enum(session, url, key, known_email)
    vuln_count = sum(1 for v in email_enum.values() if v["vulnerable"])
    print(f"{vuln_count} vulnerable endpoint(s)")

    print(f"  [4/8] Rate limiting ({RATE_LIMIT_PROBES} req each)...", end=" ", flush=True)
    rate_limit = test_rate_limit(session, url, key)
    unprotected = sum(1 for v in rate_limit.values() if not v["limited"])
    print(f"{unprotected} unprotected endpoint(s)")

    print(f"  [5/8] Phone enumeration...", end=" ", flush=True)
    phone_enum = test_phone_enum(session, url, key)
    print(f"{'enabled, ' if phone_enum['enabled'] else 'not enabled — '}{'VULNERABLE' if phone_enum['vulnerable'] else phone_enum['detail']}")

    print(f"  [6/8] Password policy...", end=" ", flush=True)
    password_policy = test_password_policy(session, url, key)
    print(f"{'VULNERABLE' if password_policy['vulnerable'] else 'enforced'}")

    print(f"  [7/8] Admin API exposure...", end=" ", flush=True)
    admin_api = test_admin_api(session, url, key)
    print(f"{'EXPOSED' if admin_api['exposed'] else 'protected'} ({admin_api['status']})")

    print(f"  [8/8] OTP brute force ({OTP_BRUTE_PROBES} attempts)...", end=" ", flush=True)
    otp_brute = test_otp_brute(session, url, key, known_email)
    if otp_brute.get("skipped"):
        print("skipped")
    else:
        print(f"{'rate limited' if otp_brute['limited'] else 'NO RATE LIMIT'}")

    results = {
        "providers":       providers,
        "signup":          signup,
        "email_enum":      email_enum,
        "rate_limit":      rate_limit,
        "phone_enum":      phone_enum,
        "password_policy": password_policy,
        "admin_api":       admin_api,
        "otp_brute":       otp_brute,
    }

    # Print summary to CLI
    print(f"\n  {'─' * 45}")
    if signup["open"]:
        print(f"  CRITICAL : open signup")
    if admin_api["exposed"]:
        print(f"  CRITICAL : admin API exposed — {admin_api['count']} user(s)")
    for ep, res in email_enum.items():
        if res["vulnerable"]:
            print(f"  HIGH     : email enum via /{ep}")
    if phone_enum.get("enabled") and phone_enum["vulnerable"]:
        print(f"  HIGH     : phone enumeration via /otp")
    if password_policy.get("vulnerable"):
        print(f"  HIGH     : weak password accepted — {password_policy['detail']}")
    if not otp_brute.get("skipped") and not otp_brute["limited"]:
        print(f"  MEDIUM   : OTP brute force not rate-limited")
    for path, res in rate_limit.items():
        if not res["limited"]:
            print(f"  MEDIUM   : no rate limit — {path.split('?')[0]}")

    content = render(results, project, url)
    with open(out_file, "w") as f:
        f.write(content)

    print(f"\n  Saved : output/{project}/auth_enum_{datetime.now().strftime('%Y%m%d')}.txt")


if __name__ == "__main__":
    main()
