import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { ApiError, authApi, commandApi, deviceApi, farmApi, zoneApi } from "./services/api";
import type { Farm, TenantAccess } from "./services/api";
import type { DeviceCommand } from "./services/api";
import type { Device } from "./services/api";
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

const metrics = [
  { label: "โซนทั้งหมด", icon: "▦", unit: "โซน" },
  { label: "อุปกรณ์ออนไลน์", icon: "▣", unit: "อุปกรณ์" },
  { label: "Gateway ออนไลน์", icon: "⌁", unit: "Gateway" },
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

function formatTenantDisplayId(tenantId: string): string {
  if (!isTenantUuid(tenantId)) {
    return "ไม่มี Tenant UUID ที่ถูกต้อง";
  }

  return `TID${tenantId.replace(/-/g, "").slice(-4)}`;
}

export default function App() {
  const [selectedPage, setSelectedPage] = useState("dashboard");
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [selectedRange, setSelectedRange] = useState("24 ชั่วโมง");
  const [selectedVariable, setSelectedVariable] = useState("อุณหภูมิ");
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

  const [farms, setFarms] = useState<
    { id: string; name: string; timezone: string; created_at: string; updated_at: string }[]
  >([]);
  const [farmsLoading, setFarmsLoading] = useState(false);
  const [farmsError, setFarmsError] = useState("");
  const [farmsRequested, setFarmsRequested] = useState(false);
  const [farmsReloadKey, setFarmsReloadKey] = useState(0);
  const [farmFormMode, setFarmFormMode] = useState<"create" | "edit" | null>(null);
  const [farmName, setFarmName] = useState("");
  const [farmTimezone, setFarmTimezone] = useState("Asia/Bangkok");
  const [farmSaving, setFarmSaving] = useState(false);
  const [farmActionError, setFarmActionError] = useState("");
  const [farmActionMessage, setFarmActionMessage] = useState("");
  const [devices, setDevices] = useState<Device[]>([]);
  const [devicesLoading, setDevicesLoading] = useState(false);
  const [devicesError, setDevicesError] = useState("");
  const [devicesRequested, setDevicesRequested] = useState(false);
  const [devicesReloadKey, setDevicesReloadKey] = useState(0);
  const [copiedField, setCopiedField] = useState("");

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

  const [selectedFarm, setSelectedFarm] = useState<{
    id: string; name: string; timezone: string;
    created_at: string; updated_at: string;
    displayId: string;
  } | null>(null);

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
      selectedPage !== "farms" ||
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
  }, [selectedPage, tenantId, authorizedTenants, tenantListLoading, devicesReloadKey]);

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
              <section className="welcome-banner">
                <div className="welcome-content">
                  <span className="welcome-kicker">
                    <span className="welcome-kicker-dot" />
                    FARM OVERVIEW
                  </span>
                  <h2>จัดการฟาร์มอย่างมั่นใจ<br />ในทุกวัน</h2>
                  <p>
                    รวมข้อมูลสภาพแวดล้อม โซนเพาะปลูก
                    และอุปกรณ์ไว้ในหน้าจอเดียว
                  </p>
                  <button
                    className="primary-button"
                    type="button"
                    onClick={() => navigate("zones")}
                  >
                    ดูโซนเพาะปลูก <span aria-hidden="true">→</span>
                  </button>
                </div>
                <div className="welcome-art" aria-hidden="true">
                  <div className="art-sun" />
                  <div className="art-hill art-hill-back" />
                  <div className="art-hill art-hill-front" />
                  <div className="art-greenhouse">
                    <div className="greenhouse-roof" />
                    <div className="greenhouse-body">
                      <span /><span /><span />
                    </div>
                  </div>
                  <div className="art-plant art-plant-one">♧</div>
                  <div className="art-plant art-plant-two">♧</div>
                </div>
              </section>

              <section className="section-block">
                <div className="section-heading">
                  <div>
                    <h2>สถานะฟาร์ม</h2>
                    <p>สรุปสถานะจากข้อมูลที่ระบบได้รับ</p>
                  </div>
                  <span className="section-note">
                    <span className="status-dot status-dot-muted" />
                    ยังไม่มีข้อมูลจริง
                  </span>
                </div>

                <div className="metric-grid">
                  {metrics.map((metric) => (
                    <article className="metric-card" key={metric.label}>
                      <div className="metric-card-top">
                        <span className="metric-icon" aria-hidden="true">
                          {metric.icon}
                        </span>
                        <span className="metric-more" aria-hidden="true">···</span>
                      </div>
                      <p className="metric-label">{metric.label}</p>
                      <div className="metric-value-row">
                        <strong>—</strong>
                        <span>{metric.unit}</span>
                      </div>
                      <p className="metric-footnote">รอข้อมูลจากระบบ</p>
                    </article>
                  ))}
                </div>
              </section>

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
                      <strong>— <small>°C</small></strong>
                      <span>ยังไม่มีข้อมูลสภาพอากาศ</span>
                    </div>
                  </div>
                  <div className="weather-detail-grid">
                    {[
                      ["ความชื้นสัมพัทธ์", "%", "◌"],
                      ["PM2.5", "µg/m³", "◉"],
                      ["ความเร็วลม", "m/s", "↝"],
                      ["ทิศทางลม", "", "⌖"],
                    ].map(([label, unit, icon]) => (
                      <div className="weather-detail" key={label}>
                        <span className="weather-detail-icon">{icon}</span>
                        <span className="weather-detail-copy">
                          <small>{label}</small>
                          <strong>— <small>{unit}</small></strong>
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              </section>

              <section className="section-block">
                <div className="section-heading">
                  <div>
                    <h2>ภาพรวมโซนเพาะปลูก</h2>
                    <p>เลือกโซนเพื่อดูค่าเซนเซอร์และอุปกรณ์ที่เกี่ยวข้อง</p>
                  </div>
                  <button
                    className="text-button"
                    type="button"
                    onClick={() => navigate("zones")}
                  >
                    ดูโซนทั้งหมด <span aria-hidden="true">→</span>
                  </button>
                </div>

                <div className="zone-empty-panel">
                  <div className="empty-illustration" aria-hidden="true">
                    <span>♧</span>
                  </div>
                  <h3>ยังไม่มีข้อมูลโซน</h3>
                  <p>
                    เมื่อเชื่อมต่อข้อมูลฟาร์มแล้ว
                    ค่าจากเซนเซอร์และสถานะอุปกรณ์จะแสดงที่นี่
                  </p>
                  <button
                    className="secondary-button"
                    type="button"
                    onClick={() => navigate("zones")}
                  >
                    ไปยัง Zone Management
                  </button>
                </div>
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

                  <div className="chart-empty">
                    <div className="chart-grid-lines" aria-hidden="true">
                      <span /><span /><span /><span />
                    </div>
                    <div className="chart-empty-content">
                      <span className="chart-empty-icon" aria-hidden="true">⌁</span>
                      <strong>ยังไม่มีข้อมูลกราฟ</strong>
                      <span>
                        {selectedVariable} · {selectedRange}
                      </span>
                      <small>จะแสดงกราฟเมื่อมีข้อมูลย้อนหลังที่ใช้งานได้</small>
                    </div>
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
                  <span className="section-note">
                    <span className={`status-dot ${farmsError ? "status-dot-muted" : ""}`} />
                    {farmsLoading ? "กำลังโหลด" : farmsError ? "โหลดข้อมูลไม่สำเร็จ" : farmsRequested ? "เชื่อมต่อ API แล้ว" : "รอเลือก Tenant"}
                  </span>
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
                      setCopiedField("");
                      setFarmFormMode(null);
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

                {canManageFarms && (
                  <form
                    className="farm-crud-form"
                    onSubmit={async (event) => {
                      event.preventDefault();
                      if (farmSaving || !tenantId) return;
                      const name = farmName.trim();
                      const timezone = farmTimezone.trim();
                      if (!name || !timezone) {
                        setFarmActionError("กรุณากรอกชื่อฟาร์มและเขตเวลา");
                        return;
                      }
                      setFarmSaving(true);
                      setFarmActionError("");
                      setFarmActionMessage("");
                      try {
                        const created = await farmApi.create(tenantId, { name, timezone });
                        const displayId = `FARM-${String(farms.length + 1).padStart(2, "0")}`;
                        setSelectedFarm({ ...created, displayId });
                        setFarmName("");
                        setFarmTimezone("Asia/Bangkok");
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
                    <h3>เพิ่มฟาร์ม</h3>
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
                    {farmActionError && <p className="farm-message-error" role="alert">{farmActionError}</p>}
                    <div className="farm-crud-actions">
                      <button className="primary-button" type="submit" disabled={farmSaving}>
                        {farmSaving ? "กำลังบันทึก…" : "สร้างฟาร์ม"}
                      </button>
                    </div>
                  </form>
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
                          setCopiedField("");
                          navigate("farm-detail");
                        }}
                        aria-label={`จัดการฟาร์ม ${farm.name}`}
                      >
                        <span className="farm-card-icon" aria-hidden="true">⌂</span>
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
                    <form
                      className="farm-crud-form"
                      onSubmit={async (event) => {
                        event.preventDefault();
                        if (farmSaving || !selectedFarm || !tenantId) return;
                        const name = farmName.trim();
                        const timezone = farmTimezone.trim();
                        if (!name || !timezone) {
                          setFarmActionError("กรุณากรอกชื่อฟาร์มและเขตเวลา");
                          return;
                        }
                        setFarmSaving(true);
                        setFarmActionError("");
                        setFarmActionMessage("");
                        try {
                          const updated = await farmApi.update(
                            tenantId,
                            selectedFarm.id,
                            { name, timezone },
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
                      <h3>แก้ไขข้อมูลฟาร์ม</h3>
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
                  )}
                  {farmActionMessage && <div className="farm-message" role="status">{farmActionMessage}</div>}
                  {farmActionError && farmFormMode !== "edit" && <div className="farm-message farm-message-error" role="alert">{farmActionError}</div>}

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
                  <p className="farm-helper-text">
                    หน้า Zone Management ปัจจุบันยังไม่มีข้อมูลโซนจริงเชื่อมต่อจาก API
                  </p>
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
                  <span className="section-note">
                    <span className={`status-dot ${zonesError ? "status-dot-muted" : ""}`} />
                    {zonesLoading ? "กำลังโหลด" : zonesError ? "โหลดข้อมูลไม่สำเร็จ" : zonesRequested ? "เชื่อมต่อ Zone API แล้ว" : "รอ Tenant และ Farm"}
                  </span>
                </div>

                <div className="zone-context-panel">
                  <div className="zone-context-main">
                    <span className="zone-context-icon" aria-hidden="true">⌂</span>
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
                      {canManage && selectedFarm && (
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
                              setZonesReloadKey((key) => key + 1);
                            } catch (error) {
                              setZoneFormError(error instanceof Error ? error.message : "บันทึกข้อมูลโซนไม่สำเร็จ");
                            } finally {
                              setZoneSaving(false);
                            }
                          }}
                        >
                          <h3>{editingZoneId ? "แก้ไขโซน" : "เพิ่มโซนใหม่"}</h3>
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
                                }}
                              >ยกเลิก</button>
                            )}
                          </div>
                        </form>
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
                          <p>{canManage ? "เพิ่มโซนผ่านแบบฟอร์มด้านบนได้" : "บัญชีนี้มีสิทธิ์ดูข้อมูลเท่านั้น"}</p>
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
                              {canManage && (
                                <div className="zone-card-actions">
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
                                </div>
                              )}
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

                <div className="device-list-toolbar">
                  <span>
                    {devicesRequested && !devicesLoading && !devicesError
                      ? `${devices.length} อุปกรณ์`
                      : "รายการอุปกรณ์"}
                  </span>
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

                {!devicesError && !devicesLoading && devicesRequested && devices.length === 0 && (
                  <div className="farm-list-empty">
                    <span className="zone-empty-symbol" aria-hidden="true">▣</span>
                    <h3>ไม่พบรายการอุปกรณ์</h3>
                    <p>API ไม่พบอุปกรณ์สำหรับ Tenant นี้ หรือยังไม่มีข้อมูลอุปกรณ์</p>
                  </div>
                )}

                {!devicesError && !devicesLoading && devices.length > 0 && (
                  <div className="device-list" aria-label="รายการอุปกรณ์">
                    {devices.map((device) => {
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
