import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { ApiError, airPollutionApi, authApi, commandApi, deviceApi, farmApi, sensorApi, telemetryApi, weatherApi, zoneApi } from "./services/api";
import type { Farm, FarmAirPollution, FarmWeather, TenantAccess } from "./services/api";
import type { DeviceCommand } from "./services/api";
import type { Device, Sensor, SensorStatus, TelemetryReading } from "./services/api";
import type { Zone, ZoneType, ZoneCategoryDetails } from "./services/api";
import { zoneTypeLabels } from "./services/api";

async function copyTextToClipboard(value: string): Promise<void> {
  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(value);
      return;
    } catch {
      // Try the fallback below.
    }
  }

  const textarea = document.createElement("textarea");
  textarea.value = value;
  textarea.setAttribute("readonly", "");
  textarea.style.position = "fixed";
  textarea.style.opacity = "0";
  textarea.style.pointerEvents = "none";
  document.body.appendChild(textarea);

  try {
    textarea.select();
    textarea.setSelectionRange(0, textarea.value.length);

    if (!document.execCommand("copy")) {
      throw new Error("Browser rejected clipboard copy");
    }
  } finally {
    textarea.remove();
  }
}


const navigation = [
  {
    title: "ภาพรวม",
    items: [{ id: "dashboard", label: "Dashboard", icon: "◫" }],
  },
  {
    title: "การจัดการฟาร์ม",
    items: [
      { id: "farms", label: "Farm Management", icon: "⌂" },
      { id: "zones", label: "Zone Management", icon: "▦" },
      { id: "devices", label: "Device Management", icon: "▣" },
      { id: "sensors", label: "Sensor Management", icon: "⌁" },
    ],
  },
  {
    title: "ข้อมูลและรายงาน",
    items: [
      { id: "reports", label: "Reports", icon: "▤" },
      { id: "alerts", label: "Alerts", icon: "♧" },
    ],
  },
  {
    title: "ระบบ",
    items: [{ id: "settings", label: "Users & Settings", icon: "⚙" }],
  },
];

const pageTitles: Record<string, { title: string; description: string }> = {
  "farm-detail": {
    title: "จัดการฟาร์ม",
    description: "รายละเอียดและการจัดการฟาร์มที่เลือก",
  },
  dashboard: {
    title: "ภาพรวมฟาร์ม",
    description: "ติดตามสภาพแวดล้อม สถานะโซน และอุปกรณ์จากที่เดียว",
  },
  farms: {
    title: "จัดการฟาร์ม",
    description: "จัดการข้อมูลฟาร์มและขอบเขตการเข้าถึง",
  },
  zones: {
    title: "จัดการโซน",
    description: "ติดตามพื้นที่เพาะปลูกและค่าต่าง ๆ ของแต่ละโซน",
  },
  devices: {
    title: "จัดการอุปกรณ์",
    description: "ตรวจสอบ Gateway, Zigbee, Tuya และอุปกรณ์ควบคุม",
  },
  sensors: {
    title: "จัดการเซนเซอร์",
    description: "ตรวจสอบค่าที่วัดได้ หน่วย และคุณภาพของข้อมูล",
  },
  reports: {
    title: "รายงาน",
    description: "ดูแนวโน้มและข้อมูลย้อนหลังเมื่อมีข้อมูลพร้อมใช้งาน",
  },
  alerts: {
    title: "การแจ้งเตือน",
    description: "ติดตามเหตุการณ์และสถานะการแก้ไข",
  },
  settings: {
    title: "ผู้ใช้และการตั้งค่า",
    description: "จัดการบัญชี สิทธิ์ และการตั้งค่าระบบ",
  },
};

type SensorMeasurementOption = {
  value: string;
  label: string;
  units: string[];
  defaultUnit: string;
};

type SensorMeasurementGroup = {
  label: string;
  options: SensorMeasurementOption[];
};

const SENSOR_MEASUREMENT_GROUPS: SensorMeasurementGroup[] = [
  {
    label: "สภาพอากาศและบรรยากาศ",
    options: [
      { value: "temperature", label: "อุณหภูมิ", units: ["celsius", "fahrenheit", "kelvin"], defaultUnit: "celsius" },
      { value: "humidity", label: "ความชื้นสัมพัทธ์", units: ["percent"], defaultUnit: "percent" },
      { value: "pressure", label: "ความดันอากาศ", units: ["hPa", "kPa", "Pa", "bar", "psi"], defaultUnit: "hPa" },
      { value: "altitude", label: "ระดับความสูง", units: ["m", "cm", "ft"], defaultUnit: "m" },
    ],
  },
  {
    label: "แสงและรังสี",
    options: [
      { value: "illuminance", label: "ความเข้มแสง", units: ["lux"], defaultUnit: "lux" },
      { value: "solar_irradiance", label: "ความเข้มรังสีแสงอาทิตย์", units: ["W/m2", "kW/m2"], defaultUnit: "W/m2" },
      { value: "par", label: "รังสี PAR สำหรับพืช", units: ["umol/m2/s", "mol/m2/day"], defaultUnit: "umol/m2/s" },
      { value: "uv_index", label: "ดัชนีรังสี UV", units: ["index"], defaultUnit: "index" },
    ],
  },
  {
    label: "คุณภาพอากาศ",
    options: [
      { value: "co2", label: "คาร์บอนไดออกไซด์ (CO2)", units: ["ppm"], defaultUnit: "ppm" },
      { value: "voc", label: "สารอินทรีย์ระเหยง่าย (VOC)", units: ["ppb", "ppm"], defaultUnit: "ppb" },
      { value: "pm25", label: "ฝุ่นละออง PM2.5", units: ["ug/m3"], defaultUnit: "ug/m3" },
      { value: "pm10", label: "ฝุ่นละออง PM10", units: ["ug/m3"], defaultUnit: "ug/m3" },
      { value: "air_quality_index", label: "ดัชนีคุณภาพอากาศ (AQI)", units: ["index"], defaultUnit: "index" },
    ],
  },
  {
    label: "ดินและคุณภาพน้ำ",
    options: [
      { value: "soil_moisture", label: "ความชื้นในดิน", units: ["percent", "m3/m3"], defaultUnit: "percent" },
      { value: "soil_temperature", label: "อุณหภูมิดิน", units: ["celsius", "fahrenheit"], defaultUnit: "celsius" },
      { value: "ph", label: "ค่าความเป็นกรด-ด่าง (pH)", units: ["pH"], defaultUnit: "pH" },
      { value: "ec", label: "ค่าการนำไฟฟ้า (EC)", units: ["uS/cm", "mS/cm"], defaultUnit: "uS/cm" },
      { value: "tds", label: "สารละลายทั้งหมด (TDS)", units: ["ppm", "mg/L"], defaultUnit: "ppm" },
      { value: "salinity", label: "ความเค็ม", units: ["ppt", "PSU", "g/L"], defaultUnit: "ppt" },
      { value: "dissolved_oxygen", label: "ออกซิเจนละลายในน้ำ (DO)", units: ["mg/L", "percent"], defaultUnit: "mg/L" },
      { value: "water_temperature", label: "อุณหภูมิน้ำ", units: ["celsius", "fahrenheit"], defaultUnit: "celsius" },
    ],
  },
  {
    label: "อุตุนิยมวิทยา",
    options: [
      { value: "rainfall", label: "ปริมาณน้ำฝน", units: ["mm", "mm/h"], defaultUnit: "mm" },
      { value: "wind_speed", label: "ความเร็วลม", units: ["m/s", "km/h"], defaultUnit: "m/s" },
      { value: "wind_direction", label: "ทิศทางลม", units: ["degree"], defaultUnit: "degree" },
      { value: "leaf_wetness", label: "ความเปียกชื้นของใบ", units: ["percent"], defaultUnit: "percent" },
    ],
  },
  {
    label: "ระบบน้ำและชลประทาน",
    options: [
      { value: "water_level", label: "ระดับน้ำ", units: ["mm", "cm", "m", "percent"], defaultUnit: "cm" },
      { value: "flow_rate", label: "อัตราการไหล", units: ["L/min", "L/h", "m3/h"], defaultUnit: "L/min" },
    ],
  },
  {
    label: "ไฟฟ้าและพลังงาน",
    options: [
      { value: "voltage", label: "แรงดันไฟฟ้า", units: ["V", "mV"], defaultUnit: "V" },
      { value: "current", label: "กระแสไฟฟ้า", units: ["A", "mA"], defaultUnit: "A" },
      { value: "power", label: "กำลังไฟฟ้า", units: ["W", "kW"], defaultUnit: "W" },
      { value: "energy", label: "พลังงานไฟฟ้า", units: ["Wh", "kWh"], defaultUnit: "Wh" },
      { value: "frequency", label: "ความถี่", units: ["Hz", "kHz"], defaultUnit: "Hz" },
      { value: "battery_level", label: "ระดับแบตเตอรี่", units: ["percent"], defaultUnit: "percent" },
    ],
  },
  {
    label: "ระยะทางและการตรวจจับ",
    options: [
      { value: "distance", label: "ระยะทาง", units: ["mm", "cm", "m"], defaultUnit: "cm" },
      { value: "vibration", label: "การสั่นสะเทือน", units: ["m/s2", "mm/s"], defaultUnit: "m/s2" },
      { value: "sound_level", label: "ระดับเสียง", units: ["dB"], defaultUnit: "dB" },
      { value: "motion", label: "การตรวจจับการเคลื่อนไหว", units: ["boolean"], defaultUnit: "boolean" },
    ],
  },
];

const SENSOR_MEASUREMENT_OPTIONS = SENSOR_MEASUREMENT_GROUPS.flatMap(
  (group) => group.options,
);

const metrics = [
  { label: "Gateway ทั้งหมด", icon: "⌁", unit: "Gateway" },
  { label: "การแจ้งเตือนค้าง", icon: "♧", unit: "รายการ" },
];

const zoneMetrics = [
  { label: "อุณหภูมิอากาศ", unit: "°C" },
  { label: "ความชื้นอากาศ", unit: "%" },
  { label: "ความชื้นดิน", unit: "%" },
  { label: "VPD", unit: "kPa" },
];

function formatThaiDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;

  const formatted = new Intl.DateTimeFormat("th-TH-u-ca-buddhist", {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(date);

  return `${formatted} น.`;
}

function isTenantUuid(value: string): boolean {
  return /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(
    value.trim(),
  );
}

function isDeviceRecentlyOnline(
  device: Device,
  now = Date.now(),
): boolean {
  if (device.status !== "active" || !device.last_seen_at) {
    return false;
  }

  const lastSeen = Date.parse(device.last_seen_at);
  const age = now - lastSeen;

  return Number.isFinite(lastSeen) && age >= 0 && age <= 5 * 60 * 1000;
}

function formatTenantDisplayId(tenantId: string): string {
  if (!isTenantUuid(tenantId)) {
    return "ไม่มี Tenant UUID ที่ถูกต้อง";
  }

  return `TID${tenantId.replace(/-/g, "").slice(-4)}`;
}

export default function App() {
  const [selectedPage, setSelectedPage] = useState("dashboard");
  const [selectedDeviceZone, setSelectedDeviceZone] = useState<{
    id: string;
    name: string;
    farmId: string;
  } | null>(null);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [selectedRange, setSelectedRange] = useState("24 ชั่วโมง");
  const [selectedVariable, setSelectedVariable] = useState("อุณหภูมิ");
  const [selectedDashboardFarmId, setSelectedDashboardFarmId] = useState("");
  const [selectedDashboardZoneId, setSelectedDashboardZoneId] = useState("all");
  const [selectedDashboardStatusZoneId, setSelectedDashboardStatusZoneId] = useState("all");
  const [zoneSearch, setZoneSearch] = useState("");

  const [zones, setZones] = useState<Zone[]>([]);
  const [zonesLoading, setZonesLoading] = useState(false);
  const [zonesError, setZonesError] = useState("");
  const [zonesRequested, setZonesRequested] = useState(false);
  const [zonesReloadKey, setZonesReloadKey] = useState(0);
  const [zoneName, setZoneName] = useState("");
  const [zoneDescription, setZoneDescription] = useState("");
  const [zoneStatus, setZoneStatus] = useState<"active" | "disabled">("active");
  const [zoneType, setZoneType] = useState<ZoneType>("plant");
  const [zoneCategoryDetails, setZoneCategoryDetails] = useState<ZoneCategoryDetails>({});
  const [zoneRelayMappingText, setZoneRelayMappingText] = useState("{}");
  const [editingZoneId, setEditingZoneId] = useState<string | null>(null);
  const [zoneFormOpen, setZoneFormOpen] = useState(false);
  const [zoneSaving, setZoneSaving] = useState(false);
  const [zoneFormError, setZoneFormError] = useState("");
  const [zoneActionMessage, setZoneActionMessage] = useState("");

  const [selectedZoneTab, setSelectedZoneTab] = useState("overview");
  const [tenantId, setTenantId] = useState(() => {
    try {
      const saved = localStorage.getItem("smartfarm.selectedTenantId") ?? "";
      return isTenantUuid(saved) ? saved : "";
    } catch {
      return "";
    }
  });
  const [tenantHistory, setTenantHistory] = useState<string[]>(() => {
    try {
      const saved = JSON.parse(
        localStorage.getItem("smartfarm.tenantHistory") ?? "[]",
      );
      return Array.isArray(saved)
        ? saved.filter(
            (value): value is string =>
              typeof value === "string" && isTenantUuid(value),
          ).slice(0, 10)
        : [];
    } catch {
      return [];
    }
  });
  const [authorizedTenants, setAuthorizedTenants] = useState<TenantAccess[]>([]);
  const [tenantListLoading, setTenantListLoading] = useState(true);
  const [tenantListError, setTenantListError] = useState("");

  const [farms, setFarms] = useState<Farm[]>([]);
  const [farmsLoading, setFarmsLoading] = useState(false);
  const [farmsError, setFarmsError] = useState("");
  const [farmsRequested, setFarmsRequested] = useState(false);
  const [farmsReloadKey, setFarmsReloadKey] = useState(0);
  const [farmFormMode, setFarmFormMode] = useState<"create" | "edit" | null>(null);
  const [farmName, setFarmName] = useState("");
  const [farmTimezone, setFarmTimezone] = useState("Asia/Bangkok");
  const [farmLatitude, setFarmLatitude] = useState("");
  const [farmLongitude, setFarmLongitude] = useState("");
  const [farmSaving, setFarmSaving] = useState(false);
  const [farmActionError, setFarmActionError] = useState("");
  const [farmActionMessage, setFarmActionMessage] = useState("");
  const [farmImageUrls, setFarmImageUrls] = useState<Record<string, string>>({});
  const [farmImageReloadKey, setFarmImageReloadKey] = useState(0);
  const [farmImageBusy, setFarmImageBusy] = useState(false);
  const [farmImageError, setFarmImageError] = useState("");
  const [devices, setDevices] = useState<Device[]>([]);
  const [devicesLoading, setDevicesLoading] = useState(false);
  const [devicesError, setDevicesError] = useState("");
  const [devicesRequested, setDevicesRequested] = useState(false);
  const [devicesReloadKey, setDevicesReloadKey] = useState(0);

  const [sensors, setSensors] = useState<Sensor[]>([]);
  const [sensorDevices, setSensorDevices] = useState<Device[]>([]);
  const [sensorsLoading, setSensorsLoading] = useState(false);
  const [sensorsError, setSensorsError] = useState("");
  const [sensorReloadKey, setSensorReloadKey] = useState(0);
  const [selectedSensorDeviceId, setSelectedSensorDeviceId] = useState("");
  const [sensorFormMode, setSensorFormMode] = useState<"create" | "edit" | null>(null);
  const [sensorEditing, setSensorEditing] = useState<Sensor | null>(null);
  const [sensorFormDeviceId, setSensorFormDeviceId] = useState("");
  const [sensorFormType, setSensorFormType] = useState("");
  const [sensorFormUnit, setSensorFormUnit] = useState("");
  const [sensorFormStatus, setSensorFormStatus] = useState<SensorStatus>("active");
  const [sensorSaving, setSensorSaving] = useState(false);
  const [sensorFormError, setSensorFormError] = useState("");
  const [deviceFormMode, setDeviceFormMode] = useState<"create" | "edit" | null>(null);
  const [deviceEditing, setDeviceEditing] = useState<Device | null>(null);
  const [deviceFormCode, setDeviceFormCode] = useState("");
  const [deviceFormType, setDeviceFormType] = useState("");
  const [deviceFormName, setDeviceFormName] = useState("");
  const [deviceFormFarmId, setDeviceFormFarmId] = useState("");
  const [deviceFormStatus, setDeviceFormStatus] = useState<"pending" | "active" | "disabled" | "revoked">("pending");
  const [deviceFormSaving, setDeviceFormSaving] = useState(false);
  const [deviceFormError, setDeviceFormError] = useState("");
  const [deviceZonesByFarm, setDeviceZonesByFarm] = useState<Record<string, Zone[]>>({});
  const [deviceZoneLoading, setDeviceZoneLoading] = useState<Record<string, boolean>>({});
  const [deviceZoneLoadErrors, setDeviceZoneLoadErrors] = useState<Record<string, string>>({});
  const [deviceZoneSaving, setDeviceZoneSaving] = useState<Record<string, boolean>>({});
  const [deviceZoneMessages, setDeviceZoneMessages] = useState<Record<string, string>>({});
  const [deviceZoneErrors, setDeviceZoneErrors] = useState<Record<string, string>>({});
  const [copiedField, setCopiedField] = useState("");
  const [telemetryReadings, setTelemetryReadings] = useState<TelemetryReading[]>([]);
  const [telemetryLoading, setTelemetryLoading] = useState(false);
  const [telemetryError, setTelemetryError] = useState("");
  const [telemetryRequested, setTelemetryRequested] = useState(false);
  const [telemetryReloadKey, setTelemetryReloadKey] = useState(0);

  const [dashboardData, setDashboardData] = useState<{
    farms: Farm[];
    devices: Device[];
    zones: Zone[];
  } | null>(null);
  const [dashboardLoading, setDashboardLoading] = useState(false);
  const [dashboardError, setDashboardError] = useState("");
  const [dashboardWeather, setDashboardWeather] = useState<FarmWeather | null>(null);
  const [dashboardWeatherError, setDashboardWeatherError] = useState("");
  const [dashboardWeatherLoading, setDashboardWeatherLoading] = useState(false);
  const [dashboardAirPollution, setDashboardAirPollution] = useState<FarmAirPollution | null>(null);
  const [dashboardAirPollutionError, setDashboardAirPollutionError] = useState("");
  const [dashboardAirPollutionLoading, setDashboardAirPollutionLoading] = useState(false);
  const [dashboardReadings, setDashboardReadings] = useState<TelemetryReading[]>([]);
  const [dashboardTelemetryLoading, setDashboardTelemetryLoading] = useState(false);
  const [dashboardTelemetryError, setDashboardTelemetryError] = useState("");

const [relayBusyKey, setRelayBusyKey] = useState("");
const [relayPanelsOpen, setRelayPanelsOpen] = useState<Record<string, boolean>>({});
const [relayMessages, setRelayMessages] = useState<Record<string, string>>({});
const [relayErrors, setRelayErrors] = useState<Record<string, string>>({});
const [relayReportedStates, setRelayReportedStates] = useState<Record<string, "on" | "off" | "unknown">>({});
const [commandHistories, setCommandHistories] = useState<Record<string, DeviceCommand[]>>({});
const [commandHistoryLoading, setCommandHistoryLoading] = useState<Record<string, boolean>>({});
const [commandHistoryErrors, setCommandHistoryErrors] = useState<Record<string, string>>({});

// Invalidate asynchronous operations when the selected tenant changes.
const tenantContextRef = useRef(tenantId.trim());
const relayOperationRef = useRef(0);
const historyOperationRef = useRef<Record<string, number>>({});
const historySequenceRef = useRef(0);

useLayoutEffect(() => {
  tenantContextRef.current = tenantId.trim();
  relayOperationRef.current += 1;
  historyOperationRef.current = {};
  setRelayBusyKey("");
  setCommandHistoryLoading({});
}, [tenantId]);

  const [selectedFarm, setSelectedFarm] = useState<
    (Farm & { displayId: string }) | null
  >(null);

  const canManageFarms = ["owner", "operator"].includes(
    authorizedTenants.find(
      (item) => item.id.toLowerCase() === tenantId.trim().toLowerCase(),
    )?.role ?? "",
  );


  const zoneTabs = [
    { id: "overview", label: "ภาพรวม" },
    { id: "sensors", label: "เซนเซอร์" },
    { id: "devices", label: "อุปกรณ์" },
    { id: "history", label: "กราฟย้อนหลัง" },
    { id: "settings", label: "การตั้งค่า" },
  ];



  useEffect(() => {
    let cancelled = false;

    authApi.tenants()
      .then((items) => {
        if (cancelled) return;

        const validItems = items.filter(
          (item) =>
            isTenantUuid(item.id) &&
            typeof item.name === "string" &&
            ["owner", "operator", "viewer"].includes(item.role),
        );
        setAuthorizedTenants(validItems);
        setTenantListError("");

        const savedId = tenantId.trim().toLowerCase();
        const saved = validItems.find(
          (item) => item.id.toLowerCase() === savedId,
        );

        if (saved) {
          setTenantId(saved.id);
        } else if (validItems.length === 1) {
          setTenantId(validItems[0].id);
        } else {
          setTenantId("");
          try {
            localStorage.removeItem("smartfarm.selectedTenantId");
          } catch {
            // Storage is optional.
          }
        }
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        setAuthorizedTenants([]);
        setTenantListError(
          error instanceof Error
            ? error.message
            : "ไม่สามารถโหลดรายการ Tenant จากเซิร์ฟเวอร์ได้",
        );
      })
      .finally(() => {
        if (!cancelled) setTenantListLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (
      (selectedPage !== "farms" && selectedPage !== "devices") ||
      tenantListLoading
    ) {
      setFarms([]);
      setFarmsError("");
      setFarmsRequested(false);
      setFarmsLoading(false);
      return;
    }

    const authorizedTenant = authorizedTenants.find(
      (item) =>
        item.id.toLowerCase() === tenantId.trim().toLowerCase(),
    );

    if (!authorizedTenant) {
      setFarms([]);
      setFarmsError("");
      setFarmsRequested(false);
      setFarmsLoading(false);
      return;
    }

    let cancelled = false;
    setFarms([]);
    setFarmsLoading(true);
    setFarmsError("");
    setFarmsRequested(true);

    farmApi.list(authorizedTenant.id)
      .then((result) => {
        if (cancelled) return;

        setFarms(result);
        try {
          localStorage.setItem(
            "smartfarm.selectedTenantId",
            authorizedTenant.id,
          );
        } catch {
          // Storage is optional.
        }
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        setFarms([]);
        setFarmsError(
          error instanceof ApiError
            ? error.message
            : "ไม่สามารถโหลดรายการฟาร์มได้ กรุณาลองใหม่",
        );
      })
      .finally(() => {
        if (!cancelled) setFarmsLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [
    selectedPage,
    tenantId,
    farmsReloadKey,
    authorizedTenants,
    tenantListLoading,
  ]);


  useEffect(() => {
    let cancelled = false;
    const objectUrls: string[] = [];
    const authorizedTenant = authorizedTenants.find(
      (item) => item.id.toLowerCase() === tenantId.trim().toLowerCase(),
    );

    const imageFarmIds = Array.from(
      new Set([
        ...farms.map((farm) => farm.id),
        ...(selectedFarm ? [selectedFarm.id] : []),
      ]),
    );

    if (tenantListLoading || !authorizedTenant || imageFarmIds.length === 0) {
      setFarmImageUrls({});
      return () => {
        cancelled = true;
      };
    }

    setFarmImageUrls({});
    void Promise.all(
      imageFarmIds.map(async (farmId) => {
        try {
          const blob = await farmApi.getImage(authorizedTenant.id, farmId);
          if (cancelled) return;
          if (!blob.type.startsWith("image/")) return;
          const url = URL.createObjectURL(blob);
          objectUrls.push(url);
          setFarmImageUrls((current) => ({ ...current, [farmId]: url }));
        } catch {
          // ฟาร์มที่ยังไม่มีรูปใช้ไอคอนเริ่มต้นแทน
        }
      }),
    );

    return () => {
      cancelled = true;
      objectUrls.forEach((url) => URL.revokeObjectURL(url));
    };
  }, [
    farms,
    selectedFarm?.id,
    tenantId,
    authorizedTenants,
    tenantListLoading,
    farmImageReloadKey,
  ]);

  useEffect(() => {
    let cancelled = false;
    const authorizedTenant = authorizedTenants.find(
      (item) => item.id.toLowerCase() === tenantId.trim().toLowerCase(),
    );
    const farmId = selectedFarm?.id;

    if (
      selectedPage !== "zones" ||
      tenantListLoading ||
      !authorizedTenant ||
      !farmId
    ) {
      setZones([]);
      setZonesError("");
      setZonesRequested(false);
      setZonesLoading(false);
      return;
    }

    setZones([]);
    setZonesError("");
    setZonesLoading(true);
    setZonesRequested(true);

    zoneApi.list(authorizedTenant.id, farmId, zoneSearch)
      .then((items) => {
        if (!cancelled) setZones(items);
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        setZones([]);
        setZonesError(
          error instanceof Error
            ? error.message
            : "ไม่สามารถโหลดรายการโซนได้",
        );
      })
      .finally(() => {
        if (!cancelled) setZonesLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [
    selectedPage,
    tenantId,
    selectedFarm?.id,
    zoneSearch,
    zonesReloadKey,
    authorizedTenants,
    tenantListLoading,
  ]);

  const authorizedDeviceTenant = authorizedTenants.find(
    (item) => item.id.toLowerCase() === tenantId.trim().toLowerCase(),
  );

  useEffect(() => {
    if (selectedPage !== "dashboard") return;

    if (tenantListLoading) return;

    if (!authorizedDeviceTenant) {
      setDashboardData(null);
      setDashboardError("");
      setDashboardLoading(false);
      return;
    }

    let cancelled = false;
    let inFlight = false;
    const requestedTenantId = authorizedDeviceTenant.id;

    // Clear previous tenant data immediately to prevent stale cross-tenant display.
    setDashboardData(null);
    setDashboardError("");

    const loadDashboard = async (showLoading = false) => {
      if (inFlight || cancelled) return;

      inFlight = true;
      if (showLoading) setDashboardLoading(true);

      try {
        const [farmItems, deviceItems] = await Promise.all([
          farmApi.list(requestedTenantId),
          deviceApi.list(requestedTenantId),
        ]);

        const zoneGroups = await Promise.all(
          farmItems.map((farm) =>
            zoneApi.list(requestedTenantId, farm.id),
          ),
        );

        if (cancelled) return;

        setDashboardData({
          farms: farmItems,
          devices: deviceItems,
          zones: zoneGroups.flat(),
        });
        setDashboardError("");
      } catch (error: unknown) {
        if (cancelled) return;

        setDashboardData(null);
        setDashboardError(
          error instanceof ApiError
            ? error.message
            : "ไม่สามารถโหลดข้อมูลภาพรวมฟาร์มได้",
        );
      } finally {
        inFlight = false;
        if (!cancelled && showLoading) {
          setDashboardLoading(false);
        }
      }
    };

    void loadDashboard(true);

    const refreshTimer = window.setInterval(() => {
      void loadDashboard();
    }, 30_000);

    return () => {
      cancelled = true;
      window.clearInterval(refreshTimer);
    };
  }, [
    selectedPage,
    authorizedDeviceTenant?.id,
    tenantListLoading,
  ]);

  useEffect(() => {
    if (selectedPage !== "dashboard") return;

    if (tenantListLoading) return;

    if (!authorizedDeviceTenant) {
      setDashboardReadings([]);
      setDashboardTelemetryError("");
      setDashboardTelemetryLoading(false);
      return;
    }

    let cancelled = false;
    let inFlight = false;
    const requestedTenantId = authorizedDeviceTenant.id;

    const rangeMilliseconds =
      selectedRange === "1 ชั่วโมง"
        ? 60 * 60 * 1000
        : selectedRange === "7 วัน"
          ? 7 * 24 * 60 * 60 * 1000
          : 24 * 60 * 60 * 1000;

    setDashboardReadings([]);
    setDashboardTelemetryError("");

    const loadDashboardTelemetry = async (showLoading = false) => {
      if (cancelled || inFlight) return;

      inFlight = true;
      if (showLoading) setDashboardTelemetryLoading(true);

      try {
        const until = new Date().toISOString();
        const since = new Date(Date.now() - rangeMilliseconds).toISOString();

        const readings = await telemetryApi.list(requestedTenantId, {
          since,
          until,
          limit: 500,
        });

        if (cancelled) return;

        setDashboardReadings(readings);
        setDashboardTelemetryError("");
      } catch (error: unknown) {
        if (cancelled) return;

        setDashboardTelemetryError(
          error instanceof ApiError
            ? error.message
            : "ไม่สามารถโหลดข้อมูลเซนเซอร์ย้อนหลังได้",
        );
      } finally {
        inFlight = false;
        if (!cancelled && showLoading) {
          setDashboardTelemetryLoading(false);
        }
      }
    };

    void loadDashboardTelemetry(true);

    const refreshTimer = window.setInterval(() => {
      void loadDashboardTelemetry();
    }, 30_000);

    return () => {
      cancelled = true;
      window.clearInterval(refreshTimer);
    };
  }, [
    selectedPage,
    authorizedDeviceTenant?.id,
    tenantListLoading,
    selectedRange,
  ]);

  useEffect(() => {
    if (selectedPage !== "devices") {
      return;
    }

    if (tenantListLoading) {
      return;
    }

    if (!authorizedDeviceTenant) {
      setDevices([]);
      setDevicesError("");
      setDevicesRequested(false);
      setDevicesLoading(false);
      setRelayReportedStates({});
      setRelayErrors({});
      setRelayMessages({});
      setCommandHistories({});
      setCommandHistoryErrors({});
      return;
    }

    let cancelled = false;
    const requestedTenantId = authorizedDeviceTenant.id;

    // Clear stale state before loading devices for the selected tenant.
    setRelayReportedStates({});
    setRelayErrors({});
    setRelayMessages({});
    setCommandHistories({});
    setCommandHistoryErrors({});
    setDevicesLoading(true);
    setDevicesError("");
    setDevicesRequested(true);

    deviceApi.list(requestedTenantId)
      .then((result) => {
        if (cancelled) return;

        setDevices(result);

        // Restore reported relay states from authorized command history.
        void Promise.all(
          result.map(async (device) => {
            try {
              const history = await commandApi.history(
                requestedTenantId,
                device.id,
                100,
              );
              return { device, history, error: "" };
            } catch (error) {
              return {
                device,
                history: null,
                error: error instanceof Error
                  ? error.message
                  : "โหลดประวัติคำสั่งไม่สำเร็จ",
              };
            }
          }),
        ).then((results) => {
          if (cancelled) return;

          const restoredStates: Record<
            string,
            "on" | "off" | "unknown"
          > = {};
          const restoredHistories: Record<string, DeviceCommand[]> = {};
          const restoredErrors: Record<string, string> = {};
          const restoredRelayErrors: Record<string, string> = {};

          for (const { device, history, error } of results) {
            if (history === null) {
              restoredErrors[device.id] = error;
              for (const relay of [1, 2, 3, 4]) {
                restoredStates[`${device.id}:${relay}`] = "unknown";
              }
              continue;
            }

            restoredHistories[device.id] = history.commands;

            for (const relay of [1, 2, 3, 4]) {
              const key = `${device.id}:${relay}`;
              // API history is newest-first. Do not fall back to an older
              // successful command if a newer command failed or is pending.
              const latestCommand = history.commands.find(
                (command) =>
                  command.command_type === "relay.set" &&
                  command.parameters?.relay === relay,
              );

              restoredStates[key] =
                latestCommand?.status === "succeeded" &&
                (latestCommand.parameters?.state === "on" ||
                  latestCommand.parameters?.state === "off")
                  ? latestCommand.parameters.state
                  : "unknown";

              restoredRelayErrors[key] =
                latestCommand &&
                ["failed", "expired"].includes(latestCommand.status)
                  ? `คำสั่ง Relay สิ้นสุดด้วยสถานะ ${latestCommand.status}`
                  : "";
            }
          }

          setRelayReportedStates(restoredStates);
          setRelayErrors(restoredRelayErrors);
          setCommandHistories(restoredHistories);
          setCommandHistoryErrors(restoredErrors);
        });

        try {
          localStorage.setItem(
            "smartfarm.selectedTenantId",
            requestedTenantId,
          );

          setTenantHistory((previous) => {
            const next = [
              requestedTenantId,
              ...previous.filter(
                (value) =>
                  value.toLowerCase() !== requestedTenantId.toLowerCase(),
              ),
            ].slice(0, 10);

            try {
              localStorage.setItem(
                "smartfarm.tenantHistory",
                JSON.stringify(next),
              );
            } catch {
              // Keep the current session usable if storage is unavailable.
            }

            return next;
          });
        } catch {
          // Keep the current session usable if storage is unavailable.
        }
      })
      .catch((error: unknown) => {
        if (cancelled) return;

        setDevices([]);
        setDevicesError(
          error instanceof ApiError
            ? error.message
            : "ไม่สามารถโหลดรายการอุปกรณ์ได้ กรุณาลองใหม่",
        );
      })
      .finally(() => {
        if (!cancelled) setDevicesLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [selectedPage, tenantId, selectedFarm?.id, authorizedTenants, tenantListLoading, devicesReloadKey]);

  // Refresh relay command history periodically while the device page is open.
  // This is read-only: it never sends commands to the ESP32.
  useEffect(() => {
    const requestedTenantId = authorizedDeviceTenant?.id;

    if (
      selectedPage !== "devices" ||
      tenantListLoading ||
      !requestedTenantId ||
      devicesLoading ||
      !devicesRequested ||
      devices.length === 0
    ) {
      return;
    }

    let cancelled = false;
    let refreshing = false;

    const refreshRelayHistory = async () => {
      if (refreshing || cancelled) return;
      refreshing = true;

      try {
        const results = await Promise.all(
          devices.map(async (device) => {
            try {
              const history = await commandApi.history(
                requestedTenantId,
                device.id,
                100,
              );
              return { device, history: history.commands, error: "" };
            } catch (error) {
              return {
                device,
                history: null,
                error: error instanceof Error
                  ? error.message
                  : "โหลดประวัติคำสั่งไม่สำเร็จ",
              };
            }
          }),
        );

        if (
          cancelled ||
          tenantContextRef.current !== requestedTenantId
        ) {
          return;
        }

        for (const result of results) {
          const deviceId = result.device.id;

          if (result.history === null) {
            setCommandHistoryErrors((previous) => ({
              ...previous,
              [deviceId]: result.error,
            }));
            continue;
          }

          const history = result.history;

          setCommandHistories((previous) => ({
            ...previous,
            [deviceId]: history,
          }));
          setCommandHistoryErrors((previous) => ({
            ...previous,
            [deviceId]: "",
          }));

          setRelayReportedStates((previous) => {
            const next = { ...previous };

            for (const relay of [1, 2, 3, 4]) {
              const key = `${deviceId}:${relay}`;
              const latest = history.find(
                (command) =>
                  command.command_type === "relay.set" &&
                  command.parameters?.relay === relay,
              );

              next[key] =
                latest?.status === "succeeded" &&
                (latest.parameters?.state === "on" ||
                  latest.parameters?.state === "off")
                  ? latest.parameters.state
                  : "unknown";
            }

            return next;
          });

          setRelayErrors((previous) => {
            const next = { ...previous };

            for (const relay of [1, 2, 3, 4]) {
              const key = `${deviceId}:${relay}`;
              const latest = history.find(
                (command) =>
                  command.command_type === "relay.set" &&
                  command.parameters?.relay === relay,
              );

              next[key] =
                latest && ["failed", "expired"].includes(latest.status)
                  ? `คำสั่ง Relay สิ้นสุดด้วยสถานะ ${latest.status}`
                  : "";
            }

            return next;
          });
        }
      } finally {
        refreshing = false;
      }
    };

    // Start after the initial device/history restoration to avoid racing it.
    const timer = window.setInterval(
      () => void refreshRelayHistory(),
      10_000,
    );

    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [
    selectedPage,
    tenantListLoading,
    authorizedDeviceTenant?.id,
    devicesLoading,
    devicesRequested,
    devices,
  ]);

  useEffect(() => {
    if (selectedPage !== "devices" || tenantListLoading) {
      return;
    }

    if (!authorizedDeviceTenant) {
      setDeviceZonesByFarm({});
      setDeviceZoneLoading({});
      setDeviceZoneLoadErrors({});
      return;
    }

    const requestedTenantId = authorizedDeviceTenant.id;
    const farmIds = [...new Set(
      devices
        .map((device) => device.farm_id)
        .filter((farmId): farmId is string => Boolean(farmId)),
    )];

    let cancelled = false;
    setDeviceZoneLoading(Object.fromEntries(farmIds.map((id) => [id, true])));
    setDeviceZoneLoadErrors({});

    void Promise.all(
      farmIds.map(async (farmId) => {
        try {
          const result = await zoneApi.list(requestedTenantId, farmId);
          return { farmId, zones: result, error: "" };
        } catch (error) {
          return {
            farmId,
            zones: [] as Zone[],
            error: error instanceof Error
              ? error.message
              : "โหลดรายการ Zone ไม่สำเร็จ",
          };
        }
      }),
    ).then((results) => {
      if (cancelled || tenantContextRef.current !== requestedTenantId) return;

      const nextZones: Record<string, Zone[]> = {};
      const nextErrors: Record<string, string> = {};
      const nextLoading: Record<string, boolean> = {};

      for (const result of results) {
        nextZones[result.farmId] = result.zones;
        nextLoading[result.farmId] = false;
        if (result.error) nextErrors[result.farmId] = result.error;
      }

      setDeviceZonesByFarm(nextZones);
      setDeviceZoneLoadErrors(nextErrors);
      setDeviceZoneLoading(nextLoading);
    });

    return () => {
      cancelled = true;
    };
  }, [selectedPage, tenantListLoading, authorizedDeviceTenant, devices]);

  useEffect(() => {
    if (selectedPage !== "devices" || tenantListLoading) {
      return;
    }

    if (!authorizedDeviceTenant) {
      setTelemetryReadings([]);
      setTelemetryError("");
      setTelemetryRequested(false);
      setTelemetryLoading(false);
      return;
    }

    let cancelled = false;
    let inFlight = false;
    const requestedTenantId = authorizedDeviceTenant.id;

    setTelemetryReadings([]);
    setTelemetryLoading(true);
    setTelemetryError("");
    setTelemetryRequested(true);

    const loadTelemetry = async (showLoading = false) => {
      if (cancelled || inFlight) return;

      inFlight = true;
      if (showLoading) setTelemetryLoading(true);

      try {
        const result = await telemetryApi.list(
          requestedTenantId,
          { latest_only: true, limit: 100 },
        );

        if (cancelled) return;
        setTelemetryReadings(result);
        setTelemetryError("");
      } catch (error: unknown) {
        if (cancelled) return;
        setTelemetryError(
          error instanceof ApiError
            ? error.message
            : "ไม่สามารถโหลดค่าเซนเซอร์ได้ กรุณาลองใหม่",
        );
      } finally {
        inFlight = false;
        if (!cancelled && showLoading) setTelemetryLoading(false);
      }
    };

    void loadTelemetry(true);

    const refreshTimer = window.setInterval(() => {
      void loadTelemetry();
    }, 30_000);

    return () => {
      cancelled = true;
      window.clearInterval(refreshTimer);
    };
  }, [selectedPage, authorizedDeviceTenant?.id, tenantListLoading, telemetryReloadKey]);

  const dashboardNow = Date.now();

  const dashboardDevices = dashboardData?.devices ?? [];

  const selectedDashboardFarm =
    dashboardData?.farms.find((farm) => farm.id === selectedDashboardFarmId) ??
    dashboardData?.farms[0] ??
    null;

  const selectedDashboardFarmIdEffective = selectedDashboardFarm?.id ?? "";


  useEffect(() => {
    if (selectedPage !== "dashboard") {
      setDashboardWeather(null);
      setDashboardWeatherError("");
      setDashboardWeatherLoading(false);
      return;
    }

    if (!authorizedDeviceTenant || !selectedDashboardFarm) {
      setDashboardWeather(null);
      setDashboardWeatherError("");
      setDashboardWeatherLoading(false);
      return;
    }

    if (
      selectedDashboardFarm.latitude === null ||
      selectedDashboardFarm.longitude === null
    ) {
      setDashboardWeather(null);
      setDashboardWeatherError("กรุณากำหนด Latitude และ Longitude ให้ฟาร์มนี้ก่อน");
      setDashboardWeatherLoading(false);
      return;
    }

    let cancelled = false;
    setDashboardWeather(null);
    setDashboardWeatherError("");
    setDashboardWeatherLoading(true);

    weatherApi
      .get(authorizedDeviceTenant.id, selectedDashboardFarm.id)
      .then((weather) => {
        if (cancelled) return;
        setDashboardWeather(weather);
        setDashboardWeatherError("");
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        setDashboardWeather(null);
        setDashboardWeatherError(
          error instanceof ApiError
            ? error.message
            : "ไม่สามารถโหลดข้อมูลสภาพอากาศได้",
        );
      })
      .finally(() => {
        if (!cancelled) setDashboardWeatherLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [
    selectedPage,
    authorizedDeviceTenant?.id,
    selectedDashboardFarm?.id,
    selectedDashboardFarm?.latitude,
    selectedDashboardFarm?.longitude,
  ]);


  useEffect(() => {
    if (
      selectedPage !== "dashboard" ||
      !authorizedDeviceTenant ||
      !selectedDashboardFarm
    ) {
      setDashboardAirPollution(null);
      setDashboardAirPollutionError("");
      setDashboardAirPollutionLoading(false);
      return;
    }

    if (
      selectedDashboardFarm.latitude === null ||
      selectedDashboardFarm.longitude === null
    ) {
      setDashboardAirPollution(null);
      setDashboardAirPollutionError(
        "กรุณากำหนดพิกัดฟาร์มก่อนดูข้อมูล PM2.5",
      );
      setDashboardAirPollutionLoading(false);
      return;
    }

    let cancelled = false;
    setDashboardAirPollution(null);
    setDashboardAirPollutionError("");
    setDashboardAirPollutionLoading(true);

    airPollutionApi
      .get(authorizedDeviceTenant.id, selectedDashboardFarm.id)
      .then((air) => {
        if (cancelled) return;
        setDashboardAirPollution(air);
        setDashboardAirPollutionError("");
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        setDashboardAirPollution(null);
        setDashboardAirPollutionError(
          error instanceof ApiError
            ? error.message
            : "ไม่สามารถโหลดข้อมูล PM2.5 ได้",
        );
      })
      .finally(() => {
        if (!cancelled) setDashboardAirPollutionLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [
    selectedPage,
    authorizedDeviceTenant?.id,
    selectedDashboardFarm?.id,
    selectedDashboardFarm?.latitude,
    selectedDashboardFarm?.longitude,
  ]);

  const selectedDashboardFarmZones = (dashboardData?.zones ?? []).filter(
    (zone) => zone.farm_id === selectedDashboardFarmIdEffective,
  );

  const selectedDashboardFarmDevices = dashboardDevices.filter(
    (device) => device.farm_id === selectedDashboardFarmIdEffective,
  );

  const selectedDashboardFarmOnlineDevices = selectedDashboardFarmDevices.filter(
    (device) => isDeviceRecentlyOnline(device, dashboardNow),
  ).length;
  const selectedDashboardZones = (dashboardData?.zones ?? []).filter(
    (zone) => zone.farm_id === selectedDashboardFarmIdEffective,
  );

  const selectedDashboardChartZone =
    selectedDashboardFarmZones.find(
      (zone) => zone.id === selectedDashboardZoneId,
    ) ??
    selectedDashboardFarmZones[0] ??
    null;

  const selectedDashboardChartZoneId = selectedDashboardChartZone?.id ?? "";

  const selectedDashboardStatusZoneIdEffective =
    selectedDashboardFarmZones.some(
      (zone) => zone.id === selectedDashboardStatusZoneId,
    )
      ? selectedDashboardStatusZoneId
      : selectedDashboardFarmZones[0]?.id ?? "";

  const selectedDashboardStatusZoneDeviceIds = new Set(
    selectedDashboardFarmDevices
      .filter(
        (device) => device.zone_id === selectedDashboardStatusZoneIdEffective
      )
      .map((device) => device.id),
  );

  const selectedDashboardZoneDeviceIds = new Set(
    dashboardDevices
      .filter((device) =>
        device.zone_id === selectedDashboardChartZoneId &&
        device.farm_id === selectedDashboardFarmIdEffective
      )
      .map((device) => device.id),
  );

  const getDashboardLatestSensorReading = (aliases: string[]) =>
    dashboardReadings
      .filter((reading) =>
        selectedDashboardStatusZoneDeviceIds.has(reading.device_id) &&
        reading.quality_status.trim().toLowerCase() === "valid" &&
        Number.isFinite(Number(reading.value)) &&
        Number.isFinite(Date.parse(reading.measured_at)) &&
        aliases.includes(reading.metric.trim().toLowerCase())
      )
      .sort(
        (a, b) =>
          Date.parse(b.measured_at) - Date.parse(a.measured_at),
      )[0] ?? null;

  const dashboardLatestTemperature =
    getDashboardLatestSensorReading(["temperature", "air_temperature"]);

  const dashboardLatestHumidity =
    getDashboardLatestSensorReading(["humidity", "air_humidity"]);

  const dashboardGatewayDevices = dashboardDevices.filter(
    (device) => device.device_type.trim().toLowerCase() === "gateway",
  );

  const dashboardOnlineGateways = dashboardData
    ? dashboardGatewayDevices.filter((device) =>
        isDeviceRecentlyOnline(device, dashboardNow),
      ).length
    : null;

  const dashboardMetricValues = [
    dashboardData ? dashboardGatewayDevices.length : null,
    null,
  ];

  const dashboardMetricAliases: Record<string, string[]> = {
    "อุณหภูมิ": ["temperature", "air_temperature"],
    "ความชื้นอากาศ": ["humidity", "air_humidity"],
    "ความชื้นดิน": ["soil_moisture"],
    "VPD": ["vpd"],
  };

  const dashboardValidReadings = dashboardReadings
    .filter((reading) =>
      reading.quality_status.trim().toLowerCase() === "valid" &&
      Number.isFinite(Number(reading.value)) &&
      Number.isFinite(Date.parse(reading.measured_at))
    )
    .filter((reading) =>
      selectedDashboardZoneDeviceIds.has(reading.device_id)
    )
    .filter((reading) =>
      (dashboardMetricAliases[selectedVariable] ?? []).includes(
        reading.metric.trim().toLowerCase(),
      )
    )
    .sort(
      (a, b) =>
        Date.parse(a.measured_at) - Date.parse(b.measured_at),
    );

  const dashboardChartReadings = dashboardValidReadings.slice(-60);
  const dashboardChartValues = dashboardChartReadings.map(
    (reading) => Number(reading.value),
  );
  const dashboardChartMin = dashboardChartValues.length
    ? Math.min(...dashboardChartValues)
    : 0;
  const dashboardChartMax = dashboardChartValues.length
    ? Math.max(...dashboardChartValues)
    : 0;
  const dashboardChartSpan =
    dashboardChartMax - dashboardChartMin || 1;

  const dashboardChartPoints = dashboardChartReadings.map(
    (reading, index) => ({
      x: dashboardChartReadings.length <= 1
        ? 300
        : 20 + (index / (dashboardChartReadings.length - 1)) * 560,
      y: 165 - (
        (Number(reading.value) - dashboardChartMin) /
        dashboardChartSpan
      ) * 130,
      reading,
    }),
  );

  const dashboardLatestReading =
    dashboardValidReadings[dashboardValidReadings.length - 1] ?? null;


  useEffect(() => {
    if (selectedPage !== "sensors" || tenantListLoading) return;

    if (!authorizedDeviceTenant) {
      setSensorDevices([]);
      setSensors([]);
      setSensorsError("ไม่พบ Tenant ที่ได้รับอนุญาต");
      setSensorsLoading(false);
      return;
    }

    let cancelled = false;
    const tenant = authorizedDeviceTenant.id;
    setSensorsLoading(true);
    setSensorsError("");

    void (async () => {
      try {
        const loadedDevices = await deviceApi.list(tenant);
        const results = await Promise.all(
          loadedDevices.map(async (device) => ({
            device,
            sensors: await sensorApi.list(tenant, device.id),
          })),
        );

        if (cancelled) return;

        setSensorDevices(loadedDevices);
        setSensors(results.flatMap((result) => result.sensors));
        setSensorFormDeviceId((current) =>
          loadedDevices.some((device) => device.id === current)
            ? current
            : loadedDevices[0]?.id ?? "",
        );
      } catch (error) {
        if (cancelled) return;
        setSensorsError(error instanceof Error ? error.message : "โหลด Sensor ไม่สำเร็จ");
      } finally {
        if (!cancelled) setSensorsLoading(false);
      }
    })();

    return () => { cancelled = true; };
  }, [selectedPage, tenantListLoading, authorizedDeviceTenant?.id, sensorReloadKey]);

  const page = pageTitles[selectedPage] ?? pageTitles.dashboard;

  // The shared top bar reports only API loading outcomes that this page tracks.
  const topbarDataStatus =
    selectedPage === "farms"
      ? farmsLoading
        ? { label: "กำลังโหลดข้อมูล", tone: "loading" }
        : farmsError
          ? { label: "โหลดข้อมูลไม่สำเร็จ", tone: "error" }
          : farmsRequested
            ? { label: "โหลดข้อมูลสำเร็จ", tone: "success" }
            : { label: "ยังไม่มีผลตรวจสอบข้อมูล", tone: "unknown" }
      : selectedPage === "devices"
        ? devicesLoading
          ? { label: "กำลังโหลดข้อมูล", tone: "loading" }
          : devicesError
            ? { label: "โหลดข้อมูลไม่สำเร็จ", tone: "error" }
            : devicesRequested
              ? { label: "โหลดข้อมูลสำเร็จ", tone: "success" }
              : { label: "ยังไม่มีผลตรวจสอบข้อมูล", tone: "unknown" }
        : { label: "ยังไม่มีผลตรวจสอบข้อมูล", tone: "unknown" };

  function navigate(id: string) {
    setSelectedPage(id);
    setMobileMenuOpen(false);
  }

  return (
    <div className="app-shell">
      <aside className={`sidebar ${mobileMenuOpen ? "sidebar-open" : ""}`}>
        <a
          className="brand"
          href="#dashboard"
          onClick={(event) => {
            event.preventDefault();
            navigate("dashboard");
          }}
        >
          <span className="brand-mark" aria-hidden="true">SF</span>
          <span className="brand-copy">
            <strong>Smart Farm</strong>
            <small>System V.1</small>
          </span>
        </a>

        <div className="sidebar-context">
          <span className="context-icon">⌂</span>
          <span>
            <strong>พื้นที่ทำงาน</strong>
            <small>ภาพรวมระบบ</small>
          </span>
          <span className="context-chevron">⌄</span>
        </div>

        <nav className="side-navigation" aria-label="เมนูหลัก">
          {navigation.map((group) => (
            <div className="nav-group" key={group.title}>
              <p className="nav-heading">{group.title}</p>
              {group.items.map((item) => (
                <button
                  className={`nav-item ${
                    selectedPage === item.id ? "active" : ""
                  }`}
                  key={item.id}
                  type="button"
                  aria-current={selectedPage === item.id ? "page" : undefined}
                  onClick={() => navigate(item.id)}
                >
                  <span className="nav-icon" aria-hidden="true">{item.icon}</span>
                  <span>{item.label}</span>
                  {item.id === "alerts" && (
                    <span className="nav-count" aria-label="ยังไม่มีข้อมูล">
                      —
                    </span>
                  )}
                </button>
              ))}
            </div>
          ))}
        </nav>

        <div className="sidebar-footer">
          <span className="footer-status-dot" />
          <span>
            <strong>Smart Farm System</strong>
            <small>ยังไม่เชื่อมต่อข้อมูลจริง</small>
          </span>
        </div>
      </aside>

      {mobileMenuOpen && (
        <button
          className="sidebar-backdrop"
          type="button"
          aria-label="ปิดเมนู"
          onClick={() => setMobileMenuOpen(false)}
        />
      )}

      <main className="main-panel">
        <header className="topbar">
          <div className="topbar-left">
            <button
              className="mobile-menu-button"
              type="button"
              aria-label="เปิดเมนู"
              aria-expanded={mobileMenuOpen}
              onClick={() => setMobileMenuOpen((open) => !open)}
            >
              ☰
            </button>
            <div className="breadcrumb">
              <span>Smart Farm</span>
              <span className="breadcrumb-separator">/</span>
              <strong>{page.title}</strong>
            </div>
          </div>

          <div className="topbar-actions">
            <span
              className={`connection-pill connection-pill-${topbarDataStatus.tone}`}
              role="status"
              aria-live="polite"
            >
              <span className={`status-dot ${
                topbarDataStatus.tone === "success"
                  ? "status-dot-success"
                  : "status-dot-muted"
              }`} />
              {topbarDataStatus.label}
            </span>
            <button
              className="icon-button notification-button"
              type="button"
              aria-label="ไปยังการแจ้งเตือน"
              onClick={() => navigate("alerts")}
            >
              ♧
            </button>
            <button
              className="profile-button"
              type="button"
              onClick={() => navigate("settings")}
              aria-label="ผู้ใช้และการตั้งค่า"
            >
              <span className="profile-avatar">SF</span>
              <span className="profile-copy">
                <strong>บัญชีผู้ใช้</strong>
                <small>การตั้งค่า</small>
              </span>
              <span className="profile-chevron">⌄</span>
            </button>
          </div>
        </header>

        <div className="page-content">
          <section className="page-heading">
            <div>
              <p className="eyebrow">SMART FARM MANAGEMENT</p>
              <h1>{page.title}</h1>
              <p className="page-description">{page.description}</p>
            </div>
            <span className="date-chip">
              <span aria-hidden="true">◷</span>
              ยังไม่มีเวลาข้อมูลล่าสุด
            </span>
          </section>

          {selectedPage === "dashboard" ? (
            <>
              <section className="section-block">
                <div className="section-heading">
                  <div>
                    <h2>สภาพอากาศภายนอก</h2>
                    <p>ข้อมูลสภาพอากาศจากแหล่งข้อมูลที่เชื่อมต่อ</p>
                  </div>
                  <span className="source-label">External weather</span>
                </div>

                <div className="weather-panel">
                  <div className="weather-summary">
                    <span className="weather-icon" aria-hidden="true">☁</span>
                    <div>
                      <strong>
                        {dashboardWeather ? dashboardWeather.temperature.toFixed(1) : "—"} <small>°C</small>
                      </strong>
                      <span>
                        {dashboardWeatherLoading
                          ? "กำลังโหลดสภาพอากาศ..."
                          : dashboardWeather
                            ? dashboardWeather.description
                            : dashboardWeatherError || "ยังไม่มีข้อมูลสภาพอากาศ"}
                      </span>
                    </div>
                  </div>
                  <div className="weather-detail-grid">
                    {[
                      ["ความชื้นสัมพัทธ์", "%", "◌"],
                      ["อุณหภูมิที่รู้สึกได้", "°C", "♨"],
                      ["ความเร็วลม", "m/s", "↝"],
                      ["ทิศทางลม", "", "⌖"],
                    ].map(([label, unit, icon]) => (
                      <div className="weather-detail" key={label}>
                        <span className="weather-detail-icon">{icon}</span>
                        <span className="weather-detail-copy">
                          <small>{label}</small>
                          <strong>
                            {dashboardWeather
                              ? (
                                  label === "ความชื้นสัมพัทธ์"
                                    ? dashboardWeather.humidity
                                    : label === "อุณหภูมิที่รู้สึกได้"
                                      ? dashboardWeather.feels_like.toFixed(1)
                                      : label === "ความเร็วลม"
                                        ? dashboardWeather.wind_speed.toFixed(1)
                                        : dashboardWeather.wind_deg === null
                                          ? "—"
                                          : `${dashboardWeather.wind_deg}°`
                                )
                              : "—"} <small>{unit}</small>
                          </strong>
                        </span>
                      </div>
                    ))}
                  </div>
                  <div className="weather-air-quality" aria-live="polite">
                    <span className="weather-detail-icon" aria-hidden="true">◉</span>
                    <div className="weather-air-quality-copy">
                      <small>ฝุ่น PM2.5</small>
                      <strong>
                        {dashboardAirPollution
                          ? dashboardAirPollution.pm2_5.toFixed(2)
                          : "—"} <small>µg/m³</small>
                      </strong>
                      <span>
                        {dashboardAirPollutionLoading
                          ? "กำลังโหลดข้อมูลคุณภาพอากาศ..."
                          : dashboardAirPollution
                            ? `AQI ${dashboardAirPollution.aqi} · ${dashboardAirPollution.aqi_label}`
                            : dashboardAirPollutionError || "ยังไม่มีข้อมูล PM2.5"}
                      </span>
                    </div>
                  </div>
                </div>
              </section>

              <section className="section-block">
                <div className="section-heading">
                  <div>
                    <h2>สถานะฟาร์ม</h2>
                    <p>สรุปสถานะจากข้อมูลที่ระบบได้รับ</p>
                  </div>
                  <span className="section-note">
                    <span
                      className={`status-dot ${
                        dashboardError || !dashboardData
                          ? "status-dot-muted"
                          : ""
                      }`}
                    />
                    {dashboardLoading && !dashboardData
                      ? "กำลังโหลดข้อมูล"
                      : dashboardError
                        ? "โหลดข้อมูลไม่สำเร็จ"
                        : dashboardData
                          ? "เชื่อมต่อข้อมูลจริงแล้ว"
                          : "รอเลือก Tenant"}
                  </span>
                </div>

                <div className="farm-status-panel">
                  <label className="select-wrap">
                    <span className="sr-only">เลือกฟาร์มสำหรับดูสถานะ</span>
                    <select
                      value={selectedDashboardFarmIdEffective}
                      onChange={(event) =>
                        setSelectedDashboardFarmId(event.target.value)
                      }
                      disabled={!dashboardData?.farms.length}
                    >
                      {(dashboardData?.farms ?? []).map((farm) => (
                        <option key={farm.id} value={farm.id}>
                          {farm.name}
                        </option>
                      ))}
                    </select>
                  </label>

                  <label className="select-wrap farm-status-zone-select">
                    <span className="sr-only">เลือกโซนสำหรับดูสถานะฟาร์ม</span>
                    <select
                      value={selectedDashboardStatusZoneIdEffective}
                      onChange={(event) =>
                        setSelectedDashboardStatusZoneId(event.target.value)
                      }
                      disabled={!selectedDashboardFarmZones.length}
                    >
                      {selectedDashboardFarmZones.map((zone) => (
                        <option key={zone.id} value={zone.id}>
                          {zone.name}
                        </option>
                      ))}
                    </select>
                  </label>

                  {selectedDashboardFarm ? (
                    <div className="farm-selected-summary">
                      <div className="farm-selected-summary-heading">
                        <strong>{selectedDashboardFarm.name}</strong>
                        <span>สรุปข้อมูลฟาร์มที่เลือก</span>
                      </div>
                      <div className="farm-status-counts">
                        <div>
                          <strong>{selectedDashboardFarmZones.length}</strong>
                          <span>โซน</span>
                        </div>
                        <div>
                          <strong>{selectedDashboardFarmDevices.length}</strong>
                          <span>อุปกรณ์</span>
                        </div>
                      </div>
                      <p>
                        ออนไลน์ {selectedDashboardFarmOnlineDevices} จาก{" "}
                        {selectedDashboardFarmDevices.length} อุปกรณ์
                      </p>
                    </div>
                  ) : null}
                </div>

                <div className="metric-grid">
                  {metrics.map((metric, index) => {
                    const value = dashboardMetricValues[index];

                    return (
                      <article className="metric-card" key={metric.label}>
                        <div className="metric-card-top">
                          <span className="metric-icon" aria-hidden="true">
                            {metric.icon}
                          </span>
                          <span className="metric-more" aria-hidden="true">···</span>
                        </div>
                        <p className="metric-label">{metric.label}</p>
                        <div className="metric-value-row">
                          <strong>
                            {dashboardLoading && !dashboardData
                              ? "…"
                              : value === null
                                ? "—"
                                : value}
                          </strong>
                          <span>{metric.unit}</span>
                        </div>
                        <p className="metric-footnote">
                          {dashboardLoading && !dashboardData
                            ? "กำลังโหลดข้อมูล"
                            : dashboardError
                              ? "โหลดข้อมูลไม่สำเร็จ"
                              : index === 1
                                ? "รอเชื่อมต่อ Alerts API"
                                : dashboardData
                                  ? `ออนไลน์ ${dashboardOnlineGateways ?? 0} Gateway · อัปเดตทุก 30 วินาที`
                                  : "รอข้อมูลจากระบบ"}
                        </p>
                      </article>
                    );
                  })}
                </div>

                <div className="dashboard-sensor-grid">
                  {[
                    {
                      label: "อุณหภูมิภายในฟาร์ม",
                      icon: "🌡",
                      reading: dashboardLatestTemperature,
                      unit: "°C",
                    },
                    {
                      label: "ความชื้นอากาศภายในฟาร์ม",
                      icon: "💧",
                      reading: dashboardLatestHumidity,
                      unit: "%",
                    },
                  ].map((sensor) => (
                    <article className="metric-card" key={sensor.label}>
                      <div className="metric-card-top">
                        <span className="metric-icon" aria-hidden="true">
                          {sensor.icon}
                        </span>
                        <span className="metric-more" aria-hidden="true">●</span>
                      </div>
                      <p className="metric-label">{sensor.label}</p>
                      <div className="metric-value-row">
                        <strong>
                          {sensor.reading
                            ? Number(sensor.reading.value).toLocaleString(
                                "th-TH",
                                { maximumFractionDigits: 2 },
                              )
                            : "—"}
                        </strong>
                        <span>{sensor.reading?.unit ?? sensor.unit}</span>
                      </div>
                      <p className="metric-footnote">
                        {dashboardTelemetryLoading && !sensor.reading
                          ? "กำลังโหลดข้อมูลเซนเซอร์..."
                          : dashboardTelemetryError
                            ? "โหลดข้อมูลไม่สำเร็จ"
                            : sensor.reading
                              ? `อัปเดต ${new Date(
                                  sensor.reading.measured_at,
                                ).toLocaleString("th-TH")}`
                              : "ยังไม่มีข้อมูลในโซนนี้"}
                      </p>
                    </article>
                  ))}
                </div>
              </section>



              <section className="section-block">
                <div className="section-heading">
                  <div>
                    <h2>ภาพรวมโซนเพาะปลูก</h2>
                    <p>เลือกโซนเพื่อดูค่าเซนเซอร์และอุปกรณ์ที่เกี่ยวข้อง</p>
                  </div>
                </div>

                {dashboardLoading && !dashboardData ? (
                  <div className="zone-empty-panel">
                    <strong>กำลังโหลดข้อมูลโซน...</strong>
                  </div>
                ) : dashboardError ? (
                  <div className="zone-empty-panel">
                    <h3>โหลดข้อมูลโซนไม่สำเร็จ</h3>
                    <p>{dashboardError}</p>
                  </div>
                ) : dashboardData && selectedDashboardZones.length > 0 ? (
                  <div className="dashboard-zone-grid">
                    {selectedDashboardZones.map((zone) => {
                      const farm = dashboardData.farms.find(
                        (item) => item.id === zone.farm_id,
                      );

                      return (
                        <article className="dashboard-zone-card" key={zone.id}>
                          <div className="dashboard-zone-card-top">
                            <span className="dashboard-zone-icon" aria-hidden="true">
                              {zone.zone_type === "fish_pond"
                                ? "◉"
                                : zone.zone_type === "livestock"
                                  ? "♧"
                                  : zone.zone_type === "cctv"
                                    ? "◎"
                                    : "♣"}
                            </span>
                            <span className={
                              zone.status === "active"
                                ? "dashboard-zone-status active"
                                : "dashboard-zone-status"
                            }>
                              {zone.status === "active" ? "ใช้งาน" : "ปิดใช้งาน"}
                            </span>
                          </div>
                          <h3>{zone.name}</h3>
                          <p className="dashboard-zone-farm">
                            ฟาร์ม: {farm?.name ?? "ไม่พบข้อมูลฟาร์ม"}
                          </p>
                          <p className="dashboard-zone-type">
                            {zoneTypeLabels[zone.zone_type]}
                          </p>
                          {zone.description ? (
                            <p className="dashboard-zone-description">
                              {zone.description}
                            </p>
                          ) : null}
                        </article>
                      );
                    })}
                  </div>
                ) : (
                  <div className="zone-empty-panel">
                    <div className="empty-illustration" aria-hidden="true">
                      <span>♧</span>
                    </div>
                    <h3>
                      {selectedDashboardFarm
                        ? "ฟาร์มนี้ยังไม่มีข้อมูลโซน"
                        : "ยังไม่มีข้อมูลโซน"}
                    </h3>
                    <p>เพิ่มโซนในฟาร์มที่เลือกเพื่อเริ่มติดตามข้อมูลพื้นที่เพาะปลูก</p>
                    <button
                      className="secondary-button"
                      type="button"
                      onClick={() => navigate("zones")}
                    >
                      ไปยัง Zone Management
                    </button>
                  </div>
                )}
              </section>

              <div className="dashboard-lower-grid">
                <section className="section-block chart-panel">
                  <div className="section-heading">
                    <div>
                      <h2>แนวโน้มสภาพแวดล้อม</h2>
                      <p>กราฟจะปรากฏเมื่อมีข้อมูลย้อนหลัง</p>
                    </div>
                  </div>

                  <div className="chart-toolbar">
                    <label className="select-wrap">
                      <span className="sr-only">เลือกโซนสำหรับกราฟ</span>
                      <select
                        value={selectedDashboardChartZoneId}
                        onChange={(event) => setSelectedDashboardZoneId(event.target.value)}
                        disabled={!selectedDashboardFarmZones.length}
                      >
                        {!selectedDashboardFarmZones.length ? (
                          <option value="">ยังไม่มีโซนในฟาร์มนี้</option>
                        ) : null}
                        {selectedDashboardFarmZones.map((zone) => (
                          <option key={zone.id} value={zone.id}>
                            {zone.name}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label className="select-wrap">
                      <span className="sr-only">ตัวแปรที่ต้องการดู</span>
                      <select
                        value={selectedVariable}
                        onChange={(event) => setSelectedVariable(event.target.value)}
                      >
                        <option>อุณหภูมิ</option>
                        <option>ความชื้นอากาศ</option>
                        <option>ความชื้นดิน</option>
                        <option>VPD</option>
                      </select>
                    </label>
                    <div className="range-switch" aria-label="ช่วงเวลา">
                      {["1 ชั่วโมง", "24 ชั่วโมง", "7 วัน"].map((range) => (
                        <button
                          className={selectedRange === range ? "selected" : ""}
                          key={range}
                          type="button"
                          onClick={() => setSelectedRange(range)}
                          aria-pressed={selectedRange === range}
                        >
                          {range}
                        </button>
                      ))}
                    </div>
                  </div>

                  <div className="chart-empty dashboard-chart">
                    <div className="chart-grid-lines" aria-hidden="true">
                      <span /><span /><span /><span />
                    </div>
                    {dashboardTelemetryLoading && dashboardReadings.length === 0 ? (
                      <div className="chart-empty-content">
                        <strong>กำลังโหลดข้อมูลเซนเซอร์...</strong>
                        <small>{selectedVariable} · {selectedRange}</small>
                      </div>
                    ) : dashboardTelemetryError ? (
                      <div className="chart-empty-content">
                        <strong>โหลดข้อมูลกราฟไม่สำเร็จ</strong>
                        <small>{dashboardTelemetryError}</small>
                      </div>
                    ) : dashboardChartPoints.length > 0 ? (
                      <>
                        <div className="dashboard-chart-summary">
                          <strong>
                            {dashboardLatestReading
                              ? `${Number(dashboardLatestReading.value).toLocaleString(
                                  "th-TH",
                                  { maximumFractionDigits: 2 },
                                )} ${dashboardLatestReading.unit}`
                              : "—"}
                          </strong>
                          <small>
                            ค่าล่าสุด · {dashboardLatestReading
                              ? new Date(dashboardLatestReading.measured_at).toLocaleString("th-TH")
                              : ""}
                          </small>
                        </div>
                        <svg
                          className="dashboard-chart-svg"
                          viewBox="0 0 600 190"
                          role="img"
                          aria-label={`กราฟ${selectedVariable}ย้อนหลัง ${selectedRange}`}
                          preserveAspectRatio="none"
                        >
                          {dashboardChartPoints.length > 1 ? (
                            <polyline
                              points={dashboardChartPoints
                                .map((point) => `${point.x},${point.y}`)
                                .join(" ")}
                              fill="none"
                              stroke="var(--sf-brand-strong)"
                              strokeWidth="3"
                              strokeLinecap="round"
                              strokeLinejoin="round"
                            />
                          ) : null}
                          {dashboardChartPoints.map((point) => (
                            <circle
                              key={point.reading.id}
                              cx={point.x}
                              cy={point.y}
                              r="3.5"
                              fill="var(--sf-brand-strong)"
                            />
                          ))}
                        </svg>
                        <div className="dashboard-chart-footer">
                          <span>
                            {dashboardChartReadings.length} จุดข้อมูล
                          </span>
                          <span>
                            ช่วงค่า {dashboardChartMin.toLocaleString("th-TH", {
                              maximumFractionDigits: 2,
                            })} – {dashboardChartMax.toLocaleString("th-TH", {
                              maximumFractionDigits: 2,
                            })}
                          </span>
                        </div>
                      </>
                    ) : (
                      <div className="chart-empty-content">
                        <span className="chart-empty-icon" aria-hidden="true">⌁</span>
                        <strong>ยังไม่มีข้อมูลที่ใช้แสดงกราฟ</strong>
                        <span>{selectedVariable} · {selectedRange}</span>
                        <small>
                          ไม่พบข้อมูลที่ผ่านการตรวจสอบในช่วงเวลานี้
                        </small>
                      </div>
                    )}
                  </div>
                </section>

                <section className="section-block alerts-panel">
                  <div className="section-heading">
                    <div>
                      <h2>การแจ้งเตือนล่าสุด</h2>
                      <p>ติดตามเหตุการณ์จากระบบ</p>
                    </div>
                    <button
                      className="icon-button"
                      type="button"
                      aria-label="ดูการแจ้งเตือนทั้งหมด"
                      onClick={() => navigate("alerts")}
                    >
                      →
                    </button>
                  </div>
                  <div className="alerts-empty">
                    <span className="alerts-empty-icon" aria-hidden="true">♧</span>
                    <strong>ยังไม่มีข้อมูลการแจ้งเตือน</strong>
                    <p>ระบบจะแสดงเหตุการณ์เมื่อได้รับข้อมูลที่เกี่ยวข้อง</p>
                  </div>
                </section>
              </div>
            </>
          ) : selectedPage === "farms" ? (
            <div className="farm-management-page">
              <section className="section-block farm-management-panel">
                <div className="section-heading">
                  <div>
                    <h2>รายการฟาร์ม</h2>
                    <p>ข้อมูลฟาร์มของ Tenant ที่บัญชีได้รับอนุญาต</p>
                  </div>
                  <div className="sf-heading-actions">
                    <span className="section-note">
                      <span className={`status-dot ${farmsError ? "status-dot-muted" : ""}`} />
                      {farmsLoading ? "กำลังโหลด" : farmsError ? "โหลดข้อมูลไม่สำเร็จ" : farmsRequested ? "เชื่อมต่อ API แล้ว" : "รอเลือก Tenant"}
                    </span>
                    {canManageFarms && (
                      <button
                        className="primary-button"
                        type="button"
                        onClick={() => {
                          setFarmName("");
                          setFarmTimezone("Asia/Bangkok");
                          setFarmActionError("");
                          setFarmActionMessage("");
                          setFarmFormMode("create");
                        }}
                      >+ เพิ่มฟาร์ม</button>
                    )}
                  </div>
                </div>

                <div className="farm-tenant-form">
                  <label htmlFor="farm-tenant-select">
                    Tenant ที่ได้รับอนุญาต
                  </label>
                  <select
                    id="farm-tenant-select"
                    aria-label="เลือก Tenant ที่บัญชีมีสิทธิ์"
                    value={
                      authorizedTenants.some(
                        (item) =>
                          item.id.toLowerCase() ===
                          tenantId.trim().toLowerCase(),
                      )
                        ? authorizedTenants.find(
                            (item) =>
                              item.id.toLowerCase() ===
                              tenantId.trim().toLowerCase(),
                          )?.id ?? ""
                        : ""
                    }
                    onChange={(event) => {
                      setTenantId(event.target.value);
                      setSelectedFarm(null);
                      setSelectedDeviceZone(null);
                      setCopiedField("");
                      setFarmFormMode(null);
                      setZoneFormOpen(false);
                      setEditingZoneId(null);
                      setZoneName("");
                      setZoneDescription("");
                      setZoneStatus("active");
                      setZoneType("plant");
                      setZoneCategoryDetails({});
                      setZoneRelayMappingText("{}");
                      setZoneFormError("");
                      setZoneActionMessage("");
                      setFarmName("");
                      setFarmTimezone("Asia/Bangkok");
                      setFarmActionError("");
                      setFarmActionMessage("");
                    }}
                    disabled={
                      tenantListLoading ||
                      authorizedTenants.length === 0
                    }
                  >
                    <option value="">
                      {tenantListLoading
                        ? "กำลังโหลด Tenant..."
                        : "เลือก Tenant ที่ได้รับอนุญาต"}
                    </option>
                    {authorizedTenants.map((item) => (
                      <option key={item.id} value={item.id}>
                        {item.name} — {item.role}
                      </option>
                    ))}
                  </select>

                  {tenantListError && (
                    <p className="farm-helper-text" role="alert">
                      โหลดรายการ Tenant ไม่สำเร็จ: {tenantListError}
                    </p>
                  )}

                  {!tenantListLoading &&
                    !tenantListError &&
                    authorizedTenants.length === 0 && (
                      <p className="farm-helper-text" role="status">
                        ไม่พบ Tenant ที่บัญชีนี้ได้รับอนุญาต
                      </p>
                    )}

                  <p className="farm-helper-text">
                    เลือก Tenant จากรายการที่บัญชีได้รับอนุญาต
                    ระบบใช้ Access Token ผ่าน API service เดิม
                  </p>
                </div>

                {farmActionMessage && (
                  <div className="farm-message" role="status">
                    {farmActionMessage}
                  </div>
                )}

                {canManageFarms && farmFormMode === "create" && (
                  <div className="sf-modal-backdrop" role="presentation">
                    <div className="sf-modal" role="dialog" aria-modal="true" aria-labelledby="farm-create-modal-title">
                  <form
                    className="farm-crud-form"
                    onSubmit={async (event) => {
                      event.preventDefault();
                      if (farmSaving || !tenantId) return;
                      const name = farmName.trim();
                      const timezone = farmTimezone.trim();
                      const latitudeText = farmLatitude.trim();
                      const longitudeText = farmLongitude.trim();
                      if (!name || !timezone) {
                        setFarmActionError("กรุณากรอกชื่อฟาร์มและเขตเวลา");
                        return;
                      }
                      if (Boolean(latitudeText) !== Boolean(longitudeText)) {
                        setFarmActionError("กรุณากรอก Latitude และ Longitude ให้ครบทั้งคู่ หรือเว้นว่างทั้งคู่");
                        return;
                      }
                      const latitude = latitudeText === "" ? null : Number(latitudeText);
                      const longitude = longitudeText === "" ? null : Number(longitudeText);
                      if (
                        (latitude !== null && (!Number.isFinite(latitude) || latitude < -90 || latitude > 90)) ||
                        (longitude !== null && (!Number.isFinite(longitude) || longitude < -180 || longitude > 180))
                      ) {
                        setFarmActionError("พิกัดไม่ถูกต้อง: Latitude ต้องอยู่ระหว่าง -90 ถึง 90 และ Longitude ระหว่าง -180 ถึง 180");
                        return;
                      }
                      setFarmSaving(true);
                      setFarmActionError("");
                      setFarmActionMessage("");
                      try {
                        const created = await farmApi.create(tenantId, { name, timezone, latitude, longitude });
                        const displayId = `FARM-${String(farms.length + 1).padStart(2, "0")}`;
                        setSelectedFarm({ ...created, displayId });
                        setFarmName("");
                        setFarmTimezone("Asia/Bangkok");
                        setFarmLatitude("");
                        setFarmLongitude("");
                        setFarmFormMode(null);
                        setFarmActionMessage("สร้างฟาร์มสำเร็จ");
                        setFarmsReloadKey((key) => key + 1);
                        navigate("farm-detail");
                      } catch (error) {
                        setFarmActionError(error instanceof Error ? error.message : "สร้างฟาร์มไม่สำเร็จ");
                      } finally {
                        setFarmSaving(false);
                      }
                    }}
                  >
                    <div className="sf-modal-header"><h3 id="farm-create-modal-title">เพิ่มฟาร์ม</h3><button className="secondary-button" type="button" disabled={farmSaving} aria-label="ปิดหน้าต่าง" onClick={() => { setFarmFormMode(null); setFarmActionError(""); }}>ปิด</button></div>
                    <label htmlFor="farm-create-name">ชื่อฟาร์ม</label>
                    <input
                      id="farm-create-name"
                      value={farmName}
                      onChange={(event) => setFarmName(event.target.value)}
                      maxLength={160}
                      required
                      disabled={farmSaving}
                      placeholder="เช่น ฟาร์มผักโรงเรือน"
                    />
                    <label htmlFor="farm-create-timezone">เขตเวลา</label>
                    <select
                      id="farm-create-timezone"
                      value={farmTimezone}
                      onChange={(event) => setFarmTimezone(event.target.value)}
                      disabled={farmSaving}
                    >
                      <option value="Asia/Bangkok">Asia/Bangkok (ประเทศไทย)</option>
                      <option value="UTC">UTC</option>
                      <option value="Asia/Singapore">Asia/Singapore</option>
                      <option value="Asia/Tokyo">Asia/Tokyo</option>
                      <option value="Australia/Sydney">Australia/Sydney</option>
                      <option value="Europe/London">Europe/London</option>
                      <option value="America/New_York">America/New_York</option>
                    </select>
                    <label htmlFor="farm-create-latitude">Latitude (ละติจูด)</label>
                    <input
                      id="farm-create-latitude"
                      type="number"
                      step="any"
                      min="-90"
                      max="90"
                      value={farmLatitude}
                      onChange={(event) => setFarmLatitude(event.target.value)}
                      disabled={farmSaving}
                      placeholder="เช่น 13.7563"
                    />
                    <label htmlFor="farm-create-longitude">Longitude (ลองจิจูด)</label>
                    <input
                      id="farm-create-longitude"
                      type="number"
                      step="any"
                      min="-180"
                      max="180"
                      value={farmLongitude}
                      onChange={(event) => setFarmLongitude(event.target.value)}
                      disabled={farmSaving}
                      placeholder="เช่น 100.5018"
                    />
                    <p className="farm-helper-text">ระบุพิกัดของฟาร์มเพื่อให้ระบบดึงสภาพอากาศจากตำแหน่งฟาร์มโดยอัตโนมัติ หากยังไม่ทราบสามารถเว้นว่างไว้ก่อนได้</p>
                    {farmActionError && <p className="farm-message-error" role="alert">{farmActionError}</p>}
                    <div className="farm-crud-actions">
                      <button className="primary-button" type="submit" disabled={farmSaving}>
                        {farmSaving ? "กำลังบันทึก…" : "สร้างฟาร์ม"}
                      </button>
                    </div>
                  </form>
                    </div>
                  </div>
                )}

                {farmsError && (
                  <div className="farm-message farm-message-error" role="alert">
                    <strong>ไม่สามารถโหลดรายการฟาร์ม</strong>
                    <p>{farmsError}</p>
                  </div>
                )}

                {!farmsError && farmsLoading && (
                  <div className="farm-message" role="status">กำลังดึงข้อมูลฟาร์มจากเซิร์ฟเวอร์…</div>
                )}

                {!farmsError && !farmsLoading && farmsRequested && farms.length === 0 && (
                  <div className="farm-list-empty">
                    <span className="zone-empty-symbol" aria-hidden="true">⌂</span>
                    <h3>ไม่พบรายการฟาร์ม</h3>
                    <p>Tenant นี้ไม่มีฟาร์มที่ API ส่งกลับมา หรือยังไม่มีข้อมูลฟาร์ม</p>
                  </div>
                )}

                {!farmsError && !farmsLoading && farms.length > 0 && (
                  <div className="farm-list" aria-label="รายการฟาร์ม">
                    {farms.map((farm, index) => (
                      <button
                        className="farm-card"
                        key={farm.id}
                        type="button"
                        onClick={() => {
                          setSelectedFarm({
                            ...farm,
                            displayId: `FARM-${String(index + 1).padStart(2, "0")}`,
                          });
                          setSelectedDeviceZone(null);
                          setCopiedField("");
                          setZoneFormOpen(false);
                          setEditingZoneId(null);
                          setZoneName("");
                          setZoneDescription("");
                          setZoneStatus("active");
                          setZoneType("plant");
                          setZoneCategoryDetails({});
                          setZoneRelayMappingText("{}");
                          setZoneFormError("");
                          setZoneActionMessage("");
                          navigate("farm-detail");
                        }}
                        aria-label={`จัดการฟาร์ม ${farm.name}`}
                      >
                        {farmImageUrls[farm.id] ? (
                          <img
                            className="farm-card-image"
                            src={farmImageUrls[farm.id]}
                            alt={`รูปฟาร์ม ${farm.name}`}
                          />
                        ) : (
                          <span className="farm-card-icon" aria-hidden="true">⌂</span>
                        )}
                        <div className="farm-card-main">
                          <h3>{farm.name}</h3>
                          <p>
                            {farm.timezone === "Asia/Bangkok" ? "กรุงเทพฯ" : farm.timezone}
                            <small className="farm-timezone-code">{farm.timezone}</small>
                          </p>
                          <small>สร้างเมื่อ {formatThaiDate(farm.created_at)}</small>
                        </div>
                        <span className="farm-id">{`FARM-${String(index + 1).padStart(2, "0")}`}</span>
                        <span className="farm-card-action" aria-hidden="true">จัดการฟาร์ม →</span>
                      </button>
                    ))}
                  </div>
                )}
              </section>
            </div>
          ) : selectedPage === "farm-detail" ? (
            <section className="section-block farm-detail-panel">
              {selectedFarm ? (
                <>
                  <div className="section-heading">
                    <div>
                      <h2>{selectedFarm.name}</h2>
                      <p>รายละเอียดฟาร์มที่เลือก</p>
                    </div>
                    <span className="source-label">Farm Detail</span>
                  </div>

                  {canManageFarms && farmFormMode === "edit" && (
                    <div className="sf-modal-backdrop" role="presentation">
                      <div className="sf-modal" role="dialog" aria-modal="true" aria-labelledby="farm-edit-modal-title">
                    <form
                      className="farm-crud-form"
                      onSubmit={async (event) => {
                        event.preventDefault();
                        if (farmSaving || !selectedFarm || !tenantId) return;
                        const name = farmName.trim();
                        const timezone = farmTimezone.trim();
                        const latitudeText = farmLatitude.trim();
                        const longitudeText = farmLongitude.trim();
                        if (!name || !timezone) {
                          setFarmActionError("กรุณากรอกชื่อฟาร์มและเขตเวลา");
                          return;
                        }
                        if (Boolean(latitudeText) !== Boolean(longitudeText)) {
                          setFarmActionError("กรุณากรอก Latitude และ Longitude ให้ครบทั้งคู่ หรือเว้นว่างทั้งคู่");
                          return;
                        }
                        const latitude = latitudeText === "" ? null : Number(latitudeText);
                        const longitude = longitudeText === "" ? null : Number(longitudeText);
                        if (
                          (latitude !== null && (!Number.isFinite(latitude) || latitude < -90 || latitude > 90)) ||
                          (longitude !== null && (!Number.isFinite(longitude) || longitude < -180 || longitude > 180))
                        ) {
                          setFarmActionError("พิกัดไม่ถูกต้อง: Latitude ต้องอยู่ระหว่าง -90 ถึง 90 และ Longitude ระหว่าง -180 ถึง 180");
                          return;
                        }
                        setFarmSaving(true);
                        setFarmActionError("");
                        setFarmActionMessage("");
                        try {
                          const updated = await farmApi.update(
                            tenantId,
                            selectedFarm.id,
                            { name, timezone, latitude, longitude },
                          );
                          setSelectedFarm({ ...updated, displayId: selectedFarm.displayId });
                          setFarmFormMode(null);
                          setFarmActionMessage("บันทึกการแก้ไขฟาร์มแล้ว");
                          setFarmsReloadKey((key) => key + 1);
                        } catch (error) {
                          setFarmActionError(error instanceof Error ? error.message : "แก้ไขฟาร์มไม่สำเร็จ");
                        } finally {
                          setFarmSaving(false);
                        }
                      }}
                    >
                      <div className="sf-modal-header"><h3 id="farm-edit-modal-title">แก้ไขข้อมูลฟาร์ม</h3><button className="secondary-button" type="button" disabled={farmSaving} aria-label="ปิดหน้าต่าง" onClick={() => { setFarmFormMode(null); setFarmActionError(""); }}>ปิด</button></div>
                      <label htmlFor="farm-edit-name">ชื่อฟาร์ม</label>
                      <input
                        id="farm-edit-name"
                        value={farmName}
                        onChange={(event) => setFarmName(event.target.value)}
                        maxLength={160}
                        required
                        disabled={farmSaving}
                      />
                      <label htmlFor="farm-edit-timezone">เขตเวลา</label>
                      <select
                        id="farm-edit-timezone"
                        value={farmTimezone}
                        onChange={(event) => setFarmTimezone(event.target.value)}
                        disabled={farmSaving}
                      >
                        <option value="Asia/Bangkok">Asia/Bangkok (ประเทศไทย)</option>
                        <option value="UTC">UTC</option>
                        <option value="Asia/Singapore">Asia/Singapore</option>
                        <option value="Asia/Tokyo">Asia/Tokyo</option>
                        <option value="Australia/Sydney">Australia/Sydney</option>
                        <option value="Europe/London">Europe/London</option>
                        <option value="America/New_York">America/New_York</option>
                      </select>
                      <label htmlFor="farm-edit-latitude">Latitude (ละติจูด)</label>
                      <input
                        id="farm-edit-latitude"
                        type="number"
                        step="any"
                        min="-90"
                        max="90"
                        value={farmLatitude}
                        onChange={(event) => setFarmLatitude(event.target.value)}
                        disabled={farmSaving}
                        placeholder="เช่น 13.7563"
                      />
                      <label htmlFor="farm-edit-longitude">Longitude (ลองจิจูด)</label>
                      <input
                        id="farm-edit-longitude"
                        type="number"
                        step="any"
                        min="-180"
                        max="180"
                        value={farmLongitude}
                        onChange={(event) => setFarmLongitude(event.target.value)}
                        disabled={farmSaving}
                        placeholder="เช่น 100.5018"
                      />
                      <p className="farm-helper-text">พิกัดนี้ใช้เลือกตำแหน่งสภาพอากาศของฟาร์ม หากลบพิกัดทั้งสองช่อง ระบบจะหยุดแสดงสภาพอากาศของฟาร์มนี้</p>
                      {farmActionError && <p className="farm-message-error" role="alert">{farmActionError}</p>}
                      <div className="farm-crud-actions">
                        <button className="primary-button" type="submit" disabled={farmSaving}>
                          {farmSaving ? "กำลังบันทึก…" : "บันทึกการแก้ไข"}
                        </button>
                        <button
                          className="secondary-button"
                          type="button"
                          disabled={farmSaving}
                          onClick={() => {
                            setFarmFormMode(null);
                            setFarmActionError("");
                          }}
                        >
                          ยกเลิก
                        </button>
                      </div>
                    </form>
                      </div>
                    </div>
                  )}
                  {farmActionMessage && <div className="farm-message" role="status">{farmActionMessage}</div>}
                  {farmActionError && farmFormMode !== "edit" && <div className="farm-message farm-message-error" role="alert">{farmActionError}</div>}

                  <section className="farm-image-section" aria-label="รูปภาพฟาร์ม">
                    <div className="farm-image-preview">
                      {farmImageUrls[selectedFarm.id] ? (
                        <img
                          src={farmImageUrls[selectedFarm.id]}
                          alt={`รูปฟาร์ม ${selectedFarm.name}`}
                        />
                      ) : (
                        <div className="farm-image-placeholder" aria-hidden="true">⌂</div>
                      )}
                    </div>
                    <div className="farm-image-controls">
                      <strong>รูปภาพฟาร์ม</strong>
                      <p>รองรับ JPEG, PNG และ WebP ขนาดไม่เกิน 5 MB</p>
                      {canManageFarms && (
                        <label className="farm-image-upload-button">
                          {farmImageBusy ? "กำลังอัปโหลด…" : "อัปโหลด / เปลี่ยนรูป"}
                          <input
                            type="file"
                            accept="image/jpeg,image/png,image/webp"
                            disabled={farmImageBusy || farmSaving}
                            onChange={async (event) => {
                              const input = event.currentTarget;
                              const file = input.files?.[0];
                              if (!file) return;

                              setFarmImageError("");
                              setFarmActionMessage("");

                              const allowedTypes = [
                                "image/jpeg",
                                "image/png",
                                "image/webp",
                              ];
                              if (!allowedTypes.includes(file.type)) {
                                setFarmImageError("ไฟล์ต้องเป็น JPEG, PNG หรือ WebP");
                                input.value = "";
                                return;
                              }
                              if (file.size > 5 * 1024 * 1024) {
                                setFarmImageError("ขนาดรูปต้องไม่เกิน 5 MB");
                                input.value = "";
                                return;
                              }

                              setFarmImageBusy(true);
                              try {
                                await farmApi.uploadImage(
                                  tenantId,
                                  selectedFarm.id,
                                  file,
                                );
                                setFarmImageReloadKey((key) => key + 1);
                                setFarmActionMessage("อัปโหลดรูปฟาร์มสำเร็จ");
                              } catch (error) {
                                setFarmImageError(
                                  error instanceof Error
                                    ? error.message
                                    : "อัปโหลดรูปฟาร์มไม่สำเร็จ",
                                );
                              } finally {
                                setFarmImageBusy(false);
                                input.value = "";
                              }
                            }}
                          />
                        </label>
                      )}
                      {farmImageError && (
                        <p className="farm-image-error" role="alert">{farmImageError}</p>
                      )}
                    </div>
                  </section>

                  <div className="farm-detail-grid">
                    <div className="farm-detail-item">
                      <span>รหัสฟาร์ม</span>
                      <strong>{selectedFarm.displayId}</strong>
                    </div>
                    <div className="farm-detail-item">
                      <span>เขตเวลา</span>
                      <strong>
                        {selectedFarm.timezone === "Asia/Bangkok"
                          ? "กรุงเทพฯ"
                          : selectedFarm.timezone}
                      </strong>
                      <small className="farm-timezone-code">{selectedFarm.timezone}</small>
                    </div>
                    <div className="farm-detail-item">
                      <span>สร้างเมื่อ</span>
                      <strong>{formatThaiDate(selectedFarm.created_at)}</strong>
                    </div>
                  </div>

                  <details className="farm-technical-details">
                    <summary>ข้อมูลทางเทคนิค</summary>
                    <p className="farm-technical-description">
                      รหัสเต็มสำหรับตรวจสอบและอ้างอิงระบบ
                    </p>
                    <div className="farm-technical-row">
                      <div className="farm-technical-value">
                        <span>Tenant ID</span>
                        <code title={tenantId}>{formatTenantDisplayId(tenantId)}</code>
                      </div>
                      {tenantId && (
                        <button
                          className="farm-copy-button"
                          type="button"
                          onClick={async () => {
                            try {
                              await copyTextToClipboard(tenantId);
                              setCopiedField("tenant");
                            } catch {
                              setCopiedField("");
                            }
                          }}
                        >
                          {copiedField === "tenant" ? "คัดลอกแล้ว" : "คัดลอก"}
                        </button>
                      )}
                    </div>
                    <div className="farm-technical-row">
                      <div className="farm-technical-value">
                        <span>Farm UUID</span>
                        <code>{selectedFarm.id}</code>
                      </div>
                      <button
                        className="farm-copy-button"
                        type="button"
                        onClick={async () => {
                          try {
                            await copyTextToClipboard(selectedFarm.id);
                            setCopiedField("farm");
                          } catch {
                            setCopiedField("");
                          }
                        }}
                      >
                        {copiedField === "farm" ? "คัดลอกแล้ว" : "คัดลอก"}
                      </button>
                    </div>
                  </details>

                  <div className="farm-detail-actions">
                    <button
                      className="secondary-button"
                      type="button"
                      onClick={() => {
                        setFarmFormMode(null);
                        setFarmActionError("");
                        setFarmActionMessage("");
                        setFarmName("");
                        setFarmTimezone("Asia/Bangkok");
                        navigate("farms");
                      }}
                    >
                      ← กลับรายการฟาร์ม
                    </button>
                    {canManageFarms && (
                      <>
                        <button
                          className="secondary-button"
                          type="button"
                          disabled={farmSaving}
                          onClick={() => {
                            setFarmName(selectedFarm.name);
                            setFarmTimezone(selectedFarm.timezone);
                            setFarmLatitude(selectedFarm.latitude === null ? "" : String(selectedFarm.latitude));
                            setFarmLongitude(selectedFarm.longitude === null ? "" : String(selectedFarm.longitude));
                            setFarmActionError("");
                            setFarmActionMessage("");
                            setFarmFormMode("edit");
                          }}
                        >
                          แก้ไขฟาร์ม
                        </button>
                        <button
                          className="secondary-button farm-delete-button"
                          type="button"
                          disabled={farmSaving}
                          onClick={async () => {
                            if (!window.confirm(`ยืนยันลบฟาร์ม "${selectedFarm.name}" หรือไม่? การลบจะไม่ทำงานหากยังมีโซนหรืออุปกรณ์อ้างอิงอยู่`)) return;
                            setFarmSaving(true);
                            setFarmActionError("");
                            setFarmActionMessage("");
                            try {
                              await farmApi.delete(tenantId, selectedFarm.id);
                              setSelectedFarm(null);
                              setFarmFormMode(null);
                              setFarmsReloadKey((key) => key + 1);
                              setFarmActionMessage("ลบฟาร์มสำเร็จ");
                              navigate("farms");
                            } catch (error) {
                              setFarmActionError(error instanceof Error ? error.message : "ลบฟาร์มไม่สำเร็จ");
                            } finally {
                              setFarmSaving(false);
                            }
                          }}
                        >
                          {farmSaving ? "กำลังดำเนินการ…" : "ลบฟาร์ม"}
                        </button>
                      </>
                    )}
                    <button
                      className="primary-button"
                      type="button"
                      onClick={() => {
                        setZoneSearch("");
                        navigate("zones");
                      }}
                    >
                      ไปยัง Zone Management →
                    </button>
                  </div>
                </>
              ) : (
                <div className="farm-list-empty">
                  <h3>ยังไม่ได้เลือกฟาร์ม</h3>
                  <p>กลับไปเลือกรายการฟาร์มก่อนเปิดหน้าจัดการ</p>
                  <button
                    className="primary-button"
                    type="button"
                    onClick={() => navigate("farms")}
                  >
                    ไปยังรายการฟาร์ม
                  </button>
                </div>
              )}
            </section>
          ) : selectedPage === "zones" ? (
            <div className="zone-management-page">
              <section className="section-block zone-management-panel">
                <div className="section-heading">
                  <div>
                    <h2>Zone Management</h2>
                    <p>จัดการโซนเพาะปลูกภายในฟาร์มที่เลือก</p>
                  </div>
                  <div className="sf-heading-actions">
                    <span className="section-note">
                      <span className={`status-dot ${zonesError ? "status-dot-muted" : ""}`} />
                      {zonesLoading ? "กำลังโหลด" : zonesError ? "โหลดข้อมูลไม่สำเร็จ" :zonesRequested ? "เชื่อมต่อ Zone API แล้ว" : "รอ Tenant และ Farm"}
                    </span>
                    {selectedFarm && ["owner", "operator"].includes(
                      authorizedTenants.find((item) => item.id.toLowerCase() === tenantId.trim().toLowerCase())?.role ?? ""
                    ) && (
                      <button
                        className="primary-button"
                        type="button"
                        onClick={() => {
                          setEditingZoneId(null);
                          setZoneName("");
                          setZoneDescription("");
                          setZoneStatus("active");
                          setZoneType("plant");
                          setZoneCategoryDetails({});
                          setZoneRelayMappingText("{}");
                          setZoneFormError("");
                          setZoneActionMessage("");
                          setZoneFormOpen(true);
                        }}
                      >+ เพิ่มโซน</button>
                    )}
                  </div>
                </div>

                <div className="zone-context-panel">
                  <div className="zone-context-main">
                    {selectedFarm && farmImageUrls[selectedFarm.id] ? (
                      <img
                        className="zone-context-image"
                        src={farmImageUrls[selectedFarm.id]}
                        alt={`รูปฟาร์ม ${selectedFarm.name}`}
                      />
                    ) : (
                      <span className="zone-context-icon" aria-hidden="true">⌂</span>
                    )}
                    <div>
                      <span className="zone-context-label">ฟาร์มที่เลือก</span>
                      <strong>{selectedFarm?.name ?? "ยังไม่ได้เลือกฟาร์ม"}</strong>
                      <small>{selectedFarm?.timezone ?? "เลือกฟาร์มก่อนเพื่อดูและจัดการโซน"}</small>
                    </div>
                  </div>
                  <button className="secondary-button" type="button" onClick={() => navigate("farms")}>
                    {selectedFarm ? "เปลี่ยนฟาร์ม" : "ไปยัง Farm Management"}
                  </button>
                </div>

                <div className="zone-tenant-context">
                  <span>Tenant</span>
                  <code>{formatTenantDisplayId(tenantId)}</code>
                  <span>สิทธิ์</span>
                  <strong>{authorizedTenants.find((item) => item.id.toLowerCase() === tenantId.trim().toLowerCase())?.role ?? "ไม่มีสิทธิ์"}</strong>
                </div>

                <label className="zone-search-field">
                  <span aria-hidden="true">⌕</span>
                  <span className="sr-only">ค้นหาโซน</span>
                  <input
                    type="search"
                    value={zoneSearch}
                    onChange={(event) => setZoneSearch(event.target.value)}
                    placeholder="ค้นหาชื่อโซน"
                    aria-label="ค้นหาชื่อโซน"
                    disabled={!selectedFarm}
                  />
                </label>

                {(() => {
                  const role = authorizedTenants.find(
                    (item) => item.id.toLowerCase() === tenantId.trim().toLowerCase(),
                  )?.role;
                  const canManage = role === "owner" || role === "operator";
                  return (
                    <>
                      {canManage && selectedFarm && zoneFormOpen && (
                        <div className="sf-modal-backdrop" role="presentation">
                          <div className="sf-modal" role="dialog" aria-modal="true" aria-labelledby="zone-modal-title">
                        <form
                          className="zone-form"
                          onSubmit={async (event) => {
                            event.preventDefault();
                            if (!selectedFarm || !canManage || zoneSaving) return;
                            const name = zoneName.trim();
                            if (!name) {
                              setZoneFormError("กรุณาระบุชื่อโซน");
                              return;
                            }
                            setZoneSaving(true);
                            setZoneFormError("");
                            setZoneActionMessage("");
                            try {
                              let categoryDetails: ZoneCategoryDetails = {
                                ...zoneCategoryDetails,
                              };
                              if (zoneType === "lighting") {
                                const rawCount = categoryDetails.switch_count;
                                if (rawCount === "" || rawCount === undefined) {
                                  delete categoryDetails.switch_count;
                                } else {
                                  const count = Number(rawCount);
                                  if (!Number.isInteger(count) || count < 1) {
                                    throw new Error("จำนวนสวิตช์ต้องเป็นจำนวนเต็มตั้งแต่ 1 ขึ้นไป");
                                  }
                                  categoryDetails.switch_count = count;
                                }
                                let relayMapping: unknown;
                                try {
                                  relayMapping = JSON.parse(zoneRelayMappingText);
                                } catch {
                                  throw new Error("Relay mapping ต้องเป็น JSON ที่ถูกต้อง");
                                }
                                if (
                                  relayMapping === null ||
                                  typeof relayMapping !== "object" ||
                                  Array.isArray(relayMapping)
                                ) {
                                  throw new Error("Relay mapping ต้องเป็น JSON object ที่ถูกต้อง");
                                }
                                categoryDetails.relay_mapping = relayMapping;
                              }
                              const payload = {
                                name,
                                description: zoneDescription.trim() || null,
                                status: zoneStatus,
                                zone_type: zoneType,
                                category_details: categoryDetails,
                              };
                              if (editingZoneId) {
                                await zoneApi.update(tenantId, selectedFarm.id, editingZoneId, payload);
                                setZoneActionMessage("บันทึกการแก้ไขโซนแล้ว");
                              } else {
                                await zoneApi.create(tenantId, selectedFarm.id, payload);
                                setZoneActionMessage("สร้างโซนแล้ว");
                              }
                              setZoneName("");
                              setZoneDescription("");
                              setZoneStatus("active");
                              setZoneType("plant");
                              setZoneCategoryDetails({});
                              setZoneRelayMappingText("{}");
                              setEditingZoneId(null);
                              setZoneFormOpen(false);
                              setZonesReloadKey((key) => key + 1);
                            } catch (error) {
                              setZoneFormError(error instanceof Error ? error.message : "บันทึกข้อมูลโซนไม่สำเร็จ");
                            } finally {
                              setZoneSaving(false);
                            }
                          }}
                        >
                          <div className="sf-modal-header"><h3 id="zone-modal-title">{editingZoneId ? "แก้ไขโซน" : "เพิ่มโซนใหม่"}</h3><button className="secondary-button" type="button" disabled={zoneSaving} aria-label="ปิดหน้าต่าง" onClick={() => { setZoneFormOpen(false); setZoneFormError(""); }}>ปิด</button></div>
                          <label>
                            ชื่อโซน
                            <input
                              value={zoneName}
                              onChange={(event) => setZoneName(event.target.value)}
                              maxLength={120}
                              required
                              disabled={zoneSaving}
                              placeholder="เช่น Greenhouse A"
                            />
                          </label>
                          <label>
                            คำอธิบาย
                            <textarea
                              value={zoneDescription}
                              onChange={(event) => setZoneDescription(event.target.value)}
                              maxLength={500}
                              rows={2}
                              disabled={zoneSaving}
                              placeholder="รายละเอียดเพิ่มเติม (ไม่บังคับ)"
                            />
                          </label>
                          <label>
                            สถานะ
                            <select
                              value={zoneStatus}
                              onChange={(event) => setZoneStatus(event.target.value as "active" | "disabled")}
                              disabled={zoneSaving}
                            >
                              <option value="active">เปิดใช้งาน</option>
                              <option value="disabled">ปิดใช้งาน</option>
                            </select>
                          </label>
                          <label>
                            ประเภทโซน
                            <select
                              value={zoneType}
                              disabled={zoneSaving}
                              onChange={(event) => {
                                setZoneType(event.target.value as ZoneType);
                                setZoneCategoryDetails({});
                                setZoneRelayMappingText("{}");
                              }}
                            >
                              <option value="plant">พืช</option>
                              <option value="livestock">ปศุสัตว์</option>
                              <option value="fish_pond">บ่อปลา</option>
                              <option value="mushroom">เห็ด</option>
                              <option value="cctv">กล้องวงจรปิด</option>
                              <option value="lighting">แสงสว่าง</option>
                            </select>
                          </label>

                          {zoneType === "plant" && (
                            <>
                              <label>ชื่อพืช
                                <input value={String(zoneCategoryDetails.crop_name ?? "")} maxLength={120} disabled={zoneSaving}
                                  onChange={(event) => setZoneCategoryDetails((current) => ({ ...current, crop_name: event.target.value }))} />
                              </label>
                              <label>ประเภทพืช
                                <input value={String(zoneCategoryDetails.crop_type ?? "")} maxLength={120} disabled={zoneSaving}
                                  onChange={(event) => setZoneCategoryDetails((current) => ({ ...current, crop_type: event.target.value }))} />
                              </label>
                            </>
                          )}
                          {zoneType === "livestock" && (
                            <label>ชนิดสัตว์
                              <input value={String(zoneCategoryDetails.species ?? "")} maxLength={120} disabled={zoneSaving}
                                onChange={(event) => setZoneCategoryDetails((current) => ({ ...current, species: event.target.value }))} />
                            </label>
                          )}
                          {zoneType === "fish_pond" && (
                            <label>ชนิดปลา
                              <input value={String(zoneCategoryDetails.fish_species ?? "")} maxLength={120} disabled={zoneSaving}
                                onChange={(event) => setZoneCategoryDetails((current) => ({ ...current, fish_species: event.target.value }))} />
                            </label>
                          )}
                          {zoneType === "mushroom" && (
                            <>
                              <label>ชนิดเห็ด
                                <input value={String(zoneCategoryDetails.mushroom_type ?? "")} maxLength={120} disabled={zoneSaving}
                                  onChange={(event) => setZoneCategoryDetails((current) => ({ ...current, mushroom_type: event.target.value }))} />
                              </label>
                              <label>สายพันธุ์
                                <input value={String(zoneCategoryDetails.variety ?? "")} maxLength={120} disabled={zoneSaving}
                                  onChange={(event) => setZoneCategoryDetails((current) => ({ ...current, variety: event.target.value }))} />
                              </label>
                            </>
                          )}
                          {zoneType === "cctv" && (
                            <>
                              <label>ชื่อกล้อง
                                <input value={String(zoneCategoryDetails.camera_name ?? "")} maxLength={120} disabled={zoneSaving}
                                  onChange={(event) => setZoneCategoryDetails((current) => ({ ...current, camera_name: event.target.value }))} />
                              </label>
                              <label>รหัสกล้อง
                                <input value={String(zoneCategoryDetails.camera_id ?? "")} maxLength={120} disabled={zoneSaving}
                                  onChange={(event) => setZoneCategoryDetails((current) => ({ ...current, camera_id: event.target.value }))} />
                              </label>
                              <label>URL สตรีมกล้อง
                                <input type="url" value={String(zoneCategoryDetails.stream_url ?? "")} maxLength={500} disabled={zoneSaving}
                                  placeholder="rtsp://camera.local/live"
                                  onChange={(event) => setZoneCategoryDetails((current) => ({ ...current, stream_url: event.target.value }))} />
                                <small>ห้ามใส่ username/password, query parameters หรือ fragment ใน URL</small>
                              </label>
                            </>
                          )}
                          {zoneType === "lighting" && (
                            <>
                              <label>จำนวนสวิตช์
                                <input type="number" min={1} step={1}
                                  value={String(zoneCategoryDetails.switch_count ?? "")} disabled={zoneSaving}
                                  onChange={(event) => setZoneCategoryDetails((current) => ({ ...current, switch_count: event.target.value }))} />
                              </label>
                              <label>จับคู่สวิตช์กับช่องรีเลย์ (JSON)
                                <textarea rows={3} value={zoneRelayMappingText} disabled={zoneSaving}
                                  onChange={(event) => setZoneRelayMappingText(event.target.value)}
                                  placeholder={'{"Switch 1": 1, "Switch 2": 2}'} />
                                <small>ระบุเลขช่องรีเลย์เป็นจำนวนเต็มบวก การตรวจว่าช่องมีอยู่จริงต้องอาศัยข้อมูลอุปกรณ์</small>
                              </label>
                            </>
                          )}
                          {zoneFormError && <p className="farm-message-error" role="alert">{zoneFormError}</p>}
                          <div className="zone-form-actions">
                            <button className="primary-button" type="submit" disabled={zoneSaving}>
                              {zoneSaving ? "กำลังบันทึก…" : editingZoneId ? "บันทึกการแก้ไข" : "สร้างโซน"}
                            </button>
                            {editingZoneId && (
                              <button
                                className="secondary-button"
                                type="button"
                                disabled={zoneSaving}
                                onClick={() => {
                                  setEditingZoneId(null);
                                  setZoneName("");
                                  setZoneDescription("");
                                  setZoneStatus("active");
                                  setZoneType("plant");
                                  setZoneCategoryDetails({});
                                  setZoneRelayMappingText("{}");
                                  setZoneFormError("");
                                  setZoneFormOpen(false);
                                }}
                              >ยกเลิก</button>
                            )}
                          </div>
                        </form>
                          </div>
                        </div>
                      )}

                      {zoneActionMessage && <div className="farm-message" role="status">{zoneActionMessage}</div>}
                      {zonesError && (
                        <div className="farm-message farm-message-error" role="alert">
                          <strong>ไม่สามารถโหลดรายการโซน</strong>
                          <p>{zonesError}</p>
                          <button className="secondary-button" type="button" onClick={() => setZonesReloadKey((key) => key + 1)}>ลองอีกครั้ง</button>
                        </div>
                      )}
                      {zonesLoading && <div className="farm-message" role="status">กำลังโหลดข้อมูลโซนจาก API…</div>}
                      {!tenantListLoading && !authorizedTenants.some((item) => item.id.toLowerCase() === tenantId.trim().toLowerCase()) && (
                        <div className="farm-list-empty">
                          <h3>กรุณาเลือก Tenant ที่ได้รับอนุญาต</h3>
                          <p>ไปยัง Farm Management เพื่อเลือก Tenant ที่บัญชีเข้าถึงได้</p>
                        </div>
                      )}
                      {!selectedFarm && (
                        <div className="farm-list-empty">
                          <h3>ยังไม่ได้เลือกฟาร์ม</h3>
                          <p>เลือกรายการฟาร์มก่อน แล้วกลับมาจัดการโซน</p>
                          <button className="primary-button" type="button" onClick={() => navigate("farms")}>ไปยัง Farm Management</button>
                        </div>
                      )}
                      {!zonesLoading && !zonesError && selectedFarm && zonesRequested && zones.length === 0 && (
                        <div className="zone-list-empty">
                          <span className="zone-empty-symbol" aria-hidden="true">▦</span>
                          <h3>{zoneSearch.trim() ? "ไม่พบโซนที่ตรงกับคำค้นหา" : "ยังไม่มีโซนในฟาร์มนี้"}</h3>
                          <p>{canManage ? "กดปุ่ม + เพิ่มโซน เพื่อเริ่มต้น" : "บัญชีนี้มีสิทธิ์ดูข้อมูลเท่านั้น"}</p>
                        </div>
                      )}
                      {!zonesLoading && !zonesError && zones.length > 0 && (
                        <div className="zone-list" aria-label="รายการโซน">
                          {zones.map((zone) => (
                            <article className="zone-card" key={zone.id}>
                              <div className="zone-card-main">
                                <div className="zone-card-heading">
                                  <h3>{zone.name}</h3>
                                  <span className={`zone-status ${zone.status === "active" ? "zone-status-active" : "zone-status-disabled"}`}>
                                    {zone.status === "active" ? "เปิดใช้งาน" : "ปิดใช้งาน"}
                                  </span>
                                </div>
                                <p>{zone.description || "ไม่มีคำอธิบาย"}</p>
                                <small>ประเภทโซน: {zoneTypeLabels[zone.zone_type ?? "plant"]}</small>
                                <br />
                                <small>แก้ไขล่าสุด {formatThaiDate(zone.updated_at)}</small>
                              </div>
                              <div className="zone-card-actions">
                                <button
                                  className="secondary-button"
                                  type="button"
                                  onClick={() => {
                                    setSelectedDeviceZone({
                                      id: zone.id,
                                      name: zone.name,
                                      farmId: zone.farm_id,
                                    });
                                    navigate("devices");
                                  }}
                                >ดูอุปกรณ์และค่าเซนเซอร์</button>
                                {canManage && (
                                  <>
                                  <button
                                    className="secondary-button"
                                    type="button"
                                    disabled={zoneSaving}
                                    onClick={() => {
                                      setEditingZoneId(zone.id);
                                      setZoneName(zone.name);
                                      setZoneDescription(zone.description ?? "");
                                      setZoneStatus(zone.status);
                                      setZoneType(zone.zone_type ?? "plant");
                                      setZoneCategoryDetails(zone.category_details ?? {});
                                      setZoneRelayMappingText(
                                        JSON.stringify(zone.category_details?.relay_mapping ?? {}, null, 2),
                                      );
                                      setZoneFormError("");
                                      setZoneActionMessage("");
                                      setZoneFormOpen(true);
                                    }}
                                  >แก้ไข</button>
                                  <button
                                    className="secondary-button zone-delete-button"
                                    type="button"
                                    disabled={zoneSaving}
                                    onClick={async () => {
                                      if (!window.confirm(`ยืนยันลบโซน "${zone.name}" หรือไม่?`)) return;
                                      setZoneSaving(true);
                                      setZoneFormError("");
                                      setZoneActionMessage("");
                                      try {
                                        if (!selectedFarm) {
                                            setZonesError("กรุณาเลือกฟาร์มก่อนดำเนินการ");
                                            return;
                                        }
                                        await zoneApi.delete(tenantId, selectedFarm.id, zone.id);
                                        if (editingZoneId === zone.id) {
                                          setEditingZoneId(null);
                                          setZoneName("");
                                          setZoneDescription("");
                                          setZoneStatus("active");
                                          setZoneType("plant");
                                          setZoneCategoryDetails({});
                                          setZoneRelayMappingText("{}");
                                          setZoneFormOpen(false);
                                        }
                                        setZoneActionMessage("ลบโซนแล้ว");
                                        setZonesReloadKey((key) => key + 1);
                                      } catch (error) {
                                        setZoneFormError(error instanceof Error ? error.message : "ลบโซนไม่สำเร็จ");
                                      } finally {
                                        setZoneSaving(false);
                                      }
                                    }}
                                  >ลบ</button>
                                  </>
                                )}
                              </div>
                            </article>
                          ))}
                        </div>
                      )}
                      {role === "viewer" && selectedFarm && (
                        <p className="farm-helper-text">สิทธิ์ Viewer: สามารถดูและค้นหาโซนได้ แต่ไม่สามารถสร้าง แก้ไข หรือลบ</p>
                      )}
                    </>
                  );
                })()}
              </section>
            </div>
          ) : selectedPage === "devices" ? (
            <div className="device-management-page">
              <section className="section-block device-management-panel">
                <div className="section-heading">
                  <div>
                    <h2>รายการอุปกรณ์</h2>
                    <p>ข้อมูลจาก Device API ตามสิทธิ์ของ Tenant ที่ได้รับอนุญาต</p>
                  </div>
                  <span className="section-note">
                    <span className={`status-dot ${devicesError ? "status-dot-muted" : ""}`} />
                    {devicesLoading ? "กำลังโหลด" : devicesError ? "โหลดข้อมูลไม่สำเร็จ" : devicesRequested ? "เชื่อมต่อ API แล้ว" : "รอ Tenant ที่ได้รับอนุญาต"}
                  </span>
                </div>

                <div className="device-tenant-context">
                  {tenantListLoading ? (
                    <p role="status">กำลังตรวจสอบสิทธิ์ Tenant จากเซิร์ฟเวอร์…</p>
                  ) : tenantListError ? (
                    <p className="farm-message farm-message-error" role="alert">
                      ตรวจสอบสิทธิ์ Tenant ไม่สำเร็จ: {tenantListError}
                    </p>
                  ) : authorizedDeviceTenant ? (
                    <p>
                      Tenant ปัจจุบัน: <strong>{authorizedDeviceTenant.name}</strong>
                      {" · "}สิทธิ์ {authorizedDeviceTenant.role}
                    </p>
                  ) : (
                    <p>
                      ยังไม่มี Tenant ที่เลือกและได้รับอนุญาต
                      กรุณาเลือก Tenant ผ่านหน้า Farm Management ก่อน
                    </p>
                  )}
                </div>

                {canManageFarms && deviceFormMode && (
                  <div className="sf-modal-backdrop" role="presentation">
                    <div className="sf-modal" role="dialog" aria-modal="true" aria-labelledby="device-crud-modal-title">
                      <form
                        className="farm-crud-form"
                        onSubmit={async (event) => {
                          event.preventDefault();
                          if (deviceFormSaving || !authorizedDeviceTenant) return;

                          if (!["owner", "operator"].includes(authorizedDeviceTenant.role)) {
                            setDeviceFormError("บัญชีนี้ไม่มีสิทธิ์จัดการอุปกรณ์");
                            return;
                          }

                          const type = deviceFormType.trim();
                          const name = deviceFormName.trim();

                          if (!type || !name || !deviceFormFarmId) {
                            setDeviceFormError("กรุณากรอกชนิด ชื่อ และเลือกฟาร์มให้ครบ");
                            return;
                          }

                          if (!farms.some((farm) => farm.id === deviceFormFarmId)) {
                            setDeviceFormError("ไม่พบฟาร์มที่เลือกในรายการฟาร์มของระบบ");
                            return;
                          }

                          setDeviceFormSaving(true);
                          setDeviceFormError("");

                          try {
                            if (deviceFormMode === "create") {
                              await deviceApi.create(authorizedDeviceTenant.id, {
                                device_type: type,
                                name,
                                farm_id: deviceFormFarmId,
                                status: deviceFormStatus,
                              });
                            } else if (deviceEditing) {
                              await deviceApi.update(
                                authorizedDeviceTenant.id,
                                deviceEditing.id,
                                {
                                  device_type: type,
                                  name,
                                  farm_id: deviceFormFarmId,
                                  status: deviceFormStatus,
                                },
                              );
                            } else {
                              throw new Error("ไม่พบอุปกรณ์ที่ต้องการแก้ไข");
                            }

                            if (deviceFormMode === "create") {
                              setSelectedDeviceZone(null);
                            }

                            setDeviceFormMode(null);
                            setDeviceEditing(null);
                            setDeviceFormCode("");
                            setDeviceFormType("");
                            setDeviceFormName("");
                            setDeviceFormFarmId("");
                            setDeviceFormStatus("pending");
                            setDevicesReloadKey((key) => key + 1);
                          } catch (error) {
                            setDeviceFormError(
                              error instanceof Error ? error.message : "บันทึกข้อมูลอุปกรณ์ไม่สำเร็จ",
                            );
                          } finally {
                            setDeviceFormSaving(false);
                          }
                        }}
                      >
                        <div className="sf-modal-header">
                          <h3 id="device-crud-modal-title">
                            {deviceFormMode === "create" ? "เพิ่มอุปกรณ์" : "แก้ไขข้อมูลอุปกรณ์"}
                          </h3>
                          <button
                            className="secondary-button"
                            type="button"
                            disabled={deviceFormSaving}
                            onClick={() => {
                              setDeviceFormMode(null);
                              setDeviceEditing(null);
                              setDeviceFormError("");
                            }}
                          >
                            ปิด
                          </button>
                        </div>

                        {deviceFormError && (
                          <div className="farm-message farm-message-error" role="alert">
                            {deviceFormError}
                          </div>
                        )}

                        <label htmlFor="device-crud-name">ชื่ออุปกรณ์</label>
                        <input
                          id="device-crud-name"
                          value={deviceFormName}
                          onChange={(event) => setDeviceFormName(event.target.value)}
                          maxLength={160}
                          required
                          disabled={deviceFormSaving}
                          placeholder="เช่น ตัวควบคุมโรงเรือน 1"
                        />

                        <label htmlFor="device-crud-type">ชนิดอุปกรณ์</label>
                        <input
                          id="device-crud-type"
                          value={deviceFormType}
                          onChange={(event) => setDeviceFormType(event.target.value)}
                          maxLength={64}
                          required
                          disabled={deviceFormSaving}
                          placeholder="เช่น esp32, relay_controller"
                        />

                        <label htmlFor="device-crud-farm">ฟาร์ม</label>
                        <select
                          id="device-crud-farm"
                          value={deviceFormFarmId}
                          onChange={(event) => setDeviceFormFarmId(event.target.value)}
                          required
                          disabled={deviceFormSaving || farmsLoading}
                        >
                          <option value="">เลือกฟาร์ม</option>
                          {farms.map((farm) => (
                            <option key={farm.id} value={farm.id}>{farm.name}</option>
                          ))}
                        </select>
                        {farmsError && (
                          <p className="farm-helper-text" role="alert">
                            โหลดรายการฟาร์มไม่สำเร็จ: {farmsError}
                          </p>
                        )}

                        <label htmlFor="device-crud-status">สถานะ</label>
                        <select
                          id="device-crud-status"
                          value={deviceFormStatus}
                          onChange={(event) => setDeviceFormStatus(event.target.value as typeof deviceFormStatus)}
                          disabled={deviceFormSaving}
                        >
                          <option value="pending">รอเปิดใช้งาน</option>
                          <option value="active">เปิดใช้งาน</option>
                          <option value="disabled">ปิดใช้งาน</option>
                          <option value="revoked">เพิกถอนแล้ว</option>
                        </select>

                        <button
                          className="primary-button"
                          type="submit"
                          disabled={deviceFormSaving || farmsLoading || farms.length === 0}
                        >
                          {deviceFormSaving ? "กำลังบันทึก…" : "บันทึกอุปกรณ์"}
                        </button>
                      </form>
                    </div>
                  </div>
                )}

                {selectedDeviceZone && (
                  <div className="device-tenant-context">
                    <p>
                      กำลังแสดงโซน: <strong>{selectedDeviceZone.name}</strong>
                    </p>
                    <button
                      className="secondary-button"
                      type="button"
                      disabled={devicesLoading || !authorizedDeviceTenant}
                      onClick={() => setSelectedDeviceZone(null)}
                    >แสดงอุปกรณ์ทั้งหมดในฟาร์ม</button>
                  </div>
                )}

                <div className="device-list-toolbar">
                  <span>
                    {devicesRequested && !devicesLoading && !devicesError
                      ? `${(selectedFarm ? devices.filter((device) => device.farm_id === selectedFarm.id) : []).filter((device) => !selectedDeviceZone || (device.zone_id === selectedDeviceZone.id && device.farm_id === selectedDeviceZone.farmId)).length} อุปกรณ์`
                      : "รายการอุปกรณ์"}
                  </span>
                  {canManageFarms && authorizedDeviceTenant && (
                    <button
                      className="primary-button"
                      type="button"
                      disabled={deviceFormSaving || farmsLoading || farms.length === 0}
                      onClick={() => {
                        setDeviceEditing(null);
                        setDeviceFormMode("create");
                        setDeviceFormCode("");
                        setDeviceFormType("");
                        setDeviceFormName("");
                        setDeviceFormFarmId(
                          selectedFarm && farms.some((farm) => farm.id === selectedFarm.id)
                            ? selectedFarm.id
                            : farms[0]?.id ?? "",
                        );
                        setDeviceFormStatus("pending");
                        setDeviceFormError("");
                      }}
                    >
                      เพิ่มอุปกรณ์
                    </button>
                  )}
                  <button
                    className="secondary-button"
                    type="button"
                    disabled={devicesLoading || !authorizedDeviceTenant}
                    onClick={() => setDevicesReloadKey((key) => key + 1)}
                  >
                    โหลดใหม่
                  </button>
                </div>

                {devicesError && (
                  <div className="farm-message farm-message-error" role="alert">
                    <strong>ไม่สามารถโหลดรายการอุปกรณ์</strong>
                    <p>{devicesError}</p>
                  </div>
                )}

                {!devicesError && devicesLoading && (
                  <div className="farm-message" role="status">
                    กำลังดึงข้อมูลอุปกรณ์จากเซิร์ฟเวอร์…
                  </div>
                )}

                {!devicesError && !devicesLoading && !devicesRequested && (
                  <div className="farm-list-empty">
                    <span className="zone-empty-symbol" aria-hidden="true">▣</span>
                    <h3>
                      {tenantListLoading
                        ? "กำลังตรวจสอบสิทธิ์"
                        : authorizedDeviceTenant
                          ? "พร้อมโหลดข้อมูลอุปกรณ์"
                          : "กรุณาเลือก Tenant ที่ได้รับอนุญาต"}
                    </h3>
                    <p>
                      {tenantListLoading
                        ? "รอผลการตรวจสอบสิทธิ์จากเซิร์ฟเวอร์"
                        : authorizedDeviceTenant
                          ? "กดโหลดใหม่เพื่อดึงรายการอุปกรณ์"
                          : "ไปที่ Farm Management เพื่อเลือก Tenant ที่บัญชีของคุณเข้าถึงได้"}
                    </p>
                  </div>
                )}

                {!devicesError && !devicesLoading && devicesRequested && (!selectedFarm || !devices.some((device) => device.farm_id === selectedFarm.id)) && !selectedDeviceZone && (
                  <div className="farm-list-empty">
                    <span className="zone-empty-symbol" aria-hidden="true">▣</span>
                    <h3>ไม่พบรายการอุปกรณ์</h3>
                    <p>API ไม่พบอุปกรณ์สำหรับ Tenant นี้ หรือยังไม่มีข้อมูลอุปกรณ์</p>
                  </div>
                )}

                {!devicesError && !devicesLoading && devicesRequested && selectedDeviceZone && !devices.some((device) => device.farm_id === selectedFarm?.id && device.zone_id === selectedDeviceZone.id && device.farm_id === selectedDeviceZone.farmId) && (
                  <div className="farm-list-empty">
                    <span className="zone-empty-symbol" aria-hidden="true">▣</span>
                    <h3>ยังไม่มีอุปกรณ์ในโซนนี้</h3>
                    <p>ไม่พบอุปกรณ์ที่ผูกกับโซน {selectedDeviceZone.name} ในฟาร์มที่เลือก ตรวจสอบการกำหนด Zone ของอุปกรณ์ได้จากรายการอุปกรณ์ทั้งหมด</p>
                  </div>
                )}

                {!devicesError && !devicesLoading && selectedFarm && (selectedDeviceZone
                  ? devices.some((device) => device.farm_id === selectedFarm.id && device.zone_id === selectedDeviceZone.id && device.farm_id === selectedDeviceZone.farmId)
                  : devices.some((device) => device.farm_id === selectedFarm.id)) && (
                  <div className="device-list" aria-label="รายการอุปกรณ์">
                    {(devices.filter((device) => device.farm_id === selectedFarm.id))
                      .filter((device) => !selectedDeviceZone || (device.zone_id === selectedDeviceZone.id && device.farm_id === selectedDeviceZone.farmId))
                      .map((device) => {
                      const statusLabels: Record<string, string> = {
                        active: "เปิดใช้งาน",
                        pending: "รอเปิดใช้งาน",
                        disabled: "ปิดใช้งาน",
                        revoked: "เพิกถอนแล้ว",
                      };
                      return (
                        <article className="device-card" key={device.id}>
                          <div className="device-card-top">
                            <span className="device-card-icon" aria-hidden="true">▣</span>
                            <div className="device-card-title">
                              <h3>{device.name}</h3>
                              <p>{device.device_code}</p>
                            </div>
                            <span className={`device-status device-status-${device.status}`}>
                              {statusLabels[device.status] ?? device.status}
                            </span>
                            {canManageFarms && (
                              <button
                                className="secondary-button"
                                type="button"
                                disabled={deviceFormSaving}
                                onClick={() => {
                                  setDeviceEditing(device);
                                  setDeviceFormMode("edit");
                                  setDeviceFormCode(device.device_code);
                                  setDeviceFormType(device.device_type);
                                  setDeviceFormName(device.name);
                                  setDeviceFormFarmId(device.farm_id ?? "");
                                  setDeviceFormStatus(
                                    device.status === "active" ||
                                    device.status === "disabled" ||
                                    device.status === "revoked"
                                      ? device.status
                                      : "pending",
                                  );
                                  setDeviceFormError("");
                                }}
                              >
                                แก้ไข
                              </button>
                            )}
                          </div>
                          <dl className="device-card-details">
                            <div>
                              <dt>ชนิดอุปกรณ์</dt>
                              <dd>{device.device_type}</dd>
                            </div>
                            <div>

                              <dt>พบล่าสุด</dt>
                              <dd>
                                {device.last_seen_at
                                  ? formatThaiDate(device.last_seen_at)
                                  : "ยังไม่มีข้อมูล"}
                              </dd>
                            </div>
                            <div>
                              <dt>Farm ID</dt>
                              <dd>{device.farm_id ?? "ยังไม่ได้ผูกกับฟาร์ม"}</dd>
                            </div>
                          </dl>
                          <section
                            className="device-telemetry"
                            aria-label={`ค่าเซนเซอร์ล่าสุดของ ${device.name}`}
                          >
                            <div className="device-telemetry-header">
                              <h4>ค่าเซนเซอร์ล่าสุด</h4>
                              <button
                                type="button"
                                className="secondary-button"
                                disabled={telemetryLoading || !authorizedDeviceTenant}
                                onClick={() => setTelemetryReloadKey((key) => key + 1)}
                              >
                                {telemetryLoading ? "กำลังโหลด…" : "รีเฟรช"}
                              </button>
                            </div>

                            {telemetryLoading && (
                              <p className="telemetry-message" role="status">
                                กำลังโหลดค่าเซนเซอร์…
                              </p>
                            )}

                            {!telemetryLoading && telemetryError && (
                              <div className="telemetry-message telemetry-error" role="alert">
                                <p>{telemetryError}</p>
                              </div>
                            )}

                            {!telemetryLoading && !telemetryError && telemetryRequested &&
                              telemetryReadings.filter((reading) => reading.device_id === device.id).length === 0 && (
                                <p className="telemetry-message">
                                  ยังไม่มีข้อมูลเซนเซอร์สำหรับอุปกรณ์นี้
                                </p>
                              )}

                            {!telemetryLoading && !telemetryError &&
                              telemetryReadings.some((reading) => reading.device_id === device.id) && (
                                <div className="telemetry-grid">
                                  {telemetryReadings
                                    .filter((reading) => reading.device_id === device.id)
                                    .map((reading) => {
                                      const metricLabels: Record<string, string> = {
                                        temperature: "อุณหภูมิอากาศ",
                                        humidity: "ความชื้นอากาศ",
                                        air_temperature: "อุณหภูมิอากาศ",
                                        air_humidity: "ความชื้นอากาศ",
                                        soil_moisture: "ความชื้นดิน",
                                        vpd: "VPD",
                                      };

                                      return (
                                        <article className="telemetry-card" key={reading.id}>
                                          <div className="telemetry-card-heading">
                                            <div>
                                              <h4>{metricLabels[reading.metric] ?? reading.metric}</h4>
                                              <p>เซนเซอร์ {reading.sensor_code}</p>
                                            </div>
                                            <span className="telemetry-quality">
                                              {reading.quality_status}
                                            </span>
                                          </div>
                                          <p className="telemetry-value">
                                            {Number.isFinite(reading.value)
                                              ? reading.value.toLocaleString("th-TH", {
                                                  maximumFractionDigits: 4,
                                                })
                                              : "—"}
                                            <span>{reading.unit || ""}</span>
                                          </p>
                                          <p className="telemetry-time">
                                            วัดเมื่อ:{" "}
                                            <time dateTime={reading.measured_at}>
                                              {formatThaiDate(reading.measured_at)}
                                            </time>
                                          </p>
                                        </article>
                                      );
                                    })}
                                </div>
                              )}
                          </section>
                          <section className="device-zone-assignment" aria-label={`กำหนด Zone ให้ ${device.name}`}>
                            <label htmlFor={`device-zone-${device.id}`}>Zone</label>
                            {!device.farm_id ? (
                              <p className="device-zone-note">ต้องผูกอุปกรณ์กับ Farm ก่อน จึงจะกำหนด Zone ได้</p>
                            ) : deviceZoneLoadErrors[device.farm_id] ? (
                              <p className="device-zone-error" role="alert">
                                โหลด Zone ไม่สำเร็จ: {deviceZoneLoadErrors[device.farm_id]}
                              </p>
                            ) : (
                              <>
                                <select
                                  id={`device-zone-${device.id}`}
                                  value={device.zone_id ?? ""}
                                  disabled={
                                    !authorizedDeviceTenant ||
                                    !["owner", "operator"].includes(authorizedDeviceTenant.role) ||
                                    Boolean(deviceZoneLoading[device.farm_id]) ||
                                    Boolean(deviceZoneSaving[device.id])
                                  }
                                  onChange={async (event) => {
                                    const nextZoneId = event.target.value || null;
                                    const currentTenantId = authorizedDeviceTenant?.id;
                                    if (
                                      !currentTenantId ||
                                      !["owner", "operator"].includes(authorizedDeviceTenant.role) ||
                                      !device.farm_id
                                    ) return;

                                    const allowedZones = deviceZonesByFarm[device.farm_id] ?? [];
                                    if (nextZoneId && !allowedZones.some((zone) => zone.id === nextZoneId)) {
                                      setDeviceZoneErrors((prev) => ({
                                        ...prev,
                                        [device.id]: "Zone ที่เลือกไม่อยู่ใน Farm ของอุปกรณ์",
                                      }));
                                      return;
                                    }

                                    setDeviceZoneSaving((prev) => ({ ...prev, [device.id]: true }));
                                    setDeviceZoneErrors((prev) => ({ ...prev, [device.id]: "" }));
                                    setDeviceZoneMessages((prev) => ({ ...prev, [device.id]: "" }));

                                    try {
                                      const updated = await deviceApi.assignZone(
                                        currentTenantId,
                                        device.id,
                                        nextZoneId,
                                      );
                                      if (tenantContextRef.current !== currentTenantId) return;

                                      setDevices((prev) =>
                                        prev.map((item) => item.id === updated.id ? updated : item),
                                      );
                                      setDeviceZoneMessages((prev) => ({
                                        ...prev,
                                        [device.id]: nextZoneId
                                          ? "บันทึก Zone สำเร็จ"
                                          : "ยกเลิกการกำหนด Zone แล้ว",
                                      }));
                                    } catch (error) {
                                      if (tenantContextRef.current !== currentTenantId) return;
                                      setDeviceZoneErrors((prev) => ({
                                        ...prev,
                                        [device.id]: error instanceof Error
                                          ? error.message
                                          : "บันทึก Zone ไม่สำเร็จ",
                                      }));
                                    } finally {
                                      setDeviceZoneSaving((prev) => ({ ...prev, [device.id]: false }));
                                    }
                                  }}
                                >
                                  <option value="">ยังไม่กำหนด Zone</option>
                                  {(deviceZonesByFarm[device.farm_id] ?? []).map((zone) => (
                                    <option key={zone.id} value={zone.id}>
                                      {zone.name}{zone.status === "disabled" ? " (ปิดใช้งาน)" : ""}
                                    </option>
                                  ))}
                                </select>
                                {deviceZoneLoading[device.farm_id] && (
                                  <p className="device-zone-note" role="status">กำลังโหลด Zone…</p>
                                )}
                                {!deviceZoneLoading[device.farm_id] &&
                                  !deviceZoneLoadErrors[device.farm_id] &&
                                  (deviceZonesByFarm[device.farm_id] ?? []).length === 0 && (
                                    <p className="device-zone-note">Farm นี้ยังไม่มี Zone</p>
                                  )}
                              </>
                            )}
                            {deviceZoneSaving[device.id] && (
                              <p className="device-zone-note" role="status">กำลังบันทึก…</p>
                            )}
                            {deviceZoneMessages[device.id] && (
                              <p className="device-zone-success" role="status">{deviceZoneMessages[device.id]}</p>
                            )}
                            {deviceZoneErrors[device.id] && (
                              <p className="device-zone-error" role="alert">{deviceZoneErrors[device.id]}</p>
                            )}
                          </section>
                          {canManageFarms && (
                            <button
                              type="button"
                              className="secondary-button"
                              onClick={() => {
                                setSelectedSensorDeviceId(device.id);
                                setSensorFormDeviceId(device.id);
                                setSensorFormMode("create");
                                setSensorEditing(null);
                                setSensorFormType("");
                                setSensorFormUnit("");
                                setSensorFormStatus("active");
                                setSensorFormError("");
                                setSelectedPage("sensors");
                              }}
                            >
                              เพิ่ม Sensor ในอุปกรณ์นี้
                            </button>
                          )}
                          <button
                            type="button"
                            className="secondary-button relay-panel-toggle"
                            aria-expanded={Boolean(relayPanelsOpen[device.id])}
                            onClick={() =>
                              setRelayPanelsOpen((previous) => ({
                                ...previous,
                                [device.id]: !previous[device.id],
                              }))
                            }
                          >
                            {relayPanelsOpen[device.id] ? "ซ่อนการควบคุม Relay" : "ควบคุม Relay"}
                          </button>
                          {relayPanelsOpen[device.id] && (
                          <section className="relay-control-panel" aria-label={`ควบคุม Relay ของ ${device.name}`}>
                            <div className="relay-panel-heading">
                              <h4>ควบคุมรีเลย์</h4>
                              <span>4 ช่อง</span>
                            </div>
                            <p className="relay-safety-note">
                              ส่งคำสั่งไปยัง API เท่านั้น ยังไม่มีการยืนยันว่ารีเลย์จริงทำงานแล้ว
                            </p>
                            {device.status !== "active" && (
                              <p className="relay-inline-warning" role="status">
                                ต้องเปิดใช้งานอุปกรณ์ก่อนจึงจะส่งคำสั่งได้
                              </p>
                            )}
                            {[1, 2, 3, 4].map((relay) => {
                              const key = `${device.id}:${relay}`;
                              const busy = relayBusyKey === key;
                              return (
                                <div className="relay-row" key={relay}>
                                  <div className="relay-identity">
                                    <span className="relay-name">Relay {relay}</span>
                                    <span
                                      className={`relay-status-led relay-led-${relayErrors[key] ? "error" : relayReportedStates[key] ?? "unknown"}`}
                                      role="img"
                                      aria-label={relayErrors[key]
                                        ? `Relay ${relay} เกิดข้อผิดพลาด`
                                        : relayReportedStates[key] === "on"
                                          ? `Relay ${relay} รายงานเปิดสำเร็จ`
                                          : relayReportedStates[key] === "off"
                                            ? `Relay ${relay} รายงานปิดสำเร็จ`
                                            : `Relay ${relay} ยังไม่ทราบสถานะ`}
                                      title={relayErrors[key] ? "เกิดข้อผิดพลาด" : relayReportedStates[key] === "on" ? "รายงานเปิดสำเร็จ" : relayReportedStates[key] === "off" ? "รายงานปิดสำเร็จ" : "ยังไม่ทราบสถานะ"}
                                    />
                                  </div>
                                  <div className="relay-actions">
                                    <button
                                      type="button"
                                      className="relay-button relay-button-on"
                                      disabled={device.status !== "active" || Boolean(relayBusyKey) || !authorizedDeviceTenant}
                                      onClick={async () => {
                                        if (relayBusyKey) return;
                                        const requestedTenantId = authorizedDeviceTenant?.id ?? "";
                                        const operationId = ++relayOperationRef.current;
                                        const isCurrentOperation = () =>
                                          relayOperationRef.current === operationId &&
                                          tenantContextRef.current === requestedTenantId;
                                        setRelayBusyKey(key);
                                        setRelayReportedStates((prev) => ({ ...prev, [key]: "unknown" }));
                                        setRelayErrors((prev) => ({ ...prev, [key]: "" }));
                                        setRelayMessages((prev) => ({ ...prev, [key]: "" }));
                                        try {
                                          const idempotencyKey = typeof crypto !== "undefined" && typeof crypto.randomUUID === "function"
                                            ? crypto.randomUUID()
                                            : `${Date.now()}-${relay}-on`;
                                          const result = await commandApi.createRelayCommand(
                                            requestedTenantId, device.id, relay, "on", idempotencyKey
                                          );
                                          if (!isCurrentOperation()) return;
                                          setRelayMessages((prev) => ({
                                            ...prev,
                                            [key]: `บันทึกคำสั่งเปิดแล้ว (${result.command.status})${result.duplicate ? " · คำสั่งเดิม" : ""} — ยังไม่ยืนยันสถานะฮาร์ดแวร์`,
                                          }));
                                          try {
                                            let observedCommand: DeviceCommand | undefined;
                                            let latestHistory: DeviceCommand[] = [];
                                            for (let attempt = 0; attempt < 12; attempt += 1) {
                                              if (attempt > 0) {
                                                await new Promise((resolve) => window.setTimeout(resolve, 1000));
                                                if (!isCurrentOperation()) return;
                                              }
                                              const history = await commandApi.history(requestedTenantId, device.id, 100);
                                              if (!isCurrentOperation()) return;
                                              latestHistory = history.commands;
                                              setCommandHistories((prev) => ({ ...prev, [device.id]: history.commands }));
                                              setCommandHistoryErrors((prev) => ({ ...prev, [device.id]: "" }));
                                              observedCommand = history.commands.find(
                                                (command) => command.id === result.command.id
                                              );
                                              if (
                                                observedCommand &&
                                                ["succeeded", "failed", "expired"].includes(observedCommand.status)
                                              ) break;
                                            }
                                            if (observedCommand) {


                                              const latestRelayCommand = latestHistory.find(
                                                (command) =>
                                                  command.command_type === "relay.set" &&
                                                  command.parameters?.relay === relay,
                                              );
                                              setRelayReportedStates((prev) => ({
                                                ...prev,
                                                [key]: latestRelayCommand?.status === "succeeded" &&
                                                  (latestRelayCommand.parameters?.state === "on" ||
                                                    latestRelayCommand.parameters?.state === "off")
                                                  ? latestRelayCommand.parameters.state
                                                  : "unknown",
                                              }));
                                              const commandStatus = observedCommand.status;
                                              const commandState = observedCommand.parameters?.state;
                                              setRelayErrors((prev) => ({
                                                ...prev,
                                                [key]: ["failed", "expired"].includes(commandStatus)
                                                  ? `คำสั่ง Relay สิ้นสุดด้วยสถานะ ${commandStatus}`
                                                  : "",
                                              }));
                                              const latestMatchesObservedCommand =
                                                latestRelayCommand?.id === observedCommand.id;

                                              setRelayMessages((prev) => ({
                                                ...prev,
                                                [key]: !latestMatchesObservedCommand
                                                  ? `คำสั่งที่ส่งมีสถานะ ${commandStatus} — สถานะรีเลย์อิงประวัติล่าสุด`
                                                  : commandStatus === "succeeded" &&
                                                      (commandState === "on" || commandState === "off")
                                                    ? `อุปกรณ์รายงานว่าคำสั่ง${commandState === "on" ? "เปิด" : "ปิด"}สำเร็จ — ไม่ใช่การวัดหน้าสัมผัสรีเลย์โดยตรง`
                                                    : ["failed", "expired"].includes(commandStatus)
                                                      ? `คำสั่งที่ส่งสิ้นสุดด้วยสถานะ ${commandStatus}`
                                                      : `คำสั่งที่ส่งยังไม่ยืนยันผล (${commandStatus}) — โปรดตรวจประวัติคำสั่งอีกครั้ง`,
                                              }));
                                            } else {
                                              setRelayMessages((prev) => ({
                                                ...prev,
                                                [key]: "ยังไม่พบคำสั่งเดิมในประวัติหลังตรวจสอบ 12 ครั้ง",
                                              }));
                                            }
                                          } catch (error) {
                                            if (!isCurrentOperation()) return;
                                            setCommandHistoryErrors((prev) => ({
                                              ...prev,
                                              [device.id]: error instanceof Error ? error.message : "โหลดประวัติคำสั่งไม่สำเร็จ",
                                            }));
                                            setRelayReportedStates((prev) => ({
                                              ...prev,
                                              [key]: "unknown",
                                            }));
                                            const message = error instanceof Error
                                              ? error.message
                                              : "โหลดประวัติคำสั่งไม่สำเร็จ";
                                            setRelayMessages((prev) => ({
                                              ...prev,
                                              [key]: `ตรวจสอบผลคำสั่งไม่สำเร็จ: ${message} — ยังไม่ทราบสถานะรีเลย์`,
                                            }));
                                          }
                                        } catch (error) {
                                            if (!isCurrentOperation()) return;
                                          setRelayErrors((prev) => ({
                                            ...prev,
                                            [key]: error instanceof Error ? error.message : "ส่งคำสั่งไม่สำเร็จ",
                                          }));
                                        } finally {
                                          if (relayOperationRef.current === operationId) setRelayBusyKey("");
                                        }
                                      }}
                                    >
                                      {busy ? "กำลังส่ง…" : "สั่งเปิด"}
                                    </button>
                                    <button
                                      type="button"
                                      className="relay-button relay-button-off"
                                      disabled={device.status !== "active" || Boolean(relayBusyKey) || !authorizedDeviceTenant}
                                      onClick={async () => {
                                        if (relayBusyKey) return;
                                        const requestedTenantId = authorizedDeviceTenant?.id ?? "";
                                        const operationId = ++relayOperationRef.current;
                                        const isCurrentOperation = () =>
                                          relayOperationRef.current === operationId &&
                                          tenantContextRef.current === requestedTenantId;
                                        setRelayBusyKey(key);
                                        setRelayReportedStates((prev) => ({ ...prev, [key]: "unknown" }));
                                        setRelayErrors((prev) => ({ ...prev, [key]: "" }));
                                        setRelayMessages((prev) => ({ ...prev, [key]: "" }));
                                        try {
                                          const idempotencyKey = typeof crypto !== "undefined" && typeof crypto.randomUUID === "function"
                                            ? crypto.randomUUID()
                                            : `${Date.now()}-${relay}-off`;
                                          const result = await commandApi.createRelayCommand(
                                            requestedTenantId, device.id, relay, "off", idempotencyKey
                                          );
                                          if (!isCurrentOperation()) return;
                                          setRelayMessages((prev) => ({
                                            ...prev,
                                            [key]: `บันทึกคำสั่งปิดแล้ว (${result.command.status})${result.duplicate ? " · คำสั่งเดิม" : ""} — ยังไม่ยืนยันสถานะฮาร์ดแวร์`,
                                          }));
                                          try {
                                            let observedCommand: DeviceCommand | undefined;
                                            let latestHistory: DeviceCommand[] = [];
                                            for (let attempt = 0; attempt < 12; attempt += 1) {
                                              if (attempt > 0) {
                                                await new Promise((resolve) => window.setTimeout(resolve, 1000));
                                                if (!isCurrentOperation()) return;
                                              }
                                              const history = await commandApi.history(requestedTenantId, device.id, 100);
                                              if (!isCurrentOperation()) return;
                                              latestHistory = history.commands;
                                              setCommandHistories((prev) => ({ ...prev, [device.id]: history.commands }));
                                              setCommandHistoryErrors((prev) => ({ ...prev, [device.id]: "" }));
                                              observedCommand = history.commands.find(
                                                (command) => command.id === result.command.id
                                              );
                                              if (
                                                observedCommand &&
                                                ["succeeded", "failed", "expired"].includes(observedCommand.status)
                                              ) break;
                                            }
                                            if (observedCommand) {

                                              const latestRelayCommand = latestHistory.find(
                                                (command) =>
                                                  command.command_type === "relay.set" &&
                                                  command.parameters?.relay === relay,
                                              );
                                              setRelayReportedStates((prev) => ({
                                                ...prev,
                                                [key]: latestRelayCommand?.status === "succeeded" &&
                                                  (latestRelayCommand.parameters?.state === "on" ||
                                                    latestRelayCommand.parameters?.state === "off")
                                                  ? latestRelayCommand.parameters.state
                                                  : "unknown",
                                              }));
                                              const commandStatus = observedCommand.status;
                                              const commandState = observedCommand.parameters?.state;
                                              setRelayErrors((prev) => ({
                                                ...prev,
                                                [key]: ["failed", "expired"].includes(commandStatus)
                                                  ? `คำสั่ง Relay สิ้นสุดด้วยสถานะ ${commandStatus}`
                                                  : "",
                                              }));
                                              const latestMatchesObservedCommand =
                                                latestRelayCommand?.id === observedCommand.id;

                                              setRelayMessages((prev) => ({
                                                ...prev,
                                                [key]: !latestMatchesObservedCommand
                                                  ? `คำสั่งที่ส่งมีสถานะ ${commandStatus} — สถานะรีเลย์อิงประวัติล่าสุด`
                                                  : commandStatus === "succeeded" &&
                                                      (commandState === "on" || commandState === "off")
                                                    ? `อุปกรณ์รายงานว่าคำสั่ง${commandState === "on" ? "เปิด" : "ปิด"}สำเร็จ — ไม่ใช่การวัดหน้าสัมผัสรีเลย์โดยตรง`
                                                    : ["failed", "expired"].includes(commandStatus)
                                                      ? `คำสั่งที่ส่งสิ้นสุดด้วยสถานะ ${commandStatus}`
                                                      : `คำสั่งที่ส่งยังไม่ยืนยันผล (${commandStatus}) — โปรดตรวจประวัติคำสั่งอีกครั้ง`,
                                              }));
                                            } else {
                                              setRelayMessages((prev) => ({
                                                ...prev,
                                                [key]: "ยังไม่พบคำสั่งเดิมในประวัติหลังตรวจสอบ 12 ครั้ง",
                                              }));
                                            }
                                          } catch (error) {
                                            if (!isCurrentOperation()) return;
                                            setCommandHistoryErrors((prev) => ({
                                              ...prev,
                                              [device.id]: error instanceof Error ? error.message : "โหลดประวัติคำสั่งไม่สำเร็จ",
                                            }));
                                            setRelayReportedStates((prev) => ({
                                              ...prev,
                                              [key]: "unknown",
                                            }));
                                            const message = error instanceof Error
                                              ? error.message
                                              : "โหลดประวัติคำสั่งไม่สำเร็จ";
                                            setRelayMessages((prev) => ({
                                              ...prev,
                                              [key]: `ตรวจสอบผลคำสั่งไม่สำเร็จ: ${message} — ยังไม่ทราบสถานะรีเลย์`,
                                            }));
                                          }
                                        } catch (error) {
                                            if (!isCurrentOperation()) return;
                                          setRelayErrors((prev) => ({
                                            ...prev,
                                            [key]: error instanceof Error ? error.message : "ส่งคำสั่งไม่สำเร็จ",
                                          }));
                                        } finally {
                                          if (relayOperationRef.current === operationId) setRelayBusyKey("");
                                        }
                                      }}
                                    >
                                      {busy ? "กำลังส่ง…" : "สั่งปิด"}
                                    </button>
                                  </div>
                                  {(relayMessages[key] || relayErrors[key]) && (
                                    <details className="relay-result-details">
                                      <summary>ดูผลคำสั่ง</summary>
                                      {relayMessages[key] && (
                                        <p className="relay-inline-success" role="status">
                                          {relayMessages[key]}
                                        </p>
                                      )}
                                      {relayErrors[key] && (
                                        <p className="relay-inline-error" role="alert">
                                          {relayErrors[key]}
                                        </p>
                                      )}
                                    </details>
                                  )}
                                </div>
                              );
                            })}
                            <details className="relay-history-details">
                              <summary>ดูประวัติคำสั่ง</summary>
                              <div className="relay-history-content">
                                <div className="relay-history-header">
                                  <h5>ประวัติคำสั่ง</h5>
                              <button
                                type="button"
                                className="relay-history-button"
                                disabled={Boolean(commandHistoryLoading[device.id]) || !authorizedDeviceTenant}
                                onClick={async () => {
                                  const requestedTenantId = authorizedDeviceTenant?.id ?? "";
                                  const operationId = ++historySequenceRef.current;
                                  historyOperationRef.current[device.id] = operationId;
                                  const isCurrentHistory = () =>
                                    historyOperationRef.current[device.id] === operationId &&
                                    tenantContextRef.current === requestedTenantId;

                                  setCommandHistoryLoading((prev) => ({ ...prev, [device.id]: true }));
                                  setCommandHistoryErrors((prev) => ({ ...prev, [device.id]: "" }));
                                  try {
                                    const history = await commandApi.history(requestedTenantId, device.id, 100);
                                    if (!isCurrentHistory()) return;
                                    setCommandHistoryErrors((prev) => ({
                                      ...prev,
                                      [device.id]: "",
                                    }));
                                    setCommandHistories((prev) => ({
                                      ...prev,
                                      [device.id]: history.commands.slice(0, 10),
                                    }));

                                    setRelayReportedStates((prev) => {
                                      const next = { ...prev };

                                      for (const relay of [1, 2, 3, 4]) {
                                        const key = `${device.id}:${relay}`;
                                        const latestCommand = history.commands.find(
                                          (command) =>
                                            command.command_type === "relay.set" &&
                                            command.parameters?.relay === relay,
                                        );

                                        next[key] =
                                          latestCommand?.status === "succeeded" &&
                                          (latestCommand.parameters?.state === "on" ||
                                            latestCommand.parameters?.state === "off")
                                            ? latestCommand.parameters.state
                                            : "unknown";
                                      }

                                      return next;
                                    });

                                    setRelayErrors((prev) => {
                                      const next = { ...prev };

                                      for (const relay of [1, 2, 3, 4]) {
                                        const key = `${device.id}:${relay}`;
                                        const latestCommand = history.commands.find(
                                          (command) =>
                                            command.command_type === "relay.set" &&
                                            command.parameters?.relay === relay,
                                        );

                                        next[key] =
                                          latestCommand &&
                                          ["failed", "expired"].includes(latestCommand.status)
                                            ? `คำสั่ง Relay สิ้นสุดด้วยสถานะ ${latestCommand.status}`
                                            : "";
                                      }

                                      return next;
                                    });
                                  } catch (error) {
                                    if (!isCurrentHistory()) return;
                                    setCommandHistoryErrors((prev) => ({
                                      ...prev,
                                      [device.id]: error instanceof Error ? error.message : "โหลดประวัติคำสั่งไม่สำเร็จ",
                                    }));
                                  } finally {
                                    if (isCurrentHistory()) {
                                      setCommandHistoryLoading((prev) => ({
                                        ...prev,
                                        [device.id]: false,
                                      }));
                                    }
                                  }
                                }}
                              >
                                {commandHistoryLoading[device.id] ? "กำลังโหลด…" : commandHistories[device.id] ? "รีเฟรชประวัติ" : "โหลดประวัติ"}
                              </button>
                            </div>
                            {commandHistoryErrors[device.id] && (
                              <p className="relay-inline-error" role="alert">{commandHistoryErrors[device.id]}</p>
                            )}
                            {commandHistories[device.id] && (
                              commandHistories[device.id].length === 0
                                ? <p className="relay-history-empty">ยังไม่มีประวัติคำสั่ง</p>
                                : <ul className="relay-history-list">
                                    {commandHistories[device.id].map((command) => (
                                      <li key={command.id}>
                                        <span>
                                          Relay {command.parameters.relay} · {command.parameters.state === "on" ? "สั่งเปิด" : "สั่งปิด"}
                                        </span>
                                        <span className="relay-command-status">{command.status}</span>
                                        <time dateTime={command.created_at}>{formatThaiDate(command.created_at)}</time>
                                      </li>
                                    ))}
                                  </ul>
                            )}
                              </div>
                            </details>
                          </section>
                          )}

                        </article>
                      );
                    })}
                  </div>
                )}
                <p className="farm-helper-text device-api-note">
                  สถานะ Relay แสดงผลตามรายงานคำสั่งจาก API ไม่ใช่การวัดสถานะฮาร์ดแวร์โดยตรง
                </p>

              </section>
            </div>

          ) : selectedPage === "sensors" ? (
            <section className="section-block device-management-panel">
              <div className="device-list-toolbar">
                <div>
                  <h2>Sensor Management</h2>
                  <p className="farm-helper-text">จัดการเซนเซอร์ภายในอุปกรณ์</p>
                </div>
                <button
                  className="secondary-button"
                  type="button"
                  disabled={sensorsLoading}
                  onClick={() => setSensorReloadKey((v) => v + 1)}
                >
                  รีเฟรช
                </button>
              </div>

              {sensorsError && <p role="alert" className="farm-message">{sensorsError}</p>}

              <label htmlFor="sensor-device-filter">กรองตามอุปกรณ์</label>
              <select
                id="sensor-device-filter"
                value={selectedSensorDeviceId}
                onChange={(e) => setSelectedSensorDeviceId(e.target.value)}
              >
                <option value="">อุปกรณ์ทั้งหมด</option>
                {sensorDevices.map((device) => (
                  <option key={device.id} value={device.id}>
                    {device.name} ({device.device_code})
                  </option>
                ))}
              </select>

              {authorizedDeviceTenant &&
                ["owner", "operator"].includes(authorizedDeviceTenant.role) && (
                <form
                  className="farm-crud-form"
                  onSubmit={(e) => {
                    e.preventDefault();
                    if (sensorSaving || !authorizedDeviceTenant) return;

                    const deviceId = sensorFormMode === "edit"
                      ? sensorEditing?.device_id
                      : sensorFormDeviceId;

                    if (!deviceId) {
                      setSensorFormError("กรุณาเลือกอุปกรณ์");
                      return;
                    }

                    setSensorSaving(true);
                    setSensorFormError("");

                    void (async () => {
                      try {
                        if (sensorFormMode === "edit" && sensorEditing) {
                          await sensorApi.update(
                            authorizedDeviceTenant.id,
                            deviceId,
                            sensorEditing.id,
                            {
                              measurement_type: sensorFormType.trim(),
                              unit: sensorFormUnit.trim(),
                              status: sensorFormStatus,
                            },
                          );
                        } else {
                          await sensorApi.create(
                            authorizedDeviceTenant.id,
                            deviceId,
                            {
                              measurement_type: sensorFormType.trim(),
                              unit: sensorFormUnit.trim(),
                            },
                          );
                        }

                        setSensorFormMode(null);
                        setSensorEditing(null);
                        setSensorFormType("");
                        setSensorFormUnit("");
                        setSensorFormStatus("active");
                        setSensorReloadKey((v) => v + 1);
                      } catch (error) {
                        setSensorFormError(
                          error instanceof Error ? error.message : "บันทึกไม่สำเร็จ",
                        );
                      } finally {
                        setSensorSaving(false);
                      }
                    })();
                  }}
                >
                  <h3>{sensorFormMode === "edit" ? "แก้ไข Sensor" : "เพิ่ม Sensor"}</h3>

                  {sensorFormMode !== "edit" && (
                    <>
                      <label htmlFor="sensor-device">อุปกรณ์</label>
                      <select
                        id="sensor-device"
                        value={sensorFormDeviceId}
                        onChange={(e) => setSensorFormDeviceId(e.target.value)}
                        required
                      >
                        <option value="">เลือกอุปกรณ์</option>
                        {sensorDevices.map((device) => (
                          <option key={device.id} value={device.id}>
                            {device.name} ({device.device_code})
                          </option>
                        ))}
                      </select>

                    </>
                  )}

                  <label htmlFor="sensor-type">Measurement Type</label>
                  <select
                    id="sensor-type"
                    value={sensorFormType}
                    onChange={(e) => {
                      const selected = SENSOR_MEASUREMENT_OPTIONS.find(
                        (option) => option.value === e.target.value,
                      );
                      setSensorFormType(e.target.value);
                      if (selected) setSensorFormUnit(selected.defaultUnit);
                    }}
                    required
                  >
                    <option value="">เลือกประเภทเซนเซอร์</option>
                    {SENSOR_MEASUREMENT_GROUPS.map((group) => (
                      <optgroup key={group.label} label={group.label}>
                        {group.options.map((option) => (
                          <option key={option.value} value={option.value}>
                            {option.label} ({option.value})
                          </option>
                        ))}
                      </optgroup>
                    ))}
                    {sensorFormType &&
                      !SENSOR_MEASUREMENT_OPTIONS.some(
                        (option) => option.value === sensorFormType,
                      ) && (
                        <option value={sensorFormType}>
                          ประเภทเดิม ({sensorFormType})
                        </option>
                      )}
                  </select>

                  <label htmlFor="sensor-unit">Unit</label>
                  <select
                    id="sensor-unit"
                    value={sensorFormUnit}
                    onChange={(e) => setSensorFormUnit(e.target.value)}
                    disabled={!sensorFormType}
                    required
                  >
                    <option value="">เลือกหน่วย</option>
                    {SENSOR_MEASUREMENT_OPTIONS
                      .find((option) => option.value === sensorFormType)
                      ?.units.map((unit) => (
                        <option key={unit} value={unit}>
                          {unit}
                        </option>
                      ))}
                    {sensorFormUnit &&
                      !SENSOR_MEASUREMENT_OPTIONS.some(
                        (option) =>
                          option.value === sensorFormType &&
                          option.units.some((unit) => unit === sensorFormUnit),
                      ) && (
                        <option value={sensorFormUnit}>
                          หน่วยเดิม ({sensorFormUnit})
                        </option>
                      )}
                  </select>

                  {sensorFormMode === "edit" && (
                    <>
                      <label htmlFor="sensor-status">สถานะ</label>
                      <select
                        id="sensor-status"
                        value={sensorFormStatus}
                        onChange={(e) => setSensorFormStatus(e.target.value as SensorStatus)}
                      >
                        <option value="active">Active</option>
                        <option value="disabled">Disabled</option>
                        <option value="retired">Retired</option>
                      </select>
                    </>
                  )}

                  {sensorFormError && <p role="alert">{sensorFormError}</p>}

                  <button type="submit" disabled={sensorSaving}>
                    {sensorSaving ? "กำลังบันทึก..." : "บันทึก"}
                  </button>
                  <button
                    type="button"
                    className="secondary-button"
                    onClick={() => {
                      setSensorFormMode(null);
                      setSensorEditing(null);
                      setSensorFormError("");
                    }}
                  >
                    ยกเลิก
                  </button>
                </form>
              )}

              {sensorsLoading ? (
                <p className="farm-list-empty">กำลังโหลด Sensor...</p>
              ) : (
                <div className="device-list">
                  {sensors
                    .filter((sensor) =>
                      !selectedSensorDeviceId || sensor.device_id === selectedSensorDeviceId
                    )
                    .map((sensor) => {
                      const device = sensorDevices.find((d) => d.id === sensor.device_id);
                      return (
                        <article className="device-card" key={sensor.id}>
                          <div className="device-card-heading">
                            <div>
                              <h3>{sensor.sensor_code}</h3>
                              <p>{device?.name ?? sensor.device_id}</p>
                            </div>
                            <span>{sensor.status}</span>
                          </div>
                          <div className="device-card-details">
                            <p>Measurement: {sensor.measurement_type}</p>
                            <p>Unit: {sensor.unit}</p>
                            <p>Created: {new Date(sensor.created_at).toLocaleString("th-TH")}</p>
                          </div>
                          {authorizedDeviceTenant &&
                            ["owner", "operator"].includes(authorizedDeviceTenant.role) &&
                            sensor.status !== "retired" && (
                            <button
                              className="secondary-button"
                              type="button"
                              onClick={() => {
                                setSensorEditing(sensor);
                                setSensorFormMode("edit");
                                setSensorFormType(sensor.measurement_type);
                                setSensorFormUnit(sensor.unit);
                                setSensorFormStatus(sensor.status);
                                setSensorFormError("");
                              }}
                            >
                              แก้ไข
                            </button>
                          )}
                        </article>
                      );
                    })}
                  {sensors.filter((sensor) =>
                    !selectedSensorDeviceId || sensor.device_id === selectedSensorDeviceId
                  ).length === 0 && (
                    <p className="farm-list-empty">ไม่พบ Sensor ในอุปกรณ์ที่เลือก</p>
                  )}
                </div>
              )}
            </section>
          ) : (
            <section className="section-block destination-panel">
              <div className="destination-icon" aria-hidden="true">
                {navigation.flatMap((group) => group.items).find((item) => item.id === selectedPage)?.icon ?? "◫"}
              </div>
              <h2>{page.title}</h2>
              <p>{page.description}</p>
              <span className="empty-state-label">
                <span className="status-dot status-dot-muted" />
                หน้านี้ยังไม่มีข้อมูลเชื่อมต่อหรือฟังก์ชันจัดการ
              </span>
              <button
                className="secondary-button"
                type="button"
                onClick={() => navigate("dashboard")}
              >
                กลับสู่ Dashboard
              </button>
            </section>
          )}

          <footer className="page-footer">
            <span>Smart Farm System V.1</span>
            <span>แสดงเฉพาะข้อมูลที่ระบบยืนยันได้</span>
          </footer>
        </div>
      </main>

      <nav className="mobile-bottom-nav" aria-label="เมนูมือถือ">
        {[
          { id: "dashboard", label: "หน้าหลัก", icon: "⌂" },
          { id: "zones", label: "โซน", icon: "▦" },
          { id: "devices", label: "อุปกรณ์", icon: "▣" },
          { id: "alerts", label: "แจ้งเตือน", icon: "♧" },
          { id: "settings", label: "บัญชี", icon: "◉" },
        ].map((item) => (
          <button
            className={`mobile-nav-item ${
              selectedPage === item.id ? "active" : ""
            }`}
            key={item.id}
            type="button"
            onClick={() => navigate(item.id)}
            aria-current={selectedPage === item.id ? "page" : undefined}
          >
            <span aria-hidden="true">{item.icon}</span>
            <small>{item.label}</small>
          </button>
        ))}
      </nav>
    </div>
  );
}
