# SMTP Relay Server to Microsoft Graph 📬

This project listens on port 25 and forwards incoming SMTP messages to Microsoft 365 Exchange using Microsoft Graph API. Messages can be plain text or HTML and are forwarded with appropriate formatting.

## 🚀 Setup

1. Install dependencies:
    ```bash
    pip install -r requirements.txt
    ```

2. Configure your Azure credentials and SMTP settings in `config.ini`:
    ```ini
    [graph]
    client_id = YOUR_CLIENT_ID
    client_secret = YOUR_CLIENT_SECRET
    tenant_id = YOUR_TENANT_ID
    sender_email = YOUR_SENDER@yourdomain.com

    [smtp]
    hostname = 0.0.0.0
    port = 25
    ```

3. Run the server:
    ```bash
    python smtp_graph_relay.py
    ```

## ⚙️ Features

- Listens for emails via SMTP on specified hostname/port
- Sends messages via Graph API with correct content type (Text or HTML)
- Secure config management via `config.ini`
- Basic logging for observability