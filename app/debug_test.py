import urllib.request
import json
import os
from dotenv import load_dotenv
load_dotenv()

API_KEY = os.getenv("ANTHROPIC_API_KEY")
print(f"Key starts with: {API_KEY[:15] if API_KEY else 'NOT SET'}")

payload = json.dumps({
    "model": "claude-haiku-4-5",
    "max_tokens": 100,
    "messages": [{"role": "user", "content": "say hello"}]
}).encode()

req = urllib.request.Request(
    "https://api.anthropic.com/v1/messages",
    data=payload,
    headers={
        "Content-Type": "application/json",
        "x-api-key": API_KEY,
        "anthropic-version": "2023-06-01"
    },
    method="POST"
)

try:
    with urllib.request.urlopen(req) as response:
        data = response.read().decode()
        print("SUCCESS:", data[:200])
except urllib.error.HTTPError as e:
    print(f"HTTP Error {e.code}:", e.read().decode())
except Exception as e:
    print("Exception:", str(e))
