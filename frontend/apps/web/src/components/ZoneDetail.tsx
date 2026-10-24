import { useState } from "react";
import type { ZoneDetailData } from "../types/zone";

type ZoneTab =
  | "overview"
  | "sensors"
  | "devices"
  | "history"
  | "settings";

const tabs: { id: ZoneTab; label: string }[] = [
  { id: "overview", label: "ภาพรวม" },
  { id: "sensors", label: "เซนเซอร์" },
  { id: "devices", label: "อุปกรณ์" },
  { id: "history", label: "กราฟย้อนหลัง" },
  { id: "settings", label: "การตั้งค่า" },
];

const sensorMetrics = [
  { id: "air_temperature", label: "อุณหภูมิอากาศ" },
  { id: "air_humidity", label: "ความชื้นอากาศ" },
  { id: "soil_moisture", label: "ความชื้นดิน" },
  { id: "vpd", label: "VPD" },
] as const;

interface ZoneDetailProps {
  data: ZoneDetailData;
}

export default function ZoneDetail({ data }: ZoneDetailProps) {
  const [activeTab, setActiveTab] = useState<ZoneTab>("overview");

  return (
    <section className="section-block zone-detail-workspace">
      <div className="section-heading">
        <div>
          <h2>{data.zone.name}</h2>
          <p>{data.zone.description || "รายละเอียดโซนเพาะปลูก"}</p>
        </div>
        <span className="source-label">Zone Detail</span>
      </div>

      <div className="zone-tabs" role="tablist" aria-label="ส่วนรายละเอียดโซน">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            id={`zone-tab-${tab.id}`}
            className={`zone-tab ${activeTab === tab.id ? "active" : ""}`}
            type="button"
            role="tab"
            aria-selected={activeTab === tab.id}
            aria-controls="zone-tab-panel"
            onClick={() => setActiveTab(tab.id)}
          >
            {tab.label}
          </button>
        ))}
      </div>

      <div
        id="zone-tab-panel"
        className="zone-tab-panel"
        role="tabpanel"
        aria-labelledby={`zone-tab-${activeTab}`}
      >
        {activeTab === "overview" && (
          <>
            <div className="zone-data-heading">
              <h3>สภาพแวดล้อม</h3>
              <span className="zone-source-tag">ข้อมูลจากเซนเซอร์</span>
            </div>

            <div className="zone-detail-metrics">
              {sensorMetrics.map((metric) => {
                const reading = data.sensors?.readings.find(
                  (item) => item.metric === metric.id,
                );

                return (
                  <article className="zone-detail-metric" key={metric.id}>
                    <span>{metric.label}</span>
                    <strong>
                      {reading ? (
                        <>
                          {reading.value} <small>{reading.unit}</small>
                        </>
                      ) : (
                        "—"
                      )}
                    </strong>
                    <small className="zone-metric-note">
                      {reading
                        ? `ข้อมูลล่าสุด ${reading.recordedAt}`
                        : "ยังไม่มีข้อมูลเซนเซอร์"}
                    </small>
                  </article>
                );
              })}
            </div>

            <div className="zone-data-heading zone-user-data-heading">
              <h3>ข้อมูลดินที่บันทึกโดยผู้ใช้</h3>
              <span className="zone-source-tag zone-source-tag-user">
                User-recorded
              </span>
            </div>

            {data.npkPhRecords.length === 0 ? (
              <div className="zone-tab-empty">
                <p>ยังไม่มีรายการบันทึก NPK หรือ pH</p>
              </div>
            ) : (
              <div className="zone-detail-metrics zone-detail-metrics-two">
                {data.npkPhRecords.map((record) => (
                  <article className="zone-detail-metric" key={record.id}>
                    <span>{record.recordedAt}</span>
                    <strong>
                      NPK: {record.nitrogen ?? "—"} /{" "}
                      {record.phosphorus ?? "—"} / {record.potassium ?? "—"}
                    </strong>
                    <small className="zone-metric-note">
                      pH: {record.ph ?? "—"}
                      {record.note ? ` · ${record.note}` : ""}
                    </small>
                  </article>
                ))}
              </div>
            )}
          </>
        )}

        {activeTab === "sensors" && (
          <div className="zone-tab-empty">
            <h3>ข้อมูลเซนเซอร์</h3>
            <p>
              {data.sensors && data.sensors.readings.length > 0
                ? `มีข้อมูลเซนเซอร์ ${data.sensors.readings.length} รายการ`
                : "ยังไม่มีข้อมูลเซนเซอร์จริงสำหรับโซนนี้"}
            </p>
          </div>
        )}

        {activeTab === "devices" && (
          data.devices.length === 0 ? (
            <div className="zone-tab-empty">
              <h3>อุปกรณ์ในโซน</h3>
              <p>ยังไม่มีข้อมูลอุปกรณ์สำหรับโซนนี้</p>
            </div>
          ) : (
            <div className="zone-detail-metrics">
              {data.devices.map((device) => (
                <article className="zone-detail-metric" key={device.id}>
                  <span>{device.type}</span>
                  <strong>{device.name}</strong>
                  <small className="zone-metric-note">
                    {device.status || "ยังไม่มีสถานะ"}
                  </small>
                </article>
              ))}
            </div>
          )
        )}

        {activeTab === "history" && (
          <div className="zone-tab-empty">
            <h3>กราฟย้อนหลัง</h3>
            <p>ส่วนกราฟจะแสดงเมื่อมีข้อมูลย้อนหลังจริงพร้อมใช้งาน</p>
          </div>
        )}

        {activeTab === "settings" && (
          <div className="zone-tab-empty">
            <h3>การตั้งค่าโซน</h3>
            <p>
              การตั้งค่ายังไม่เปิดใช้งานจนกว่าจะมีการเชื่อมต่อระบบที่เกี่ยวข้อง
            </p>
          </div>
        )}
      </div>
    </section>
  );
}
