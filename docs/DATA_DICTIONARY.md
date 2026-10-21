# Smart Farm System V.1 — Data Dictionary

Status: Draft 0.1 — for review; not approved for migration
Target: Raspberry Pi 4 SmartGateway; PostgreSQL 17
Capacity baseline: 100 devices; telemetry interval 30 seconds

## 1. Design constraints

- MQTT is prohibited.
- ESP32 devices communicate with the backend using HTTPS/REST.
- PostgreSQL remains on the Linux root filesystem, not the USB SSD.
- Use UTC timestamps with PostgreSQL `timestamptz`.
- Use UUID primary keys for application entities.
- Enforce tenant isolation in backend authorization and database relationships.
- Store device credentials separately from human-user accounts.
- Make telemetry ingestion idempotent to handle retries and replay.
- Keep schema changes in reviewed migration files; never create tables at runtime.
- Do not enable automatic data deletion or partition cleanup until retention is approved.

## 2. Capacity baseline

- Target concurrent devices: 100.
- Nominal telemetry interval: 30 seconds per device.
- Estimated event rate: approximately 3.33 events/second.
- Estimated volume: 288,000 telemetry events/day if each device sends one event per interval.
- This estimate counts events, not individual sensor readings.

## 3. Pending decisions

- Approve the nine zone types and their behavior.
- Define telemetry event and sensor-reading payloads.
- Decide retention, offline replay window, backup schedule, RPO, and RTO.
- Confirm device credential provisioning and rotation.
- Review the proposed schema before writing migrations.

## 4. Proposed table inventory

These are proposed logical tables, not approved database migrations.

### 4.1 Tenancy and farm structure

- `tenants` — tenant or organization boundary.
- `users` — human user identities.
- `tenant_memberships` — user membership, role, and tenant-level access.
- `farms` — farms owned by a tenant.
- `zone_types` — approved definitions for zone types; the nine types remain pending.
- `zones` — farm areas linked to a zone type.

### 4.2 Devices and connectivity

- `devices` — enrolled device identity, ownership, and lifecycle status.
- `device_credentials` — credential metadata, rotation, expiry, and revocation; never store plaintext secrets.
- `sensors` — sensor identity, type, units, and association with a device or zone.
- `device_connections` — connectivity and connection-state history.

### 4.3 Telemetry and health

- `telemetry_events` — received device events, event identifiers, and ingestion timestamps.
- `sensor_readings` — validated individual measurements associated with telemetry events.
- `device_heartbeats` — device liveness and reported health.

### 4.4 Commands and firmware

- `commands` — requested device actions, expiry, and current lifecycle state.
- `command_events` — append-only command acknowledgement, result, and lifecycle history.
- `firmware_releases` — firmware version metadata and signature information.
- `ota_jobs` — device-targeted OTA rollout status and recovery information.

### 4.5 Agronomy and integrations

- `manual_measurements` — operator-entered NPK, pH, and related measurements.
- `vpd_calculations` — calculated VPD values with input references, units, and formula version.
- `cctv_sources` — CCTV integration metadata and tenant access boundaries.

### 4.6 Operations and audit

- `audit_logs` — security-sensitive user, device, and administrative actions.
- `backup_manifests` — backup metadata, checksums, and verification results.

## 5. Inventory review notes

- Table names and boundaries are proposals and may change during schema review.
- Tenant ownership and authorization must be enforced consistently across related records.
- Telemetry event deduplication keys and offline replay behavior require an explicit contract.
- Retention, partitioning, indexes, and archival rules remain undecided.
- No tables, roles, migrations, or database records have been created by this document.

## 6. Proposed columns: tenancy and farm structure

The following columns are preliminary design proposals, not database migrations.

### 6.1 `tenants`

- `id` — UUID, primary key.
- `name` — text, required.
- `status` — text, required; allowed values must be defined before implementation.
- `created_at` — timestamptz, required.
- `updated_at` — timestamptz, required.

### 6.2 `users`

