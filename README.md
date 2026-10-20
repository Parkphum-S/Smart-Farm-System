# Smart Farm System V.1

Production-oriented smart farm platform for Raspberry Pi 4 SmartGateway,
ESP32 devices, and a web dashboard.

## Non-negotiable architecture rules

- MQTT is prohibited.
- ESP32 communicates with the Backend through HTTPS/REST.
- Dashboard live updates may use Server-Sent Events (SSE) or WebSocket.
- PostgreSQL is the primary database.
- The system must support offline operation and store-and-forward.
- Tenant isolation, authentication, authorization, and auditability are mandatory.
- SmartGateway data services must remain separate from the USB SSD used for logs,
  audit records, and backups.

## Project status

Initial requirements and architecture planning. No production application
code or application database has been created yet.

## Requirements

See [docs/REQUIREMENTS.md](docs/REQUIREMENTS.md).
