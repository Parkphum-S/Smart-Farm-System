# Smart Farm System V.1 — Requirements

Status: Initial draft for review
Target: Raspberry Pi 4 SmartGateway and ESP32 devices

## 1. Mandatory Architecture

- MQTT is prohibited.
- ESP32 communicates with the Backend using HTTPS/REST.
- Dashboard live updates may use SSE or WebSocket.
- PostgreSQL is the primary database.
- Support offline operation and store-and-forward.
- Design for secure WAN deployment.

## 2. Core Features

- Multi-tenant farms, users, roles, and permissions.
- Farm, zone, device, and sensor management.
- Nine zone types; the exact list must be approved before implementation.
- Device authentication, credential rotation, and revocation.
- Telemetry ingestion, validation, deduplication, and heartbeat monitoring.
- Command lifecycle: creation, expiry, acknowledgement, result, and audit trail.
- Offline buffering and safe replay after reconnection.
- Secure OTA with signed firmware, integrity checks, and recovery planning.
- VPD calculations with documented units and formulas.
- Manual NPK and pH records with timestamps and operator attribution.
- CCTV integration with tenant access controls.
- Dashboard, reports, and data export.
- Audit logging and verified backup/restore.

## 3. Security and Isolation

- Enforce authentication and RBAC on the server.
- Verify tenant authorization on every protected operation.
- Authenticate devices separately from human users.
- Use parameterized database queries and validate inputs.
- Keep secrets out of source control and logs.
- Use least-privilege PostgreSQL roles; the application account must not be a superuser.
- Keep PostgreSQL bound to localhost unless a reviewed requirement needs otherwise.
- Use TLS 1.2 or newer and trusted certificates for production WAN access.
- Apply rate limits, replay protection, and command expiry.

## 4. Storage and Operations

- Keep PostgreSQL data on the Linux filesystem, not on the USB SSD.
- Reserve the exFAT USB SSD for Execution Log, Audit Log, and backups only.
- Preserve existing SSD data; do not format or repartition it.
- Validate SSD mount point, UUID, filesystem, and writability before writing.
- Use backup checksums and manifests; test restore procedures.
- Define log retention, backup schedule, RPO, and RTO before production.
- Monitor disk space, memory, service health, and offline queues.

## 5. Verification

- Test authorization and cross-tenant isolation.
- Test telemetry validation, duplicate events, retries, and clock skew.
- Test offline buffering, replay, command expiry, and device recovery.
- Test VPD calculations and manual agronomic records.
- Test backup integrity and restoration.
- Preserve Execution Log history and append new results without silently rewriting prior records.
- Run relevant tests before committing; push only after verifying branch, remote, and permissions.

## 6. Implementation Phases

1. Review requirements and approve all nine zone types.
2. Select Backend framework and define REST API contracts.
3. Design database schema, migrations, and tenant boundaries.
4. Implement identity, authorization, and device enrollment.
5. Implement telemetry, heartbeat, commands, and offline buffering.
6. Implement zones, VPD, and manual NPK/pH.
7. Implement dashboard updates, CCTV, and reports.
8. Implement OTA safeguards, backups, monitoring, and WAN hardening.
9. Complete acceptance tests and operational documentation.

## 7. Decisions Required

- Names and behavior of the nine zone types.
- Backend framework and dashboard technology.
- Device credential provisioning and rotation.
- Expected device count, telemetry rate, and retention.
- Command guarantees and actuator safety requirements.
- CCTV protocols and network isolation.
- Backup schedule, retention, RPO, and RTO.
- Trusted TLS certificates and WAN exposure model.