- `id` — UUID, primary key.
- `email` — text, required; normalization and uniqueness policy must be decided.
- `display_name` — text, required.
- `status` — text, required; allowed values must be defined before implementation.
- `created_at` — timestamptz, required.
- `updated_at` — timestamptz, required.

### 6.3 `tenant_memberships`

- `tenant_id` — UUID, required; foreign key to `tenants.id`.
- `user_id` — UUID, required; foreign key to `users.id`.
- `role` — text, required; role vocabulary must be approved.
- `status` — text, required.
- `created_at` — timestamptz, required.
- Primary key proposal: (`tenant_id`, `user_id`).
- Authorization must verify membership and role for every tenant-scoped operation.

### 6.4 `farms`

- `id` — UUID, primary key.
- `tenant_id` — UUID, required; identifies the owning tenant.
- `name` — text, required.
- `location` — optional structured location; exact fields remain undecided.
- `timezone` — text, required; use a valid IANA timezone identifier.
- `created_at` — timestamptz, required.
- `updated_at` — timestamptz, required.
- Add a unique constraint on (`tenant_id`, `id`) to support tenant-scoped foreign keys.

### 6.5 `zone_types`

- `id` — UUID, primary key.
- `code` — text, required and unique.
- `name` — text, required.
- `description` — text, optional.
- `is_active` — boolean, required.
- The exact nine zone types and their behavior require approval before implementation.

### 6.6 `zones`

- `id` — UUID, primary key.
- `tenant_id` — UUID, required.
- `farm_id` — UUID, required.
- `zone_type_id` — UUID, required; foreign key to `zone_types.id`.
- `name` — text, required.
- `status` — text, required; allowed values remain to be defined.
- `created_at` — timestamptz, required.
- `updated_at` — timestamptz, required.
- Use a composite foreign key (`tenant_id`, `farm_id`) referencing `farms` (`tenant_id`, `id`) to prevent cross-tenant farm references.

### 6.7 Design safeguards

- UUID identifiers do not replace authorization checks.
- Every tenant-scoped query must derive tenant access from the authenticated principal, not trust a client-supplied `tenant_id` alone.
- Decide whether email uniqueness is global or tenant-scoped before adding a database constraint.
- Define role and status values before implementation.
- Review deletion behavior and foreign-key actions before creating migrations.

## 7. Proposed columns: devices and connectivity

These are preliminary logical designs. They do not create database objects.

### 7.1 `devices`

- `id` — UUID, primary key.
- `tenant_id` — UUID, required; owning tenant.
- `farm_id` — UUID, optional if devices may be registered before farm assignment.
- `zone_id` — UUID, optional; current assigned zone.
- `device_code` — text, required; stable human-readable identifier.
- `device_type` — text, required; approved device category.
- `name` — text, required.
- `status` — text, required; lifecycle vocabulary remains to be defined.
- `created_at` — timestamptz, required.
- `updated_at` — timestamptz, required.
- `last_seen_at` — timestamptz, optional; last accepted contact time.
- Add tenant-scoped uniqueness for (`tenant_id`, `id`) and (`tenant_id`, `device_code`).
- Farm and zone references must enforce tenant consistency using composite foreign keys where applicable.

### 7.2 `device_credentials`

- `id` — UUID, primary key.
- `tenant_id` — UUID, required.
- `device_id` — UUID, required.
- `credential_type` — text, required; exact supported types remain undecided.
- `secret_hash` — text, optional; use only for credential types designed for one-way verification.
- `public_key_fingerprint` — text, optional; for public-key credentials.
- `created_at` — timestamptz, required.
- `expires_at` — timestamptz, optional.
- `revoked_at` — timestamptz, optional.
- Never store plaintext passwords, tokens, or private keys in this table.
- Credential issuance, rotation, revocation, and recovery procedures must be defined before implementation.
- Add tenant-consistent foreign keys to the associated device.

### 7.3 `sensors`

