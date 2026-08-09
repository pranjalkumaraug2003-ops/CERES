"""
google_auth.py — One-time OAuth consent flow for Gmail + Calendar.
Run once from project root:
    python -m server.utils.google_auth

This will open your browser, ask you to sign in to Google,
and save server/token.json. You won't need to do this again.
"""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))

from google_auth_oauthlib.flow import InstalledAppFlow
import json

SCOPES = [
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/gmail.send',
    'https://www.googleapis.com/auth/calendar',
]

CREDS_PATH = os.path.join(os.path.dirname(__file__), '..', 'credentials.json')
TOKEN_PATH = os.path.join(os.path.dirname(__file__), '..', 'token.json')

def main():
    if not os.path.exists(CREDS_PATH):
        print("❌ credentials.json not found!")
        print()
        print("Steps to get it:")
        print("  1. Go to https://console.cloud.google.com")
        print("  2. Create a new project (or select existing)")
        print("  3. Go to APIs & Services → Enable APIs")
        print("     → Enable Gmail API")
        print("     → Enable Google Calendar API")
        print("  4. Go to APIs & Services → Credentials")
        print("  5. Create OAuth 2.0 Client ID → Desktop Application")
        print("  6. Download JSON → save as server/credentials.json")
        print()
        print("Then run this script again.")
        return

    flow = InstalledAppFlow.from_client_secrets_file(CREDS_PATH, SCOPES)
    creds = flow.run_local_server(port=0)

    with open(TOKEN_PATH, 'w') as f:
        f.write(creds.to_json())

    print(f"✅ Authentication successful! Token saved to {TOKEN_PATH}")
    print("CERES can now access your Gmail and Google Calendar.")

if __name__ == '__main__':
    main()
