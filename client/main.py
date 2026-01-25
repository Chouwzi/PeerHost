import argparse
import urllib.request
import urllib.error
import json
import sys
import os
from pathlib import Path

BASE_URL = "http://localhost:8000"
TOKEN_FILE = Path(".session_token")

def save_token(token):
    with open(TOKEN_FILE, "w") as f:
        f.write(token)

def load_token():
    if not TOKEN_FILE.exists():
        return None
    with open(TOKEN_FILE, "r") as f:
        return f.read().strip()

def make_request(method, endpoint, data=None, token=None):
    url = f"{BASE_URL}{endpoint}"
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    
    encoded_data = json.dumps(data).encode('utf-8') if data else None
    req = urllib.request.Request(url, data=encoded_data, method=method, headers=headers)
    
    try:
        with urllib.request.urlopen(req) as resp:
            if resp.status == 204:
                return None
            response_data = resp.read().decode('utf-8')
            return json.loads(response_data)
    except urllib.error.HTTPError as e:
        print(f"Error {e.code}: {e.read().decode('utf-8')}")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)

def cmd_claim(args):
    print(f"Claiming session...")
    payload = {
        "host_id": "cli-host-01"
    }
    resp = make_request("POST", "/world/session", payload)
    token = resp["token"]
    heartbeat = resp["heartbeat_interval"]
    lock_timeout = resp["lock_timeout"]
    save_token(token)
    print(f"Success! Token saved.")
    print(f"Token: {token[:10]}...")
    print(f"Heartbeat interval: {heartbeat}")
    print(f"Lock timeout: {lock_timeout}")

def cmd_stop(args):
    print(f"Stopping session...")
    token = load_token()
    if not token:
        print("No token found. Please claim session first.")
        return
    
    make_request("DELETE", "/world/session", token=token)
    if TOKEN_FILE.exists():
        TOKEN_FILE.unlink()
    print("Session stopped.")

def cmd_heartbeat(args):
    print(f"Sending heartbeat...")
    token = load_token()
    if not token:
        print("No token found. Please claim session first.")
        return

    make_request("POST", "/world/session/heartbeat", token=token)
    print("Heartbeat sent.")

def cmd_get(args):
    print(f"Getting session info...")
    data = make_request("GET", "/world/session")
    print(json.dumps(data, indent=2))

def main():
    parser = argparse.ArgumentParser(description="PeerHost CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)
    
    subparsers.add_parser("claim", help="Claim session").set_defaults(func=cmd_claim)
    subparsers.add_parser("stop", help="Stop session").set_defaults(func=cmd_stop)
    subparsers.add_parser("heartbeat", help="Send heartbeat").set_defaults(func=cmd_heartbeat)
    subparsers.add_parser("get", help="Get session info").set_defaults(func=cmd_get)
    
    args = parser.parse_args()
    if hasattr(args, 'func'):
        args.func(args)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