- `id` — UUID, primary key.
- `tenant_id` — UUID, required.
- `device_id` — UUID, required.
- `zone_id` — UUID, optional.
- `sensor_code` — text, required; identifier unique within the agreed scope.
- `measurement_type` — text, required; for example temperature, humidity, pH, or electrical conductivity.
- `unit` — text, required; use a documented unit vocabulary.
- `status` — text, required.
- `created_at` — timestamptz, required.
- `updated_at` — timestamptz, required.
- Define whether a sensor can be reassigned between devices or zones and how historical attribution is preserved.
- Enforce tenant consistency for device and zone relationships.

### 7.4 `device_connections`

- `id` — UUID, primary key.
- `tenant_id` — UUID, required.
- `device_id` — UUID, required.
- `transport` — text, required; for example HTTPS/REST or Zigbee gateway forwarding.
- `connected_at` — timestamptz, required.
- `disconnected_at` — timestamptz, optional.
- `result` — text, required; exact status vocabulary remains to be defined.
- `details` — JSONB, optional; must exclude secrets and sensitive payloads.
- Use this table for connection history, not as the sole source of current device liveness.
- Define event deduplication and clock-skew handling before implementation.

### 7.5 Device security and tenancy safeguards

- Authenticate devices separately from human users.
- Derive tenant access from trusted enrollment and server-side authorization, not from an untrusted request field alone.
- Never accept device-supplied tenant or zone identifiers without validating their association.
- Define credential rotation, revocation, replay protection, and rate limits before production deployment.

## 8. Proposed columns: telemetry and device health

These are preliminary logical designs, not database migrations.

### 8.1 `telemetry_events`

- `id` — UUID, primary key for the server-side record.
- `tenant_id` — UUID, required.
- `device_id` — UUID, required.
- `event_id` — text, required; stable event identifier generated by the device.
- `occurred_at` — timestamptz, required; device-reported event time.
- `received_at` — timestamptz, required; server ingestion time.
- `schema_version` — integer, required.
- `payload` — JSONB, required; validated event envelope, with size limits.
- `payload_hash` — text, required; hash of a documented canonical representation.
- `ingest_status` — text, required; vocabulary to be defined.
- Deduplication proposal: unique (`device_id`, `event_id`).
- Retries of the same event must not create duplicate logical readings.
- Validate device identity, tenant ownership, timestamps, schema version, and payload size before accepting an event.

### 8.2 `sensor_readings`

- `id` — UUID, primary key.
- `tenant_id` — UUID, required.
- `telemetry_event_id` — UUID, required; source event.
- `device_id` — UUID, required.
- `sensor_id` — UUID, required.
- `measured_at` — timestamptz, required.
- `received_at` — timestamptz, required.
- `measurement_type` — text, required.
- `value_numeric` — numeric, optional for numeric measurements.
- `value_text` — text, optional for categorical measurements.
- `unit` — text, required.
- `quality_status` — text, required; vocabulary and validation rules to be defined.
- A check constraint should ensure the permitted value representation is unambiguous.
- Define how sensor reassignment affects historical readings before implementation.
- Enforce tenant-consistent references to the event, device, and sensor.

### 8.3 `device_heartbeats`

- `id` — UUID, primary key.
- `tenant_id` — UUID, required.
- `device_id` — UUID, required.
- `reported_at` — timestamptz, required; device-reported heartbeat time.
- `received_at` — timestamptz, required; server receipt time.
- `firmware_version` — text, optional.
- `uptime_seconds` — bigint, optional; must be non-negative.
- `health_payload` — JSONB, optional; validate keys and size, and exclude secrets.
- Heartbeat freshness must be calculated using server receipt time and an approved threshold.
- Consider storing all heartbeats only if operational requirements justify the storage volume; otherwise retain latest state plus selected history.

### 8.4 Ingestion and offline-replay safeguards

- The backend must authenticate the device before associating an event with a tenant.
- Preserve both device event time and server receipt time to handle clock skew.
- Define the accepted offline replay window and behavior for stale events before implementation.
- Make duplicate delivery idempotent and return a deterministic response for previously accepted event identifiers.
- Decide whether invalid events are rejected, quarantined, or recorded in a separate operational log.
- Do not trust a tenant identifier embedded in the payload without verifying it against the enrolled device.

