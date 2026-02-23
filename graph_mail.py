# ChatGPT/Claude used for troubleshooting, suggestions and generating
import os
import requests
import msal

GRAPH_SCOPE = ["https://graph.microsoft.com/.default"]
GRAPH_API = "https://graph.microsoft.com/v1.0"


def _get_access_token() -> str:
    tenant_id = os.environ["AZURE_TENANT_ID"]
    client_id = os.environ["AZURE_CLIENT_ID"]
    client_secret = os.environ["AZURE_CLIENT_SECRET"]

    app = msal.ConfidentialClientApplication(
        client_id=client_id,
        authority=f"https://login.microsoftonline.com/{tenant_id}",
        client_credential=client_secret,
    )

    token_result = app.acquire_token_for_client(scopes=GRAPH_SCOPE)
    if "access_token" not in token_result:
        raise RuntimeError(
            f"Failed to get token: {token_result.get('error')} - {token_result.get('error_description')}"
        )

    return token_result["access_token"]


def send_graph_email(to_email: str, subject: str, body: str) -> None:
    sender_upn = os.environ["GRAPH_SENDER_UPN"]
    token = _get_access_token()

    payload = {
        "message": {
            "subject": subject,
            "body": {
                "contentType": "HTML",
                "content": body,
            },
            "from": {
                "emailAddress": {
                    "address": sender_upn,
                    "name": "Inventory Alerts"
                }
            },
            "replyTo": [
                {
                    "emailAddress": {
                        "address": sender_upn,
                        "name": "Inventory Alerts"
                    }
                }
            ],
            "toRecipients": [
                {"emailAddress": {"address": to_email}}
            ],
        },
        "saveToSentItems": True,
    }

    resp = requests.post(
        f"{GRAPH_API}/users/{sender_upn}/sendMail",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json=payload,
        timeout=30,
    )

    # Graph sendMail success = 202 Accepted
    if resp.status_code != 202:
        raise RuntimeError(f"Graph sendMail failed: {resp.status_code} {resp.text}")
