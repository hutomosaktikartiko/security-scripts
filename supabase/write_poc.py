import requests
import uuid
from config import SUPABASE_URL, HEADERS

MARKER = "[SECURITY_TEST]"

def test_insert(table: str, payload: dict) -> tuple[bool, str | None]:
    """Try INSERT. Return (success, inserted_id)."""
    r = requests.post(
        f"{SUPABASE_URL}/rest/v1/{table}",
        headers={**HEADERS, "Prefer": "return=representation"},
        json=payload,
    )
    if r.status_code in (200, 201):
        inserted = r.json()
        row_id = inserted[0].get("id") if inserted else None
        return True, row_id
    return False, None

def test_update(table: str, row_id: str, payload: dict) -> bool:
    """Try UPDATE row by id."""
    r = requests.patch(
        f"{SUPABASE_URL}/rest/v1/{table}",
        headers={**HEADERS, "Prefer": "return=representation"},
        params={"id": f"eq.{row_id}"},
        json=payload,
    )
    return r.status_code in (200, 204)

def test_delete(table: str, row_id: str) -> bool:
    """Try DELETE row by id."""
    r = requests.delete(
        f"{SUPABASE_URL}/rest/v1/{table}",
        headers=HEADERS,
        params={"id": f"eq.{row_id}"},
    )
    return r.status_code in (200, 204)

def run_poc(table: str, insert_payload: dict, update_payload: dict):
    print(f"\n  Table: {table}")
    print(f"  {'-' * 40}")

    # Insert
    ok, row_id = test_insert(table, insert_payload)
    status = "VULNERABLE" if ok else "protected"
    print(f"    INSERT  : [{status}]  id={row_id}")

    if not ok:
        print(f"    UPDATE  : [skipped — insert failed]")
        print(f"    DELETE  : [skipped — insert failed]")
        return

    # Update
    ok_update = test_update(table, row_id, update_payload)
    status = "VULNERABLE" if ok_update else "protected"
    print(f"    UPDATE  : [{status}]")

    # Delete (cleanup)
    ok_delete = test_delete(table, row_id)
    status = "VULNERABLE" if ok_delete else "protected"
    print(f"    DELETE  : [{status}]")

    if ok_delete:
        print(f"    Cleanup : [OK] test row removed")
        return
    else:
        print(f"    Cleanup : [WARN] could not delete test row — remove manually")
        print(f"             id = {row_id}")

def main():
    print("=" * 60)
    print("WRITE ACCESS PoC")
    print(f"Marker : '{MARKER}' — automatically cleaned up after test")
    print("=" * 60)

    test_id = str(uuid.uuid4())

    tests = [
        (
            "segments",
            {
                "id"         : test_id,
                "name"       : f"{MARKER} test",
                "slug"       : f"security-test-{test_id[:8]}",
                "description": f"{MARKER} automated security test — safe to delete",
                "order_index": 9999,
                "is_active"  : False,
            },
            {"name": f"{MARKER} updated"},
        ),
        (
            "sub_segments",
            {
                "id"         : str(uuid.uuid4()),
                "segment_id" : test_id,         # FK ke test segment di atas (mungkin gagal FK)
                "name"       : f"{MARKER} test",
                "slug"       : f"security-test-sub-{test_id[:8]}",
                "order_index": 9999,
                "is_active"  : False,
            },
            {"name": f"{MARKER} updated"},
        ),
        (
            "topics",
            {
                "id"              : str(uuid.uuid4()),
                "sub_segment_id"  : test_id,
                "name"            : f"{MARKER} test",
                "slug"            : f"security-test-topic-{test_id[:8]}",
                "total_questions" : 0,
                "order_index"     : 9999,
                "is_active"       : False,
            },
            {"name": f"{MARKER} updated"},
        ),
        (
            "question_sets",
            {
                "id"            : str(uuid.uuid4()),
                "topic_id"      : test_id,
                "name"          : f"{MARKER} test set",
                "slug"          : f"security-test-set-{test_id[:8]}",
                "description"   : f"{MARKER} automated security test",
                "question_count": 0,
                "order_index"   : 9999,
                "is_active"     : False,
            },
            {"name": f"{MARKER} updated"},
        ),
        (
            "questions",
            {
                "id"            : str(uuid.uuid4()),
                "topic_id"      : test_id,
                "question_text" : f"{MARKER} This is a security test question — safe to delete",
                "option_a"      : "A",
                "option_b"      : "B",
                "option_c"      : "C",
                "option_d"      : "D",
                "correct_answer": "A",
                "difficulty"    : "easy",
                "is_active"     : False,
            },
            {"question_text": f"{MARKER} updated — safe to delete"},
        ),
    ]

    for table, insert_payload, update_payload in tests:
        run_poc(table, insert_payload, update_payload)

    print("=" * 60)

if __name__ == "__main__":
    main()