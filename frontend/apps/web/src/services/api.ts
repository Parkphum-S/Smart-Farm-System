const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/+$/, "");
const TOKEN_KEY = "smartfarm_access_token";

export interface AuthUser {
  id: string;
  email: string;
  display_name: string;
}

export interface TenantAccess {
  id: string;
  name: string;
  role: "owner" | "operator" | "viewer";
}

export interface LoginResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
  user: AuthUser;
}

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export const session = {
  getToken(): string | null {
    return sessionStorage.getItem(TOKEN_KEY);
  },

  setToken(token: string): void {
    sessionStorage.setItem(TOKEN_KEY, token);
  },

  clear(): void {
    sessionStorage.removeItem(TOKEN_KEY);
  },
};

async function request<T>(
  path: string,
  options: RequestInit = {},
  authenticated = true,
): Promise<T> {
  const headers = new Headers(options.headers);
  headers.set("Accept", "application/json");

  if (options.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  const token = session.getToken();
  if (authenticated && token) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  let response: Response;

  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...options,
      headers,
    });
  } catch {
    throw new ApiError(
      "ไม่สามารถเชื่อมต่อเซิร์ฟเวอร์ได้ กรุณาตรวจสอบการเชื่อมต่อ API",
      0,
    );
  }

  if (response.status === 401 && authenticated) {
    session.clear();
    window.dispatchEvent(new Event("smartfarm:unauthorized"));
  }

  if (!response.ok) {
    let message = `เกิดข้อผิดพลาดจากเซิร์ฟเวอร์ (${response.status})`;

    try {
      const body: unknown = await response.json();
      if (
        typeof body === "object" &&
        body !== null &&
        "detail" in body
      ) {
        const detail = (body as { detail?: unknown }).detail;
        if (typeof detail === "string") {
          message = detail;
        }
      }
    } catch {
      // ใช้ข้อความมาตรฐานเมื่อ response ไม่มี JSON
    }

    throw new ApiError(message, response.status);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return (await response.json()) as T;
}

export interface Farm {
  id: string;
  name: string;
  timezone: string;
  latitude: number | null;
  longitude: number | null;
  created_at: string;
  updated_at: string;
}

export interface FarmCreate {
  name: string;
  timezone: string;
  latitude: number | null;
  longitude: number | null;
}

export type FarmUpdate = Partial<FarmCreate>;

export interface FarmWeather {
  temperature: number;
  feels_like: number;
  humidity: number;
  pressure: number;
  wind_speed: number;
  wind_deg: number | null;
  description: string;
  icon: string;
  observed_at: string;
  source: string;
}

export interface FarmAirPollution {
  pm2_5: number;
  aqi: number;
  aqi_label: string;
  observed_at: string;
  source: string;
}

