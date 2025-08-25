# smtprelay.py
import logging
from aiosmtpd.controller import Controller
from msal import ConfidentialClientApplication
import requests
import configparser
import time
from email import policy
from email.parser import BytesParser
import ipaddress
import base64

# --- Config loading ---
config = configparser.ConfigParser()
config.read("config.ini")

GRAPH_CLIENT_ID = config["graph"]["client_id"]
GRAPH_CLIENT_SECRET = config["graph"]["client_secret"]
GRAPH_TENANT_ID = config["graph"]["tenant_id"]
GRAPH_SENDER_EMAIL = config["graph"]["sender_email"]

SMTP_HOSTNAME = config["smtp"].get("hostname", "0.0.0.0")
SMTP_PORT = config["smtp"].getint("port", 25)

# Load and process allowed IPs and CIDRs
ALLOWED_IPS = set(ip.strip() for ip in config["security"].get("allowed_ips", "").split(",") if ip.strip())
ALLOWED_CIDR_STRINGS = [cidr.strip() for cidr in config["security"].get("allowed_cidrs", "").split(",") if cidr.strip()]
ALLOWED_NETWORKS = [ipaddress.ip_network(cidr, strict=False) for cidr in ALLOWED_CIDR_STRINGS]

# --- Logging setup ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("smtp-relay")

# --- Microsoft Graph email sending ---
def send_email_with_graph_api(to_address, subject, content, content_type, attachments=[]):
    logger.info("Sending email to Graph API...")
    app = ConfidentialClientApplication(
        GRAPH_CLIENT_ID,
        authority=f"https://login.microsoftonline.com/{GRAPH_TENANT_ID}",
        client_credential=GRAPH_CLIENT_SECRET,
    )

    token_response = app.acquire_token_for_client(scopes=["https://graph.microsoft.com/.default"])
    token = token_response.get("access_token")
    if not token:
        logger.error("Failed to acquire token: %s", token_response)
        return

    graph_payload = {
        "message": {
            "subject": subject,
            "body": {
                "contentType": content_type,
                "content": content,
            },
            "toRecipients": [
                {"emailAddress": {"address": to_address}},
            ],
            "attachments": [
                {
                    "@odata.type": "#microsoft.graph.fileAttachment",  # Specify the correct type
                    "name": att["name"],
                    "contentType": att["contentType"],
                    "contentBytes": att["contentBytes"]  # Already base64-encoded
                }
                for att in attachments
            ] if attachments else []
        },
        "saveToSentItems": "true"
    }

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    response = requests.post(
        f"https://graph.microsoft.com/v1.0/users/{GRAPH_SENDER_EMAIL}/sendMail",
        headers=headers,
        json=graph_payload,
    )

    if response.status_code == 202:
        logger.info("✅ Email sent successfully via Graph API.")
    else:
        logger.error("❌ Failed to send mail: %s - %s", response.status_code, response.text)

# --- Attachment extraction ---
def extract_attachments(parsed):
    attachments = []
    for part in parsed.iter_attachments():
        filename = part.get_filename()
        content_type = part.get_content_type()
        content = part.get_payload(decode=True)  # Decode the content to bytes
        if filename and content:
            attachments.append({
                "name": filename,
                "contentType": content_type,
                "contentBytes": base64.b64encode(content).decode("utf-8")  # Base64 encode the content
            })
    return attachments

# --- SMTP handler ---
class RelayHandler:
    async def handle_DATA(self, server, session, envelope):
        peer_ip = session.peer[0]
        logger.debug(f"🔎 Incoming connection from: {peer_ip}")

        try:
            ip_obj = ipaddress.ip_address(peer_ip)
        except ValueError:
            logger.warning(f"❌ Invalid IP address: {peer_ip}")
            return "550 Invalid IP address format"

        if peer_ip in ALLOWED_IPS:
            logger.debug(f"✅ Authorized IP (exact match): {peer_ip}")
        elif any(ip_obj in net for net in ALLOWED_NETWORKS):
            logger.debug(f"✅ Authorized IP (CIDR match): {peer_ip}")
        else:
            logger.warning(f"❌ Unauthorized IP: {peer_ip}")
            return "550 Access denied: IP not authorized"

        logger.info("📨 DATA received from %s", envelope.mail_from)

        raw_bytes = envelope.original_content
        parsed = BytesParser(policy=policy.default).parsebytes(raw_bytes)

        subject = parsed.get("Subject", "(No Subject)")
        to_addresses = envelope.rcpt_tos

        body_part = parsed.get_body(preferencelist=("html", "plain"))
        content_type = "HTML" if body_part and body_part.get_content_type() == "text/html" else "Text"
        content = body_part.get_content() if body_part else parsed.get_payload()

        attachments = extract_attachments(parsed)
        if attachments:
            logger.info("📎 Found %d attachment(s)", len(attachments))

        for recipient in to_addresses:
            logger.info("➡️  Relaying to: %s [%s]", recipient, content_type)
            send_email_with_graph_api(recipient, subject, content, content_type, attachments)

        return "250 OK: Message relayed"

# --- SMTP server entrypoint ---
def run_smtp_relay():
    controller = Controller(
        RelayHandler(),
        hostname=SMTP_HOSTNAME,
        port=SMTP_PORT
    )
    logger.info(f"🚀 SMTP Relay Server started on {SMTP_HOSTNAME}:{SMTP_PORT}...")
    controller.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("🛑 Server shutting down...")
        controller.stop()

if __name__ == "__main__":
    run_smtp_relay()
