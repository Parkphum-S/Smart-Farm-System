import { useCallback, useEffect, useState, type FormEvent } from "react";
import { ApiError, authApi, session, type AuthUser } from "./services/api";
import type { ReactNode } from "react";

type AuthStatus =
  | "checking"
  | "anonymous"
  | "transitioning"
  | "authenticated";

interface AuthGateProps {
  children: ReactNode;
}

interface SplashScreenProps {
  message: string;
}

function SplashScreen({ message }: SplashScreenProps) {
  return (
    <main className="auth-screen auth-splash" aria-live="polite">
      <section className="auth-brand auth-splash-content">
        <span className="auth-logo" aria-label="Smart Farm logo">
          SF
        </span>

        <p className="auth-eyebrow">SMART FARM MANAGEMENT</p>
        <h1>Smart Farm</h1>
        <p>System V.1</p>

        <span className="auth-spinner" aria-hidden="true" />
        <span className="auth-muted">{message}</span>
      </section>

      <span className="auth-splash-footer">
        SMART FARM SYSTEM
      </span>
    </main>
  );
}

export default function AuthGate({ children }: AuthGateProps) {
  const [status, setStatus] = useState<AuthStatus>("checking");
  const [user, setUser] = useState<AuthUser | null>(null);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  const clearSession = useCallback(() => {
    session.clear();
    setUser(null);
    setStatus("anonymous");
  }, []);

  // ตรวจสอบ Session เมื่อเปิดหน้าเว็บหรือ Refresh
  useEffect(() => {
    let active = true;

    const checkSession = async () => {
      if (!session.getToken()) {
        if (active) setStatus("anonymous");
        return;
      }

      try {
        const currentUser = await authApi.me();

        if (active) {
          setUser(currentUser);
          setStatus("authenticated");
        }
      } catch {
        session.clear();

        if (active) {
          setUser(null);
          setStatus("anonymous");
        }
      }
    };

    const onUnauthorized = () => {
      if (active) clearSession();
    };

    window.addEventListener("smartfarm:unauthorized", onUnauthorized);
    void checkSession();

    return () => {
      active = false;
      window.removeEventListener("smartfarm:unauthorized", onUnauthorized);
    };
  }, [clearSession]);

  // แสดง Splash ช่วงสั้น ๆ หลัง Login สำเร็จ
  useEffect(() => {
    if (status !== "transitioning") return;

    const timer = window.setTimeout(() => {
      setStatus("authenticated");
    }, 650);

    return () => window.clearTimeout(timer);
  }, [status]);

  async function handleLogin(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submitting) return;

    setSubmitting(true);
    setError("");

    try {
      const result = await authApi.login(email.trim(), password);

      if (!result.access_token || !result.user) {
        throw new Error("รูปแบบข้อมูลตอบกลับจากระบบไม่ถูกต้อง");
      }

      session.setToken(result.access_token);

      try {
        const currentUser = await authApi.me();
        setUser(currentUser);
      } catch {
        session.clear();
        throw new Error("เข้าสู่ระบบแล้ว แต่ไม่สามารถตรวจสอบ Session ได้");
      }

      setPassword("");
      setStatus("transitioning");
    } catch (cause) {
      setError(
        cause instanceof ApiError
          ? cause.status === 401
            ? "อีเมลหรือรหัสผ่านไม่ถูกต้อง"
            : cause.message
          : cause instanceof Error
            ? cause.message
            : "เข้าสู่ระบบไม่สำเร็จ กรุณาลองอีกครั้ง",
      );
    } finally {
      setSubmitting(false);
    }
  }

  async function handleLogout() {
    try {
      await authApi.logout();
    } catch {
      // ล้าง Session ในเครื่องแม้เซิร์ฟเวอร์ไม่ตอบกลับ
    } finally {
      clearSession();
      setPassword("");
      setError("");
    }
  }

  if (status === "checking") {
    return <SplashScreen message="กำลังตรวจสอบ Session..." />;
  }

  if (status === "transitioning") {
    return <SplashScreen message="เข้าสู่ระบบสำเร็จ กำลังเตรียมระบบ..." />;
  }

  if (status === "anonymous") {
    return (
      <main className="auth-screen">
        <section className="auth-card">
          <div className="auth-brand">
            <span className="auth-logo">SF</span>
            <p className="auth-eyebrow">SMART FARM MANAGEMENT</p>
            <h1>ยินดีต้อนรับ</h1>
            <p>เข้าสู่ระบบ Smart Farm System V.1</p>
          </div>

          <form className="auth-form" onSubmit={handleLogin}>
            <label htmlFor="login-email">อีเมล</label>
            <input
              id="login-email"
              name="email"
              type="email"
              autoComplete="username"
              placeholder="name@example.com"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              required
            />

            <label htmlFor="login-password">รหัสผ่าน</label>
            <input
              id="login-password"
              name="password"
              type="password"
              autoComplete="current-password"
              placeholder="กรอกรหัสผ่าน"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              required
            />

            {error && (
              <p className="auth-error" role="alert">
                {error}
              </p>
            )}

            <button
              className="auth-submit"
              type="submit"
              disabled={submitting}
            >
              {submitting ? "กำลังเข้าสู่ระบบ..." : "เข้าสู่ระบบ"}
            </button>
          </form>

          <p className="auth-security-note">
            ระบบจะตรวจสอบสิทธิ์กับเซิร์ฟเวอร์ก่อนเข้าใช้งาน
          </p>
        </section>
      </main>
    );
  }

  return (
    <>
      <div className="auth-session-bar">
        <span>
          เข้าสู่ระบบแล้ว{user?.display_name ? `: ${user.display_name}` : ""}
        </span>
        <button type="button" onClick={handleLogout}>
          ออกจากระบบ
        </button>
      </div>
      {children}
    </>
  );
}