export const farmApi = {
  list(tenantId: string): Promise<Farm[]> {
    return request<Farm[]>(
      `/api/v1/tenants/${encodeURIComponent(tenantId)}/farms`,
    );
  },

  create(tenantId: string, data: FarmCreate): Promise<Farm> {
    return request<Farm>(
      `/api/v1/tenants/${encodeURIComponent(tenantId)}/farms`,
      { method: "POST", body: JSON.stringify(data) },
    );
  },

  update(tenantId: string, farmId: string, data: FarmUpdate): Promise<Farm> {
    return request<Farm>(
      `/api/v1/tenants/${encodeURIComponent(tenantId)}/farms/${encodeURIComponent(farmId)}`,
      { method: "PATCH", body: JSON.stringify(data) },
    );
  },

  delete(tenantId: string, farmId: string): Promise<void> {
    return request<void>(
      `/api/v1/tenants/${encodeURIComponent(tenantId)}/farms/${encodeURIComponent(farmId)}`,
      { method: "DELETE" },
    );
  },

  async uploadImage(
    tenantId: string,
    farmId: string,
    file: File,
  ): Promise<void> {
    const form = new FormData();
    form.append("image", file);

    const token = session.getToken();
    const headers = new Headers({ Accept: "application/json" });
    if (token) headers.set("Authorization", `Bearer ${token}`);

    let response: Response;
    try {
      response = await fetch(
        `${API_BASE_URL}/api/v1/tenants/${encodeURIComponent(tenantId)}/farms/${encodeURIComponent(farmId)}/image`,
        { method: "POST", headers, body: form },
      );
    } catch {
      throw new ApiError(
        "ไม่สามารถเชื่อมต่อเซิร์ฟเวอร์ได้ กรุณาตรวจสอบการเชื่อมต่อ API",
        0,
      );
    }

    if (response.status === 401) {
      session.clear();
      window.dispatchEvent(new Event("smartfarm:unauthorized"));
    }
    if (!response.ok) {
      let message = `เกิดข้อผิดพลาดจากเซิร์ฟเวอร์ (${response.status})`;
      try {
        const body: unknown = await response.json();
        if (typeof body === "object" && body !== null && "detail" in body) {
          const detail = (body as { detail?: unknown }).detail;
          if (typeof detail === "string") message = detail;
        }
      } catch {
        // ใช้ข้อความมาตรฐานเมื่อ response ไม่มี JSON
      }
      throw new ApiError(message, response.status);
    }
  },

  async getImage(tenantId: string, farmId: string): Promise<Blob> {
    const token = session.getToken();
    const headers = new Headers();
    if (token) headers.set("Authorization", `Bearer ${token}`);

    let response: Response;
    try {
      response = await fetch(
        `${API_BASE_URL}/api/v1/tenants/${encodeURIComponent(tenantId)}/farms/${encodeURIComponent(farmId)}/image`,
        { method: "GET", headers, cache: "no-store" },
      );
    } catch {
      throw new ApiError(
        "ไม่สามารถเชื่อมต่อเซิร์ฟเวอร์ได้ กรุณาตรวจสอบการเชื่อมต่อ API",
        0,
      );
    }

    if (response.status === 401) {
      session.clear();
      window.dispatchEvent(new Event("smartfarm:unauthorized"));
    }
    if (!response.ok) {
      let message = `เกิดข้อผิดพลาดจากเซิร์ฟเวอร์ (${response.status})`;
      try {
        const body: unknown = await response.json();
        if (typeof body === "object" && body !== null && "detail" in body) {
          const detail = (body as { detail?: unknown }).detail;
          if (typeof detail === "string") message = detail;
        }
      } catch {
        // ใช้ข้อความมาตรฐานเมื่อ response ไม่มี JSON
      }
      throw new ApiError(message, response.status);
    }
    return response.blob();
  },
};


export const weatherApi = {
  get(tenantId: string, farmId: string): Promise<FarmWeather> {
    return request<FarmWeather>(
      `/api/v1/tenants/${encodeURIComponent(tenantId)}/farms/${encodeURIComponent(farmId)}/weather`,
    );
  },
};


export const airPollutionApi = {
  get(tenantId: string, farmId: string): Promise<FarmAirPollution> {
    return request<FarmAirPollution>(
      `/api/v1/tenants/${encodeURIComponent(tenantId)}/farms/${encodeURIComponent(farmId)}/air-pollution`,
    );
  },
};


export type ZoneType =
  | "plant"
  | "livestock"
  | "fish_pond"
  | "mushroom"
  | "cctv"
  | "lighting";

export type ZoneCategoryDetails = Record<string, unknown>;

export const zoneTypeLabels: Record<ZoneType, string> = {
  plant: "พืช",
  livestock: "ปศุสัตว์",
  fish_pond: "บ่อปลา",
  mushroom: "เห็ด",
  cctv: "กล้องวงจรปิด",
  lighting: "แสงสว่าง",
};

export interface Zone {
  id: string;
  tenant_id: string;
  farm_id: string;
  name: string;
  description: string | null;
  status: "active" | "disabled";
  zone_type: ZoneType;
  category_details: ZoneCategoryDetails;
  created_at: string;
  updated_at: string;
}

export interface ZoneCreate {
  name: string;
  description?: string | null;
  status?: "active" | "disabled";
  zone_type: ZoneType;
  category_details: ZoneCategoryDetails;
}

export type ZoneUpdate = Partial<ZoneCreate>;

