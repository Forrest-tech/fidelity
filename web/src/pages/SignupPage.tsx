import { useCallback, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, Navigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Alert, Button, Divider, Form, Input, Result, Typography } from "antd";
import { LockOutlined, MailOutlined, SafetyCertificateOutlined } from "@ant-design/icons";
import { ApiError, api, json } from "../net/client";
import { useAuth } from "../auth/AuthProvider";
import { Captcha } from "../components/Captcha";
import type { CaptchaHandle } from "../components/Captcha";
import { Loading } from "../components/ui";
import { AuthFrame, ProviderButtons } from "./LoginPage";

interface AuthOptions {
  providers: Array<{ id: string; label: string }>;
  captcha: boolean;
  signup: boolean;
}

/** Ask for an account (requirements v2, U-1): email, password, "I'm not a robot". An administrator approves it;
 * a Google / Microsoft / GitHub sign-up from the company's own domain is approved at once. */
export function SignupPage() {
  const { t } = useTranslation();
  const { me, loading } = useAuth();
  const [form] = Form.useForm<{ email: string; password: string; confirm: string }>();
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [sent, setSent] = useState("");
  const [byEmail, setByEmail] = useState(false);
  const [needTick, setNeedTick] = useState(false);
  const captchaRef = useRef<CaptchaHandle>(null);
  const proof = useRef<string | null>(null);
  const onCaptcha = useCallback((p: string | null) => {
    proof.current = p;
    if (p) setNeedTick(false);
  }, []);
  const opts = useQuery({ queryKey: ["auth-options"], queryFn: () => api<AuthOptions>("/auth/options"), retry: 1, staleTime: 300_000 });
  if (loading || opts.isLoading) return <Loading />;
  if (me) return <Navigate to="/" replace />;
  const needCaptcha = opts.data?.captcha !== false;

  const submit = async (v: { email: string; password: string }) => {
    setErr("");
    if (needCaptcha && !proof.current) {
      setNeedTick(true);
      captchaRef.current?.focus();
      return;
    }
    setBusy(true);
    try {
      const r = await api<{ status: string }>("/auth/signup", json({ email: v.email.trim(), password: v.password, altcha: proof.current }));
      setByEmail(r?.status === "verify_email");
      setSent(v.email.trim());
    } catch (x) {
      captchaRef.current?.reset();
      const d = x instanceof ApiError ? x.message : "";
      if (x instanceof ApiError && x.status === 429) setErr(t("signup.tooMany"));
      else if (d.startsWith("CAPTCHA_")) setErr(t("login.captchaExpiredTick"));
      else if (d.startsWith("INVALID_PASSWORD")) setErr(t("login.setupPasswordShort"));
      else if (x instanceof ApiError && x.status === 404) setErr(t("signup.closed"));
      else setErr(t("login.error"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <AuthFrame>
      {opts.data?.signup === false ? (
        <Result status="info" title={t("signup.closedTitle")} subTitle={t("login.noAccount")}
          extra={<Link to="/login"><Button type="primary">{t("signup.backToSignIn")}</Button></Link>} />
      ) : sent ? (
        <Result status="success" title={byEmail ? t("email.checkInbox") : t("signup.sentTitle")}
          subTitle={byEmail ? t("email.confirmSent", { email: sent }) : t("signup.sentBody", { email: sent })}
          extra={<Link to="/login"><Button type="primary">{t("signup.backToSignIn")}</Button></Link>} />
      ) : (
        <>
          <Typography.Title level={1} className="fx-auth-h1">{t("signup.title")}</Typography.Title>
          <Typography.Paragraph type="secondary" style={{ marginBottom: 20 }}>{t("signup.intro")}</Typography.Paragraph>
          {!!opts.data?.providers.length && (
            <>
              <ProviderButtons providers={opts.data.providers} verb="signup" next="/" />
              <Divider plain className="fx-auth-or">{t("login.or")}</Divider>
            </>
          )}
          <Form form={form} layout="vertical" requiredMark={false} aria-label={t("signup.title")} onFinish={(v) => void submit(v)} validateTrigger="onBlur">
            <Form.Item name="email" label={t("login.email")} htmlFor="signup-email" extra={t("signup.emailHint")}
              rules={[{ required: true, whitespace: true, message: t("login.emailRequired") },
                { type: "email", message: t("login.emailInvalid"), transform: (s: string) => s?.trim() }, { max: 320, message: t("login.emailInvalid") }]}>
              <Input id="signup-email" size="large" type="email" inputMode="email" autoComplete="email" autoFocus maxLength={320}
                placeholder={t("login.emailPlaceholder")} prefix={<MailOutlined aria-hidden="true" className="fx-auth-icon" />} />
            </Form.Item>
            <Form.Item name="password" label={t("login.password")} htmlFor="signup-password" extra={t("login.setupPasswordHint")}
              rules={[{ required: true, message: t("login.passwordRequired") }, { min: 10, message: t("login.setupPasswordShort") }, { max: 1000, message: t("login.passwordRequired") }]}>
              <Input.Password id="signup-password" size="large" autoComplete="new-password" prefix={<LockOutlined aria-hidden="true" className="fx-auth-icon" />} />
            </Form.Item>
            <Form.Item name="confirm" label={t("login.setupConfirm")} htmlFor="signup-confirm" dependencies={["password"]}
              rules={[{ required: true, message: t("login.confirmRequired") },
                ({ getFieldValue }) => ({ validator: (_r, v) => (!v || v === getFieldValue("password") ? Promise.resolve() : Promise.reject(new Error(t("login.setupMismatch")))) })]}>
              <Input.Password id="signup-confirm" size="large" autoComplete="new-password" prefix={<LockOutlined aria-hidden="true" className="fx-auth-icon" />} />
            </Form.Item>
            {needCaptcha && (
              <div style={{ marginBottom: 16 }}>
                <Captcha ref={captchaRef} onChange={onCaptcha} invalid={needTick} />
                {needTick && <div className="fx-human-note" role="alert">{t("login.tickFirst")}</div>}
              </div>
            )}
            <div aria-live="polite">{err && <Alert type="error" showIcon title={err} style={{ marginBottom: 16 }} />}</div>
            <Button type="primary" htmlType="submit" size="large" block loading={busy}>{busy ? t("login.submitting") : t("signup.submit")}</Button>
          </Form>
          <p className="fx-auth-foot">{t("signup.haveAccount")} <Link to="/login">{t("signup.signIn")}</Link></p>
        </>
      )}
      <p className="fx-auth-secure" style={{ marginTop: 18 }}><SafetyCertificateOutlined aria-hidden="true" /> {t("login.secure")}</p>
    </AuthFrame>
  );
}