## 9. Proposed columns: commands and firmware

### 9.1 `commands`

- `id` — UUID, primary key; unique command identity.
- `tenant_id` — UUID, required; tenant ownership.
- `device_id` — UUID, required; intended recipient.
- `requested_by_user_id` — UUID, optional when initiated by an authorized system process; initiating human user otherwise.
- `command_type` — text, required; allowlisted operation name.
- `parameters` — JSONB, required; validated against the command-type schema.
- `status` — text, required; proposed lifecycle vocabulary: `pending`, `sent`, `acknowledged`, `succeeded`, `failed`, `expired`, `cancelled`.
- `created_at` — timestamptz, required; server creation time.
- `expires_at` — timestamptz, required; latest time at which execution may begin.
- `updated_at` — timestamptz, required; last state update.
- `idempotency_key` — text, required; prevents duplicate command creation on client retries.
- `correlation_id` — UUID, optional; associates related commands and operational events.
- `result_summary` — JSONB, optional; validated, size-limited result metadata with no secrets.

### 9.2 `command_events`

- `id` — UUID, primary key.
- `tenant_id` — UUID, required.
- `command_id` — UUID, required; related command.
- `device_id` — UUID, required; reporting device.
- `event_type` — text, required; acknowledgement, progress, success, failure, or other approved lifecycle event.
- `occurred_at` — timestamptz, optional; device-reported event time.
- `received_at` — timestamptz, required; server receipt time.
- `event_id` — text, required; stable device-generated identifier for deduplication.
- `details` — JSONB, optional; validated and size-limited, excluding credentials and secrets.
- Lifecycle history should be append-only to preserve the audit trail.
- Deduplicate repeated event delivery and validate each transition against the command's current state.
- The exact delivery protocol and retry policy remain to be defined; commands must not be sent through MQTT.

### 9.3 `firmware_releases`

- `id` — UUID, primary key.
- `version` — text, required; release version.
- `hardware_target` — text, required; compatible device model or hardware family.
- `artifact_uri` — text, required; controlled artifact location, not an arbitrary device-supplied URL.
- `artifact_sha256` — text, required; digest of the exact firmware artifact.
- `signature_uri` — text, required; location of the detached signature or signed manifest.
- `signing_key_id` — text, required; identifier of the trusted signing key.
- `release_status` — text, required; proposed values to be defined for draft, approved, deprecated, and revoked releases.
- `created_at` — timestamptz, required.
- `approved_at` — timestamptz, optional.
- Verify signatures and artifact hashes before installation; a hash alone does not establish publisher authenticity.
- Define signing-key rotation, revocation, compatibility checks, and rollback protection before implementation.

### 9.4 `ota_jobs`

- `id` — UUID, primary key.
- `tenant_id` — UUID, required.
- `device_id` — UUID, required; target device.
- `firmware_release_id` — UUID, required; approved target release.
- `status` — text, required; proposed lifecycle values include `pending`, `downloading`, `verifying`, `installing`, `succeeded`, `failed`, `rolled_back`, and `cancelled`.
- `created_at` — timestamptz, required.
- `started_at` — timestamptz, optional.
- `completed_at` — timestamptz, optional.
- `previous_version` — text, optional; version observed before the update.
- `reported_version` — text, optional; version reported after the update.
- `failure_code` — text, optional; controlled failure vocabulary.
- `failure_details` — JSONB, optional; sanitized diagnostics without secrets.
- Require authenticated device reporting and verify the resulting firmware version.
- Define staged rollout limits, interruption recovery, rollback behavior, and operator approval before enabling OTA.
- Enforce tenant-consistent foreign keys and authorization checks for commands, events, releases, and jobs.

### 9.5 Command and OTA safeguards