export const zoneApi = {
  list(tenantId: string, farmId: string, query = ""): Promise<Zone[]> {
    const suffix = query.trim()
      ? `?q=${encodeURIComponent(query.trim())}`
      : "";
    return request<Zone[]>(
      `/api/v1/tenants/${encodeURIComponent(tenantId)}/farms/${encodeURIComponent(farmId)}/zones${suffix}`,
    );
  },

  create(tenantId: string, farmId: string, data: ZoneCreate): Promise<Zone> {
    return request<Zone>(
      `/api/v1/tenants/${encodeURIComponent(tenantId)}/farms/${encodeURIComponent(farmId)}/zones`,
      { method: "POST", body: JSON.stringify(data) },
    );
  },

  update(
    tenantId: string,
    farmId: string,
    zoneId: string,
    data: ZoneUpdate,
  ): Promise<Zone> {
    return request<Zone>(
      `/api/v1/tenants/${encodeURIComponent(tenantId)}/farms/${encodeURIComponent(farmId)}/zones/${encodeURIComponent(zoneId)}`,
      { method: "PATCH", body: JSON.stringify(data) },
    );
  },

  delete(tenantId: string, farmId: string, zoneId: string): Promise<void> {
    return request<void>(
      `/api/v1/tenants/${encodeURIComponent(tenantId)}/farms/${encodeURIComponent(farmId)}/zones/${encodeURIComponent(zoneId)}`,
      { method: "DELETE" },
    );
  },
};


export interface Device {
  id: string;
  device_code: string;
  device_type: string;
  name: string;
  status: "pending" | "active" | "disabled" | "revoked" | string;
  farm_id: string | null;
  zone_id: string | null;
  last_seen_at: string | null;
  created_at: string;
  updated_at: string;
}

export const deviceApi = {
  list(tenantId: string): Promise<Device[]> {
    return request<Device[]>(
      `/api/v1/tenants/${encodeURIComponent(tenantId)}/devices`,
    );
  },

  create(
    tenantId: string,
    data: {
      device_code?: string;
      device_type: string;
      name: string;
      farm_id: string | null;
      status?: "pending" | "active" | "disabled" | "revoked";
    },
  ): Promise<Device> {
    return request<Device>(
      `/api/v1/tenants/${encodeURIComponent(tenantId)}/devices`,
      { method: "POST", body: JSON.stringify(data) },
    );
  },

  update(
    tenantId: string,
    deviceId: string,
    data: {
      device_type?: string;
      name?: string;
      farm_id?: string | null;
      status?: "pending" | "active" | "disabled" | "revoked";
    },
  ): Promise<Device> {
    return request<Device>(
      `/api/v1/tenants/${encodeURIComponent(tenantId)}/devices/${encodeURIComponent(deviceId)}`,
      { method: "PATCH", body: JSON.stringify(data) },
    );
  },

  assignZone(
    tenantId: string,
    deviceId: string,
    zoneId: string | null,
  ): Promise<Device> {
    return request<Device>(
      `/api/v1/tenants/${encodeURIComponent(tenantId)}/devices/${encodeURIComponent(deviceId)}/zone`,
      {
        method: "PATCH",
        body: JSON.stringify({ zone_id: zoneId }),
      },
    );
  },
};


export type SensorStatus = "active" | "disabled" | "retired";

export interface Sensor {
  id: string;
  tenant_id: string;
  device_id: string;
  sensor_code: string;
  measurement_type: string;
  unit: string;
  status: SensorStatus;
  created_at: string;
}

export const sensorApi = {
  list(tenantId: string, deviceId: string): Promise<Sensor[]> {
    return request<Sensor[]>(
      `/api/v1/tenants/${encodeURIComponent(tenantId)}/devices/${encodeURIComponent(deviceId)}/sensors`,
    );
  },
  create(tenantId: string, deviceId: string, data: {
    measurement_type: string;
    unit: string;
  }): Promise<Sensor> {
    return request<Sensor>(
      `/api/v1/tenants/${encodeURIComponent(tenantId)}/devices/${encodeURIComponent(deviceId)}/sensors`,
      { method: "POST", body: JSON.stringify(data) },
    );
  },
  update(tenantId: string, deviceId: string, sensorId: string, data: {
    measurement_type?: string;
    unit?: string;
    status?: SensorStatus;
  }): Promise<Sensor> {
    return request<Sensor>(
      `/api/v1/tenants/${encodeURIComponent(tenantId)}/devices/${encodeURIComponent(deviceId)}/sensors/${encodeURIComponent(sensorId)}`,
      { method: "PATCH", body: JSON.stringify(data) },
    );
  },
};

