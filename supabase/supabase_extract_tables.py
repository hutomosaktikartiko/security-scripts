import subprocess
import re
from config import SO_FILE_PATH

def extract_candidates():
    # Extract candidate strings from the SO file
    result = subprocess.run(
        ["strings", SO_FILE_PATH],
        capture_output=True, text=True
    )

    all_strings = result.stdout.splitlines()

    # Pattern: lowercase with underscore, 3-40 characters
    pattern = re.compile(r'^[a-z][a-z_]{2,39}$')

    # Usually table names
    keywords = [
        "user", "profile", "question", "answer", "segment",    
        "topic", "subject", "subscription", "payment", "order",
        "result", "score", "quiz", "exam", "tryout", "lesson",
        "chapter", "category", "tag", "review", "comment",     
        "notification", "setting", "config", "banner", "report",         
        "soal", "bank", "set", "session", "transaction", "invoice" 
    ]

    candidates = set()
    for s in all_strings:
        if pattern.match(s):
            for kw in keywords:
                if kw in s:
                    candidates.add(s)
                    break
    
    print(f"Total candidate table names: {len(candidates)}")
    print(f"\n=== CANDIDATE ===")
    for c in sorted(candidates):
        print(f"    {c}")
    
    # Save to file
    with open("candidates.txt", "w") as f:
        f.write("\n".join(sorted(candidates)))
    print("\nSaved to candidates.txt")

extract_candidates()