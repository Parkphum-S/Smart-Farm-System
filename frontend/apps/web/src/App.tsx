import { useEffect, useState } from "react";
import { ApiError, farmApi } from "./services/api";

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
  const [farms, setFarms] = useState<
    { id: string; name: string; timezone: string; created_at: string; updated_at: string }[]
  >([]);
  const [farmsLoading, setFarmsLoading] = useState(false);
  const [farmsError, setFarmsError] = useState("");
  const [farmsRequested, setFarmsRequested] = useState(false);
  const [farmsReloadKey, setFarmsReloadKey] = useState(0);
  const [copiedField, setCopiedField] = useState("");
  const [selectedFarm, setSelectedFarm] = useState<{
    id: string; name: string; timezone: string;
    created_at: string; updated_at: string;
    displayId: string;
  } | null>(null);


  const zoneTabs = [
    { id: "overview", label: "ภาพรวม" },
    { id: "sensors", label: "เซนเซอร์" },
    { id: "devices", label: "อุปกรณ์" },
    { id: "history", label: "กราฟย้อนหลัง" },
    { id: "settings", label: "การตั้งค่า" },
  ];



  useEffect(() => {
    if (selectedPage !== "farms" || !tenantId.trim()) {
      setFarms([]);
      setFarmsError("");
      setFarmsRequested(false);
      return;
    }

    if (!isTenantUuid(tenantId)) {
      setFarms([]);
      setFarmsError("Tenant ID ต้องเป็น UUID รูปแบบเต็ม");
      setFarmsRequested(false);
      setFarmsLoading(false);
      return;
    }

    let cancelled = false;
    setFarmsLoading(true);
    setFarmsError("");
    setFarmsRequested(true);

    farmApi.list(tenantId.trim())
      .then((result) => {
        if (!cancelled) {
          setFarms(result);
          try {
            localStorage.setItem("smartfarm.selectedTenantId", tenantId.trim());
            setTenantHistory((previous) => {
              const next = [
                tenantId.trim(),
                ...previous.filter(
                  (value) => value.toLowerCase() !== tenantId.trim().toLowerCase(),
                ),
              ].slice(0, 10);
              try {
                localStorage.setItem("smartfarm.tenantHistory", JSON.stringify(next));
              } catch {
                // Keep the current session usable if storage is unavailable.
              }
              return next;
            });
          } catch {
            // Keep the current session usable if storage is unavailable.
          }
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
  }, [selectedPage, tenantId, farmsReloadKey]);

  const page = pageTitles[selectedPage] ?? pageTitles.dashboard;

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
            <span className="connection-pill">
              <span className="status-dot status-dot-muted" />
              รอเชื่อมต่อข้อมูล
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
                    <p>ข้อมูลจาก Farm API ตามสิทธิ์ของ Tenant ที่ระบุ</p>
                  </div>
                  <span className="section-note">
                    <span className={`status-dot ${farmsError ? "status-dot-muted" : ""}`} />
                    {farmsLoading ? "กำลังโหลด" : farmsError ? "โหลดข้อมูลไม่สำเร็จ" : farmsRequested ? "เชื่อมต่อ API แล้ว" : "รอ Tenant ID"}
                  </span>
                </div>

                <form
                  className="farm-tenant-form"
                  onSubmit={(event) => {
                    event.preventDefault();
                    const input = event.currentTarget.querySelector("input");
                    if (input) {
                      const value = input.value.trim();
                      setTenantId(value);
                      if (value) setFarmsReloadKey((key) => key + 1);
                    }
                  }}
                >
                  <label htmlFor="farm-tenant-id">Tenant ID</label>
                  <div className="farm-tenant-controls">
                    <input
                      id="farm-tenant-id"
                      type="text"
                      value={tenantId}
                      onChange={(event) => setTenantId(event.target.value)}
                      placeholder="ระบุ Tenant ID ที่บัญชีนี้มีสิทธิ์เข้าถึง"
                      autoComplete="off"
                      required
                    />
                    <button className="primary-button" type="submit" disabled={farmsLoading || !isTenantUuid(tenantId)}>
                      {farmsLoading ? "กำลังโหลด…" : "โหลดรายการฟาร์ม"}
                    </button>
                  </div>
                  <p className="farm-helper-text">
                    ใช้ Tenant ID ที่ได้รับอนุญาตเท่านั้น ระบบจะส่ง Access Token ผ่าน API service เดิม
                  </p>
                </form>

                <div className="tenant-history-panel">
                  <div className="tenant-history-heading">
                    <strong>ประวัติ Tenant ID</strong>
                    <span>{tenantHistory.length}/10 รายการ</span>
                  </div>
                  {tenantHistory.length > 0 ? (
                    <div className="tenant-history-list">
                      {tenantHistory.map((savedTenantId) => (
                        <button
                          key={savedTenantId}
                          className={`tenant-history-item ${
                            tenantId.toLowerCase() === savedTenantId.toLowerCase()
                              ? "active"
                              : ""
                          }`}
                          type="button"
                          onClick={() => {
                            setTenantId(savedTenantId);
                            setFarmsReloadKey((key) => key + 1);
                          }}
                          title={savedTenantId}
                        >
                          <span>{formatTenantDisplayId(savedTenantId)}</span>
                          {tenantId.toLowerCase() === savedTenantId.toLowerCase()
                            ? <span>กำลังเลือก</span>
                            : <span>เลือก Tenant</span>}
                        </button>
                      ))}
                    </div>
                  ) : (
                    <p className="farm-helper-text">
                      ประวัติจะปรากฏหลังโหลดรายการฟาร์มสำเร็จ
                    </p>
                  )}
                  <div className="tenant-history-actions">
                    <button
                      className="secondary-button"
                      type="button"
                      disabled={!tenantId}
                      onClick={() => {
                        try {
                          localStorage.removeItem("smartfarm.selectedTenantId");
                        } catch {
                          // Continue clearing the in-memory selection.
                        }
                        setTenantId("");
                        setFarms([]);
                        setFarmsError("");
                        setFarmsRequested(false);
                        setFarmsLoading(false);
                        setSelectedFarm(null);
                        setCopiedField("");
                      }}
                    >
                      ยกเลิกการเลือก Tenant
                    </button>
                    <button
                      className="farm-copy-button"
                      type="button"
                      disabled={tenantHistory.length === 0}
                      onClick={() => {
                        try {
                          localStorage.removeItem("smartfarm.tenantHistory");
                        } catch {
                          // Continue clearing the in-memory history.
                        }
                        setTenantHistory([]);
                      }}
                    >
                      ล้างประวัติ
                    </button>
                  </div>
                </div>

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
                      onClick={() => navigate("farms")}
                    >
                      ← กลับรายการฟาร์ม
                    </button>
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
                    <span className="status-dot status-dot-muted" />
                    ยังไม่เชื่อมต่อ Zone API
                  </span>
                </div>

                <div className="zone-context-panel">
                  <div className="zone-context-main">
                    <span className="zone-context-icon" aria-hidden="true">⌂</span>
                    <div>
                      <span className="zone-context-label">ฟาร์มที่เลือก</span>
                      <strong>
                        {selectedFarm ? selectedFarm.name : "ยังไม่ได้เลือกฟาร์ม"}
                      </strong>
                      <small>
                        {selectedFarm
                          ? selectedFarm.timezone
                          : "เลือกฟาร์มก่อนเพื่อดูบริบทการจัดการโซน"}
                      </small>
                    </div>
                  </div>
                  <button
                    className="secondary-button"
                    type="button"
                    onClick={() => navigate("farms")}
                  >
                    {selectedFarm ? "เปลี่ยนฟาร์ม" : "ไปยัง Farm Management"}
                  </button>
                </div>

                <div className="zone-tenant-context">
                  <span>Tenant</span>
                  <code>{formatTenantDisplayId(tenantId)}</code>
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
                  />
                </label>

                <div className="zone-list-empty">
                  <span className="zone-empty-symbol" aria-hidden="true">▦</span>
                  <h3>
                    {zoneSearch.trim()
                      ? "ยังไม่สามารถค้นหาโซนได้"
                      : "ยังไม่มีข้อมูลโซนจากระบบ"}
                  </h3>
                  <p>
                    {zoneSearch.trim()
                      ? "ช่องค้นหาพร้อมใช้งานเมื่อเชื่อมต่อ Zone API และมีรายการโซนจริง"
                      : "ขณะนี้ Backend ยังไม่มี Zone API สำหรับดึงรายการโซน จึงยังไม่สามารถแสดงหรือจัดการโซนจริงได้"}
                  </p>
                  <span className="zone-api-notice">
                    ไม่มีการสร้างข้อมูลจำลองหรือส่งคำขอไปยัง API ที่ยังไม่รองรับ
                  </span>
                </div>
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
