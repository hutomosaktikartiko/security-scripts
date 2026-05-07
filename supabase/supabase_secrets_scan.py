"""
Phase 7 — Secrets Hunting di APK
Scan binary APK / .so file untuk menemukan key, token, dan URL tersembunyi.
"""

import re
import subprocess
import base64
import json
from config import SO_FILE_PATH


# Patterns yang dicari
PATTERNS = {
    "JWT Token": re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
    "Google API Key": re.compile(r"AIza[0-9A-Za-z\-_]{35}"),
    "Stripe Live Key": re.compile(r"sk_live_[0-9a-zA-Z]{24,}"),
    "Stripe Test Key": re.compile(r"sk_test_[0-9a-zA-Z]{24,}"),
    "AWS Access Key": re.compile(r"AKIA[0-9A-Z]{16}"),
    "Supabase URL": re.compile(r"https://[a-z]{20}\.supabase\.co"),
    "Firebase URL": re.compile(r"https://[a-z0-9-]+\.firebaseio\.com"),
    "Private Key Header": re.compile(r"-----BEGIN (RSA |EC |)PRIVATE KEY-----"),
    "Generic Secret": re.compile(r"(?i)(secret|password|passwd|api_key|apikey)[\"'\s:=]+([A-Za-z0-9_\-/+]{16,})"),
}


def extract_strings(path: str) -> list[str]:
    """Jalankan strings pada binary file."""
    result = subprocess.run(
        ["strings", "-n", "8", path],
        capture_output=True, text=True, errors="ignore"
    )
    return result.stdout.splitlines()


def decode_jwt(token: str) -> dict | None:
    """Decode JWT payload tanpa verifikasi signature."""
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        # Tambah padding
        payload = parts[1] + "=="
        decoded = base64.urlsafe_b64decode(payload)
        return json.loads(decoded)
    except Exception:
        return None


def analyze_jwt(token: str, source_line: str) -> str:
    payload = decode_jwt(token)
    if not payload:
        return f"    Token  : {token[:60]}..."

    role    = payload.get("role", "unknown")
    ref     = payload.get("ref", "?")
    exp     = payload.get("exp", "?")

    severity = "[CRITICAL]" if role == "service_role" else "[INFO]"
    result   = f"    {severity} role={role}  project={ref}\n"
    result  += f"    Token  : {token[:80]}...\n"
    result  += f"    Payload: {json.dumps(payload, indent=6)}"

    if role == "service_role":
        result += "\n    [!!!] SERVICE ROLE KEY — Bypasses ALL Row Level Security!"
        result += "\n    [!!!] Attacker has full admin access to database."

    return result


def scan(strings: list[str]) -> dict[str, list]:
    findings: dict[str, list] = {}

    for line in strings:
        for name, pattern in PATTERNS.items():
            matches = pattern.findall(line)
            if matches:
                if name not in findings:
                    findings[name] = []
                # Simpan unique matches
                for m in matches:
                    val = m if isinstance(m, str) else m[1]
                    if val not in [f["value"] for f in findings[name]]:
                        findings[name].append({"value": val, "line": line.strip()})

    return findings


def main():
    print("=" * 60)
    print("  PHASE 7 — SECRETS HUNTING IN APK / BINARY")
    print(f"  Target: {SO_FILE_PATH}")
    print("=" * 60)

    print("\n  Extracting strings from binary...")
    strings = extract_strings(SO_FILE_PATH)
    print(f"  Extracted {len(strings):,} strings.\n")

    findings = scan(strings)

    if not findings:
        print("  [+] No sensitive patterns found.")
        print("=" * 60)
        return

    for category, items in findings.items():
        print(f"\n  [{category}] — {len(items)} found")
        print(f"  {'-' * 50}")

        for item in items:
            val  = item["value"]
            line = item["line"]

            if category == "JWT Token":
                print(analyze_jwt(val, line))
            elif category == "Supabase URL":
                print(f"    URL: {val}")
            elif category == "Generic Secret":
                print(f"    Context : {line[:100]}")
                print(f"    Value   : {val}")
            else:
                print(f"    {val}")

            print()

    print("=" * 60)
    print("  SUMMARY")
    print("=" * 60)

    critical = []
    for category, items in findings.items():
        for item in items:
            if category == "JWT Token":
                payload = decode_jwt(item["value"])
                if payload and payload.get("role") == "service_role":
                    critical.append(f"service_role key ditemukan!")
            elif category in ("Stripe Live Key", "AWS Access Key"):
                critical.append(f"{category} ditemukan!")

    if critical:
        print("\n  [!!!] CRITICAL FINDINGS:")
        for c in critical:
            print(f"    - {c}")
    else:
        print("\n  Tidak ada critical key ditemukan.")
        print("  JWT yang ada hanya anon key — sudah diketahui sebelumnya.")

    # Cek apakah ada Supabase URL lain (beda project)
    if "Supabase URL" in findings:
        urls = {item["value"] for item in findings["Supabase URL"]}
        if len(urls) > 1:
            print(f"\n  [!] Multiple Supabase projects found: {len(urls)}")
            for url in urls:
                print(f"    - {url}")
            print("  Tip: Test setiap project — staging biasanya lebih lemah.")

    print("=" * 60)


if __name__ == "__main__":
    main()
