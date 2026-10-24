/**
 * Frontend domain contract for real zone data.
 *
 * These types do not define or assume the backend API response format.
 * Map the actual API response to these types after the API contract
 * has been confirmed.
 */

export type ZoneId = string;

export interface ZoneSummary {
  id: ZoneId;
  name: string;
  description?: string | null;
  status?: string | null;
}

export type SensorMetric =
  | "air_temperature"
  | "air_humidity"
  | "soil_moisture"
  | "vpd";

export interface SensorReading {
  metric: SensorMetric;
  value: number;
  unit: string;
  recordedAt: string;
}

export interface ZoneSensorData {
  readings: SensorReading[];
}

export interface NpkPhRecord {
  id: string;
  recordedAt: string;
  nitrogen?: number | null;
  phosphorus?: number | null;
  potassium?: number | null;
  ph?: number | null;
  note?: string | null;
}

export interface ZoneDevice {
  id: string;
  name: string;
  type: string;
  status?: string | null;
}

export interface ZoneDetailData {
  zone: ZoneSummary;
  sensors: ZoneSensorData | null;
  devices: ZoneDevice[];
  npkPhRecords: NpkPhRecord[];
}
