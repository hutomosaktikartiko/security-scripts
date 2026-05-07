import os
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
ANON_KEY     = os.getenv("SUPABASE_ANON_KEY")
SO_FILE_PATH = os.getenv("SO_FILE_PATH")

if not SUPABASE_URL or not ANON_KEY:
    raise ValueError("SUPABASE_URL and SUPABASE_ANON_KEY must be set in .env")

HEADERS = {
    "apikey": ANON_KEY,
    "Authorization": f"Bearer {ANON_KEY}",
    "Content-Type": "application/json",
}
