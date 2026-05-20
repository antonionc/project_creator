import base64
from project_creator.auth import get_credentials
from project_creator.gmail import build_gmail_service, _get_body

def main():
    creds = get_credentials()
    service = build_gmail_service(creds)
    
    msg_id = "19dcb29bc4ded777"
    msg = service.users().messages().get(userId="me", id=msg_id, format="full").execute()
    body = _get_body(msg)
    
    print("BODY LENGTH:", len(body))
    print("--- BODY START ---")
    print(body)
    print("--- BODY END ---")
    
    # Also print the raw parts structure
    import json
    print("--- PAYLOAD STRUCTURE ---")
    print(json.dumps(msg.get("payload", {}), indent=2))

if __name__ == "__main__":
    main()
