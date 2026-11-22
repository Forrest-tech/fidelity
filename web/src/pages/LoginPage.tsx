import { useCallback, useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Navigate, useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Alert, Button, Divider, Form, Input, Popover, Segmented, Typography } from "antd";
import { GithubFilled, LockOutlined, MailOutlined, MoonOutlined, SafetyCertificateOutlined, SunOutlined } from "@ant-design/icons";
import { ApiError, api, json } from "../net/client";
import { useAuth } from "../auth/AuthProvider";
import { Captcha } from "../components/Captcha";
import type { CaptchaHandle } from "../components/Captcha";
import { Loading } from "../components/ui";
import { LANGS } from "../locales";
import { useTheme } from "../layout/ThemeProvider";

interface AuthOptions {
  providers: Array<{ id: string; label: string }>;
  captcha: boolean;
}

// Brand marks as the providers publish them (Google "G", Microsoft four squares); GitHub from Ant Design's icon set.
const GoogleMark = () => (
  <svg width="18" height="18" viewBox="0 0 48 48" aria-hidden="true">
    <path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z" />
    <path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z" />
    <path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z" />
    <path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z" />
  </svg>
);
const MicrosoftMark = () => (
  <svg width="16" height="16" viewBox="0 0 21 21" aria-hidden="true">
    <rect x="1" y="1" width="9" height="9" fill="#F25022" />
    <rect x="11" y="1" width="9" height="9" fill="#7FBA00" />
    <rect x="1" y="11" width="9" height="9" fill="#00A4EF" />
    <rect x="11" y="11" width="9" height="9" fill="#FFB900" />
  </svg>
);
const MARK: Record<string, JSX.Element> = {
  google: <GoogleMark />,
  microsoft: <MicrosoftMark />,
  github: <GithubFilled style={{ fontSize: 18 }} aria-hidden="true" />,
};

const OAUTH_ERRORS = ["oauth_no_account", "oauth_cancelled", "oauth_expired", "oauth_failed", "oauth_no_email", "oauth_inactive", "oauth_unavailable"];