export interface TelemetryReading {
  id: string;
  sensor_id: string;
  sensor_code: string;
  device_id: string;
  device_name: string;
  metric: string;
  value: number;
  unit: string;
  quality_status: string;
  measured_at: string;
  received_at: string;
}

export const telemetryApi = {
  list(
    tenantId: string,
    params: {
      latest_only?: boolean;
      limit?: number;
      metric?: string;
      sensor_id?: string;
      since?: string;
      until?: string;
    } = {},
  ): Promise<TelemetryReading[]> {
    const query = new URLSearchParams();
    if (params.latest_only !== undefined) {
      query.set("latest_only", String(params.latest_only));
    }
    if (params.limit !== undefined) {
      query.set("limit", String(params.limit));
    }
    if (params.metric !== undefined) {
      query.set("metric", params.metric);
    }
    if (params.sensor_id !== undefined) {
      query.set("sensor_id", params.sensor_id);
    }
    if (params.since !== undefined) {
      query.set("since", params.since);
    }
    if (params.until !== undefined) {
      query.set("until", params.until);
    }

    const suffix = query.toString();
    return request<TelemetryReading[]>(
      `/api/v1/tenants/${encodeURIComponent(tenantId)}/telemetry/readings${suffix ? `?${suffix}` : ""}`,
    );
  },
};

export interface DeviceCommand {
  id: string;
  device_id: string;
  command_type: string;
  parameters: {
    relay: number;
    state: "on" | "off";
  };
  status: string;
  created_at: string;
  expires_at: string;
  updated_at: string;
  correlation_id: string | null;
  result_summary: Record<string, unknown> | null;
}

export interface CommandCreateResult {
  command: DeviceCommand;
  duplicate: boolean;
}

export interface CommandHistoryResult {
  commands: DeviceCommand[];
}

export const commandApi = {
  createRelayCommand(
    tenantId: string,
    deviceId: string,
    relay: number,
    state: "on" | "off",
    idempotencyKey: string,
  ): Promise<CommandCreateResult> {
    if (!Number.isInteger(relay) || relay < 1 || relay > 4) {
      throw new Error("หมายเลข Relay ต้องอยู่ระหว่าง 1 ถึง 4");
    }

    return request<CommandCreateResult>(
      `/api/v1/tenants/${encodeURIComponent(tenantId)}/devices/${encodeURIComponent(deviceId)}/commands`,
      {
        method: "POST",
        body: JSON.stringify({
          command_type: "relay.set",
          parameters: { relay, state },
          idempotency_key: idempotencyKey,
          expires_in_seconds: 60,
        }),
      },
    );
  },

  history(
    tenantId: string,
    deviceId: string,
    limit = 20,
  ): Promise<CommandHistoryResult> {
    const safeLimit = Math.max(1, Math.min(100, Math.floor(limit)));

    return request<CommandHistoryResult>(
      `/api/v1/tenants/${encodeURIComponent(tenantId)}/devices/${encodeURIComponent(deviceId)}/commands?limit=${safeLimit}`,
    );
  },
};

export const authApi = {
  tenants(): Promise<TenantAccess[]> {
    return request<TenantAccess[]>("/api/v1/auth/tenants");
  },


  login(email: string, password: string): Promise<LoginResponse> {
    return request<LoginResponse>(
      "/api/v1/auth/login",
      {
        method: "POST",
        body: JSON.stringify({ email, password }),
      },
      false,
    );
  },

  me(): Promise<AuthUser> {
    return request<AuthUser>("/api/v1/auth/me");
  },

  logout(): Promise<void> {
    return request<void>("/api/v1/auth/logout", {
      method: "POST",
    });
  },
};
