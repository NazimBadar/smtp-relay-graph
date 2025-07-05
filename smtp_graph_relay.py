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
# logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger("smtp-relay")

# --- Microsoft Graph email sending ---
def send_email_with_graph_api(to_address, subject, content, content_type):
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

    payload = {
        "message": {
            "subject": subject,
            "body": {
                "contentType": content_type,
                "content": content,
            },
            "toRecipients": [
                {"emailAddress": {"address": to_address}},
            ],
        }
    }
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    response = requests.post(
        f"https://graph.microsoft.com/v1.0/users/{GRAPH_SENDER_EMAIL}/sendMail",
        headers=headers,
        json=payload,
    )

    if response.status_code == 202:
        logger.info("✅ Email sent successfully via Graph API.")
    else:
        logger.error("❌ Failed to send mail: %s - %s", response.status_code, response.text)


class RelayHandler:
    async def handle_DATA(self, server, session, envelope):
        # peer_ip = session.peer[0]
        # logger.debug(f"🔎 Incoming connection from: {peer_ip}")

        # if peer_ip not in ALLOWED_IPS:
        #     logger.warning(f"❌ Unauthorized IP: {peer_ip}")
        #     return "550 Access denied: Unauthorized IP address"

        peer_ip = session.peer[0]
        logger.debug(f"🔎 Incoming connection from: {peer_ip}")

        try:
            ip_obj = ipaddress.ip_address(peer_ip)
        except ValueError:
            logger.warning(f"❌ Invalid IP address: {peer_ip}")
            return "550 Invalid IP address format"

        # Check against exact IP matches
        if peer_ip in ALLOWED_IPS:
            logger.debug(f"✅ Authorized IP (exact match): {peer_ip}")
        # Check against CIDR network ranges
        elif any(ip_obj in net for net in ALLOWED_NETWORKS):
            logger.debug(f"✅ Authorized IP (CIDR match): {peer_ip}")
        else:
            logger.warning(f"❌ Unauthorized IP: {peer_ip}")
            return "550 Access denied: IP not authorized"

        # Log the received email details        
        logger.info("📨 DATA received from %s", envelope.mail_from)

        # Parse the raw message using modern email policy
        raw_bytes = envelope.original_content
        parsed = BytesParser(policy=policy.default).parsebytes(raw_bytes)

        subject = parsed.get("Subject", "(No Subject)")
        to_addresses = envelope.rcpt_tos

        body_part = parsed.get_body(preferencelist=("html", "plain"))
        content_type = "HTML" if body_part and body_part.get_content_type() == "text/html" else "Text"
        content = body_part.get_content() if body_part else parsed.get_payload()

        for recipient in to_addresses:
            logger.info("➡️  Relaying to: %s [%s]", recipient, content_type)
            send_email_with_graph_api(recipient, subject, content, content_type)

        return "250 OK: Message relayed"

# --- SMTP server entrypoint ---
def run_smtp_relay():
    controller = Controller(
        RelayHandler(),
        hostname=SMTP_HOSTNAME,
        port=SMTP_PORT
    )
    # controller = Controller(RelayHandler(), hostname=SMTP_HOSTNAME, port=SMTP_PORT)
    logger.info(f"🚀 SMTP Relay Server started on {SMTP_HOSTNAME}:{SMTP_PORT}...")
    controller.start()

    try:
        while True:
            time.sleep(1)  # Keeps the main thread alive
    except KeyboardInterrupt:
        logger.info("🛑 Server shutting down...")
        controller.stop()

if __name__ == "__main__":
    run_smtp_relay()
# This script sets up an SMTP relay server that listens for incoming emails
# and forwards them to Microsoft Graph API for sending. It uses the aiosmtpd library   
# for handling SMTP messages asynchronously and the msal library for Microsoft authentication.
# The configuration is loaded from a config.ini file, which includes the necessary
