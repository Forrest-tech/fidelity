import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Navigate, useLocation } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Alert, Button, Card, Form, Input, Segmented, Typography } from "antd";
import { ApiError, api, json } from "../net/client";
import { useAuth } from "../auth/AuthProvider";
import { Loading } from "../components/ui";
import { LANGS } from "../locales";

export function LoginPage() {
  const { t, i18n } = useTranslation();
  const { me, loading, login } = useAuth();
  const loc = useLocation() as { state?: { from?: string } };
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [confirm, setConfirm] = useState("");
  const setup = useQuery({ queryKey: ["setup"], queryFn: () => api<{ needs_setup: boolean }>("/setup"), retry: false });
  const firstRun = setup.data?.needs_setup === true;
  const lang = i18n.language.startsWith("zh") ? "zh" : "en";

  if (loading) return <Loading />;
  if (me) return <Navigate to={loc.state?.from || "/"} replace />;

  const submit = async () => {
    setBusy(true);
    setErr("");
    try {
      if (firstRun) {
        if (password !== confirm) {
          setErr(t("login.setupMismatch"));
          return;
        }
        await api("/setup", json({ email, password }));
      }
      await login(email, password);
    } catch (x) {
      if (firstRun && x instanceof ApiError && x.status === 422) {
        setErr(x.message || t("login.setupPassword"));
        return;
      }
      if (x instanceof ApiError && x.status === 429) setErr(t("login.tooMany"));
      else if (x instanceof ApiError && x.status === 400) setErr(t("login.failed"));
      else setErr(t("login.error"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex min-h-full flex-col items-center justify-center gap-4 p-4" style={{ minHeight: "100vh" }}>
      <div style={{ position: "absolute", top: 12, right: 16 }}>
        <Segmented
          size="small"
          aria-label={t("header.language")}
          value={lang}
          options={LANGS.map((l) => ({ value: l, label: l === "zh" ? "中文" : "English" }))}
          onChange={(v) => void i18n.changeLanguage(String(v))}
        />
      </div>
      <Card style={{ width: "100%", maxWidth: 400 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 4 }}>
          <span
            aria-hidden="true"
            style={{ width: 36, height: 36, borderRadius: 8, background: "var(--ant-color-primary)", color: "#fff", display: "grid", placeItems: "center", fontWeight: 700, fontSize: 18, lineHeight: 1 }}
          >
            F
          </span>
          <Typography.Title level={1} style={{ margin: 0, fontSize: 22 }}>
            {t("app.name")}
          </Typography.Title>
        </div>
        <Typography.Paragraph type="secondary">{t("app.tagline")}</Typography.Paragraph>
        {firstRun && (
          <div style={{ marginBottom: 16, padding: "12px 16px", borderRadius: 8, background: "var(--ant-color-info-bg)", border: "1px solid var(--ant-color-info-border)" }}>
            <h2 style={{ margin: 0, fontSize: 14, fontWeight: 600 }}>{t("login.setupTitle")}</h2>
            <Typography.Text type="secondary">{t("login.setupHint")}</Typography.Text>
          </div>
        )}
        <Form layout="vertical" aria-label={firstRun ? t("login.setupTitle") : t("login.title")} onFinish={() => void submit()}>
          <Form.Item label={t("login.email")} htmlFor="login-email">
            <Input id="login-email" size="large" type="email" required autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} />
          </Form.Item>
          <Form.Item label={t("login.password")} htmlFor="login-password">
            <Input
              id="login-password"
              size="large"
              type="password"
              required
              autoComplete={firstRun ? "new-password" : "current-password"}
              minLength={firstRun ? 10 : undefined}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </Form.Item>
          {firstRun && (
            <Form.Item label={t("login.setupConfirm")} htmlFor="login-confirm">
              <Input id="login-confirm" size="large" type="password" required autoComplete="new-password" value={confirm} onChange={(e) => setConfirm(e.target.value)} />
            </Form.Item>
          )}
          {err && <Alert type="error" showIcon title={err} style={{ marginBottom: 16 }} />}
          <Button type="primary" htmlType="submit" size="large" block loading={busy}>
            {busy ? t("login.submitting") : firstRun ? t("login.setupSubmit") : t("login.submit")}
          </Button>
        </Form>
      </Card>
    </div>
  );
}