export function LoginPage() {
  const { t, i18n } = useTranslation();
  const { me, loading, login, refresh } = useAuth();
  const { dark, setTheme } = useTheme();
  const loc = useLocation() as { state?: { from?: string } };
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const [form] = Form.useForm<{ email: string; password: string; confirm?: string }>();
  const [busy, setBusy] = useState(false);
  const [leaving, setLeaving] = useState("");
  const [err, setErr] = useState("");
  const [captcha, setCaptcha] = useState<string | null>(null);
  const captchaRef = useRef<CaptchaHandle>(null);
  const setup = useQuery({ queryKey: ["setup"], queryFn: () => api<{ needs_setup: boolean }>("/setup"), retry: false });
  const opts = useQuery({ queryKey: ["auth-options"], queryFn: () => api<AuthOptions>("/auth/options"), retry: 1, staleTime: 300_000 });
  const firstRun = setup.data?.needs_setup === true;
  // when the options cannot be read, show the check anyway (the server decides; it refuses a sign-in without it)
  const needCaptcha = opts.data?.captcha === true || opts.isError;
  const providers = firstRun ? [] : opts.data?.providers ?? [];
  const lang = i18n.language.startsWith("zh") ? "zh" : "en";
  const from = loc.state?.from && loc.state.from !== "/login" ? loc.state.from : "/";

  // a refused Google/Microsoft/GitHub sign-in comes back as /login?error=<code>: show it once, keep the URL clean
  useEffect(() => {
    const code = params.get("error");
    if (code) {
      setErr(OAUTH_ERRORS.includes(code) ? t(`login.oauth.${code}`) : t("login.oauth.oauth_failed"));
      navigate("/login", { replace: true, state: loc.state });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params]);

  const onCaptcha = useCallback((p: string | null) => setCaptcha(p), []);
  // pressing Sign in before the bot check has finished: wait for it, then go on by itself
  const pending = useRef<{ email: string; password: string } | null>(null);
  useEffect(() => {
    if (captcha && pending.current) {
      const v = pending.current;
      pending.current = null;
      void submit(v);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [captcha]);

  if (loading) return <Loading />;
  if (me) return <Navigate to={from} replace />;

  const submit = async (v: { email: string; password: string }) => {
    setErr("");
    if (needCaptcha && !captcha) {
      pending.current = v;
      setBusy(true);
      window.setTimeout(() => {
        if (pending.current === v) {
          // the check did not finish (offline, blocked worker): say so instead of spinning for ever
          pending.current = null;
          setBusy(false);
          setErr(t("login.captchaRequired"));
          captchaRef.current?.reset();
        }
      }, 30_000);
      return;
    }
    setBusy(true);
    try {
      if (firstRun) {
        await api("/setup", json({ email: v.email.trim(), password: v.password, altcha: captcha }));
        await refresh(); // the server signed the new administrator in
      } else {
        await login(v.email, v.password, captcha);
      }
    } catch (x) {
      captchaRef.current?.reset(); // each check works once: get a fresh one for the next attempt
      const detail = x instanceof ApiError ? x.message : "";
      if (x instanceof ApiError && x.status === 429) setErr(t("login.tooMany"));
      else if (detail === "CAPTCHA_EXPIRED" || detail === "CAPTCHA_REUSED") setErr(t("login.captchaExpired"));
      else if (detail.startsWith("CAPTCHA_")) setErr(t("login.captchaRequired"));
      else if (firstRun && x instanceof ApiError && x.status === 422) setErr(t("login.setupPassword"));
      else if (firstRun && x instanceof ApiError && x.status === 409) {
        void setup.refetch();
        setErr(t("login.failed"));
      } else if (x instanceof ApiError && x.status === 400) setErr(t("login.failed"));
      else setErr(t("login.error"));
    } finally {
      setBusy(false);
    }
  };

  const goProvider = (id: string, label: string) => {
    setLeaving(label);
    window.location.assign(`/api/v1/auth/oauth/${id}/authorize?next=${encodeURIComponent(from)}`);
  };

  const title = firstRun ? t("login.setupTitle") : t("login.heading");

  return (
    <div className="fx-auth">
      <aside className="fx-auth-brand" aria-hidden="true">
        <div className="fx-auth-brand-in">
          <div className="fx-auth-logo">
            <span className="fx-auth-mark">F</span>
            <span>{t("app.name")}</span>
          </div>
          <p className="fx-auth-tag">{t("app.tagline")}</p>
          <ul className="fx-auth-points">
            <li>{t("login.brandPoint1")}</li>
            <li>{t("login.brandPoint2")}</li>
            <li>{t("login.brandPoint3")}</li>
          </ul>
        </div>
      </aside>
      <main className="fx-auth-main" id="main">
        <div className="fx-auth-tools">
          <Segmented
            size="small"
            aria-label={t("header.language")}
            value={lang}
            options={LANGS.map((l) => ({ value: l, label: l === "zh" ? "中文" : "English" }))}
            onChange={(v) => void i18n.changeLanguage(String(v))}
          />
          <Button
            size="small"
            type="text"
            aria-label={dark ? t("shell.lightTheme") : t("shell.darkTheme")}
            onClick={() => setTheme(dark ? "light" : "dark")}
          >
            {dark ? <SunOutlined aria-hidden="true" /> : <MoonOutlined aria-hidden="true" />}
          </Button>
        </div>
        <div className="fx-auth-card">
          <div className="fx-auth-logo fx-auth-logo-sm" aria-hidden="true">
            <span className="fx-auth-mark">F</span>
            <span>{t("app.name")}</span>
          </div>
          <Typography.Title level={1} className="fx-auth-h1">
            {title}
          </Typography.Title>
          <Typography.Paragraph type="secondary" style={{ marginBottom: 20 }}>
            {firstRun ? t("login.setupHint") : providers.length ? t("login.subheading") : t("app.tagline")}
          </Typography.Paragraph>

          {providers.length > 0 && (
            <>
              <div className="fx-auth-providers">
                {providers.map((p) => (
                  <Button
                    key={p.id}
                    size="large"
                    block
                    icon={MARK[p.id] ?? <SafetyCertificateOutlined aria-hidden="true" />}
                    loading={leaving === p.label}
                    disabled={!!leaving || busy}
                    onClick={() => goProvider(p.id, p.label)}
                  >
                    {leaving === p.label ? t("login.redirecting", { provider: p.label }) : t("login.continueWith", { provider: p.label })}
                  </Button>
                ))}
              </div>
              <Divider plain className="fx-auth-or">
                {t("login.or")}
              </Divider>
            </>
          )}

          <Form
            form={form}
            layout="vertical"
            requiredMark={false}
            aria-label={firstRun ? t("login.setupTitle") : t("login.title")}
            onFinish={(v) => void submit(v)}
            validateTrigger="onBlur"
          >
            <Form.Item
              name="email"
              label={t("login.email")}
              htmlFor="login-email"
              extra={firstRun ? t("login.setupEmailHint") : undefined}
              rules={[
                { required: true, whitespace: true, message: t("login.emailRequired") },
                { type: "email", message: t("login.emailInvalid"), transform: (s: string) => s?.trim() },
                { max: 320, message: t("login.emailInvalid") },
              ]}
            >
              <Input
                id="login-email"
                size="large"
                type="email"
                inputMode="email"
                autoComplete="username"
                autoFocus
                maxLength={320}
                placeholder={t("login.emailPlaceholder")}
                prefix={<MailOutlined aria-hidden="true" className="fx-auth-icon" />}
              />
            </Form.Item>
            <Form.Item
              name="password"
              label={t("login.password")}
              htmlFor="login-password"
              extra={firstRun ? t("login.setupPasswordHint") : undefined}
              rules={[
                { required: true, message: t("login.passwordRequired") },
                ...(firstRun ? [{ min: 10, message: t("login.setupPasswordShort") }] : []),
                { max: 1000, message: t("login.passwordRequired") },
              ]}
            >
              <Input.Password
                id="login-password"
                size="large"
                autoComplete={firstRun ? "new-password" : "current-password"}
                placeholder={t("login.passwordPlaceholder")}
                prefix={<LockOutlined aria-hidden="true" className="fx-auth-icon" />}
              />
            </Form.Item>
            {!firstRun && (
              <div className="fx-auth-forgot-row">
                <Popover content={<div style={{ maxWidth: 260 }}>{t("login.forgotHelp")}</div>} trigger="click" placement="bottomRight">
                  <Button type="link" size="small" className="fx-auth-forgot">
                    {t("login.forgot")}
                  </Button>
                </Popover>
              </div>
            )}
            {firstRun && (
              <Form.Item
                name="confirm"
                label={t("login.setupConfirm")}
                htmlFor="login-confirm"
                dependencies={["password"]}
                rules={[
                  { required: true, message: t("login.confirmRequired") },
                  ({ getFieldValue }) => ({
                    validator: (_r, v) => (!v || v === getFieldValue("password") ? Promise.resolve() : Promise.reject(new Error(t("login.setupMismatch")))),
                  }),
                ]}
              >
                <Input.Password id="login-confirm" size="large" autoComplete="new-password" prefix={<LockOutlined aria-hidden="true" className="fx-auth-icon" />} />
              </Form.Item>
            )}
            {needCaptcha && (
              <div style={{ marginBottom: 16 }}>
                <Captcha ref={captchaRef} onChange={onCaptcha} />
              </div>
            )}
            <div aria-live="polite">{err && <Alert type="error" showIcon title={err} style={{ marginBottom: 16 }} />}</div>
            <Button type="primary" htmlType="submit" size="large" block loading={busy} disabled={!!leaving}>
              {busy && pending.current ? t("login.captchaWait") : busy ? t("login.submitting") : firstRun ? t("login.setupSubmit") : t("login.submit")}
            </Button>
          </Form>
          {!firstRun && <p className="fx-auth-foot">{t("login.noAccount")}</p>}
        </div>
        <p className="fx-auth-secure">
          <SafetyCertificateOutlined aria-hidden="true" /> {t("login.secure")}
        </p>
      </main>
    </div>
  );
}