- Treat command parameters as untrusted input; allowlist command types and validate each parameter schema.
- Enforce authorization at command creation and again at execution where relevant.
- Expired or cancelled commands must not begin execution; define how to handle a command already in progress.
- Record state transitions with actor, server timestamp, and correlation identifiers in the appropriate audit trail.
- Keep device credentials, private signing keys, and other secrets out of command payloads, result details, and logs.
- These lifecycle vocabularies are proposals and require review before implementation.

## 10. Proposed columns: agronomy and integrations

### 10.1 `manual_measurements`

- `id` — UUID, primary key.
- `tenant_id` — UUID, required; tenant ownership.
- `farm_id` — UUID, required; farm where the measurement was taken.
- `zone_id` — UUID, optional; specific zone, if applicable.
- `recorded_by_user_id` — UUID, required; authenticated user who entered the record.
- `measurement_type` — text, required; proposed examples include `NPK`, `pH`, and `electrical_conductivity`.
- `value_numeric` — numeric, required; measured value.
- `unit` — text, required; explicit unit or scale for interpretation.
- `measured_at` — timestamptz, required; time the sample was measured.
- `recorded_at` — timestamptz, required; server time the record was entered.
- `method` — text, optional; measurement method or instrument.
- `notes` — text, optional; length-limited and sanitized operator notes.
- `sample_reference` — text, optional; non-sensitive sample identifier.
- Define permitted measurement types, units, valid ranges, and instrument-specific rules before implementation.
- Preserve the distinction between the measurement time and the record-entry time.
- Do not interpret NPK values without an approved unit, scale, and nutrient-order convention.

### 10.2 `vpd_calculations`

- `id` — UUID, primary key.
- `tenant_id` — UUID, required.
- `farm_id` — UUID, required.
- `zone_id` — UUID, optional; zone to which the calculation applies.
- `calculated_at` — timestamptz, required; server calculation time.
- `temperature_c` — numeric, required; input air temperature in degrees Celsius.
- `relative_humidity_pct` — numeric, required; input relative humidity as a percentage.
- `vpd_kpa` — numeric, required; calculated vapor pressure deficit in kilopascals.
- `formula_version` — text, required; identifies the approved calculation method.
- `temperature_source_id` — UUID, optional; reference to the source sensor or measurement.
- `humidity_source_id` — UUID, optional; reference to the source sensor or measurement.
- `input_snapshot` — JSONB, optional; validated input metadata needed to reproduce the result.
- Validate temperature and relative humidity ranges and reject non-finite or invalid inputs.
- Document the saturation-vapor-pressure formula and whether leaf temperature is included.
- Retain the formula version and source inputs so historical results can be interpreted reproducibly.
- Decide the calculation cadence and retention policy before implementation.

### 10.3 `cctv_sources`

- `id` — UUID, primary key.
- `tenant_id` — UUID, required; tenant ownership.
- `farm_id` — UUID, required; associated farm.
- `zone_id` — UUID, optional; associated zone.
- `name` — text, required; operator-facing camera name.
- `provider_type` — text, required; approved integration or protocol identifier.
- `connection_reference` — text, optional; reference to securely managed connection configuration.
- `status` — text, required; proposed lifecycle vocabulary to be defined.
- `created_at` — timestamptz, required.
- `updated_at` — timestamptz, required.
- Store credentials and stream secrets in an approved secret-management mechanism, not in this table or ordinary logs.
- Avoid storing stream URLs containing credentials in audit records or API responses.
- Enforce tenant authorization before returning camera metadata or granting stream access.
- Define supported camera protocols, access method, retention, privacy controls, and network exposure before implementation.

### 10.4 Agronomy and integration safeguards

- Keep manually entered measurements distinguishable from device telemetry and derived calculations.
- Validate units and measurement ranges at the API boundary and preserve the original recorded values.
- Treat VPD as a derived value whose formula, input units, and source observations must be traceable.
- Do not expose CCTV streams directly to the public internet; document an authenticated access path and network policy.
- Enforce tenant-consistent foreign keys and server-side authorization for all farm, zone, measurement, calculation, and camera records.
- All fields and rules in this section are proposals and require review before migration.
