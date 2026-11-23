import { useCallback, useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Alert, Button, Form, Input, Result, Spin, Typography } from "antd";
import { LockOutlined, MailOutlined } from "@ant-design/icons";
import { ApiError, api, json } from "../net/client";
import { Captcha } from "../components/Captcha";
import type { CaptchaHandle } from "../components/Captcha";
import { AuthFrame } from "./LoginPage";

const back = (t: (k: string) => string) => <Link to="/login"><Button type="primary">{t("signup.backToSignIn")}</Button></Link>;

/** The link in the confirmation e-mail lands here: the address is confirmed, then sign in (or wait for approval). */
export function VerifyEmailPage() {
  const { t } = useTranslation();
  const [params] = useSearchParams();
  const token = params.get("token") ?? "";
  const [state, setState] = useState<"working" | "active" | "pending" | "done" | "invalid">("working");
  const ran = useRef(false);
  useEffect(() => {
    if (ran.current) return;
    ran.current = true;
    if (!token) {
      setState("invalid");
      return;
    }
    api<{ status: string }>("/auth/verify-email", json({ token })).then(
      (r) => setState(r.status === "active" ? "active" : "pending"),
      (e) => setState(e instanceof ApiError && e.status === 409 ? "done" : "invalid"),
    );
  }, [token]);
  return (
    <AuthFrame>
      {state === "working" ? (
        <div style={{ textAlign: "center", padding: 32 }} role="status"><Spin /> <div className="fx-muted" style={{ marginTop: 10 }}>{t("email.confirming")}</div></div>
      ) : state === "active" ? (
        <Result status="success" title={t("email.confirmedTitle")} subTitle={t("email.confirmedActive")} extra={back(t)} />
      ) : state === "pending" ? (
        <Result status="success" title={t("email.confirmedTitle")} subTitle={t("email.confirmedPending")} extra={back(t)} />
      ) : state === "done" ? (
        <Result status="info" title={t("email.alreadyTitle")} subTitle={t("email.alreadyBody")} extra={back(t)} />
      ) : (
        <Result status="warning" title={t("email.invalidTitle")} subTitle={t("email.invalidConfirm")}
          extra={<Link to="/resend-confirmation"><Button type="primary">{t("email.resend")}</Button></Link>} />
      )}
    </AuthFrame>
  );
}

/** One e-mail address plus "I'm not a robot": used to ask for a reset link or a new confirmation link. */
function EmailRequest({ title, intro, endpoint, submit, sentTitle, sentBody }: { title: string; intro: string; endpoint: string; submit: string; sentTitle: string; sentBody: (e: string) => string }) {
  const { t } = useTranslation();
  const opts = useQuery({ queryKey: ["auth-options"], queryFn: () => api<{ captcha: boolean; email?: boolean }>("/auth/options"), staleTime: 300_000 });
  const captchaRef = useRef<CaptchaHandle>(null);
  const proof = useRef<string | null>(null);
  const [needTick, setNeedTick] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [sent, setSent] = useState("");
  const onCaptcha = useCallback((p: string | null) => {
    proof.current = p;
    if (p) setNeedTick(false);
  }, []);
  const needCaptcha = opts.data?.captcha !== false;
  if (opts.data && opts.data.email === false) {
    return <Result status="info" title={title} subTitle={t("login.forgotHelp")} extra={back(t)} />;
  }
  if (sent) return <Result status="success" title={sentTitle} subTitle={sentBody(sent)} extra={back(t)} />;
  const go = async (v: { email: string }) => {
    setErr("");
    if (needCaptcha && !proof.current) {
      setNeedTick(true);
      captchaRef.current?.focus();
      return;
    }
    setBusy(true);
    try {
      await api(endpoint, json({ email: v.email.trim(), altcha: proof.current }));
      setSent(v.email.trim());
    } catch (x) {
      captchaRef.current?.reset();
      if (x instanceof ApiError && x.status === 429) setErr(t("signup.tooMany"));
      else if (x instanceof ApiError && x.message.startsWith("CAPTCHA_")) setErr(t("login.captchaExpiredTick"));
      else setErr(t("login.error"));
    } finally {
      setBusy(false);
    }
  };
  return (
    <>
      <Typography.Title level={1} className="fx-auth-h1">{title}</Typography.Title>
      <Typography.Paragraph type="secondary" style={{ marginBottom: 20 }}>{intro}</Typography.Paragraph>
      <Form layout="vertical" requiredMark={false} aria-label={title} onFinish={(v) => void go(v)} validateTrigger="onBlur">
        <Form.Item name="email" label={t("login.email")} htmlFor="req-email"
          rules={[{ required: true, whitespace: true, message: t("login.emailRequired") }, { type: "email", message: t("login.emailInvalid"), transform: (s: string) => s?.trim() }]}>
          <Input id="req-email" size="large" type="email" autoComplete="email" autoFocus prefix={<MailOutlined aria-hidden="true" className="fx-auth-icon" />} />
        </Form.Item>
        {needCaptcha && (
          <div style={{ marginBottom: 16 }}>
            <Captcha ref={captchaRef} onChange={onCaptcha} invalid={needTick} />
            {needTick && <div className="fx-human-note" role="alert">{t("login.tickFirst")}</div>}
          </div>
        )}
        <div aria-live="polite">{err && <Alert type="error" showIcon title={err} style={{ marginBottom: 16 }} />}</div>
        <Button type="primary" htmlType="submit" size="large" block loading={busy}>{submit}</Button>
      </Form>
      <p className="fx-auth-foot"><Link to="/login">{t("signup.backToSignIn")}</Link></p>
    </>
  );
}

export function ForgotPasswordPage() {
  const { t } = useTranslation();
  return (
    <AuthFrame>
      <EmailRequest title={t("email.forgotTitle")} intro={t("email.forgotIntro")} endpoint="/auth/forgot-password" submit={t("email.sendLink")}
        sentTitle={t("email.checkInbox")} sentBody={(e) => t("email.resetSent", { email: e })} />
    </AuthFrame>
  );
}

export function ResendConfirmationPage() {
  const { t } = useTranslation();
  return (
    <AuthFrame>
      <EmailRequest title={t("email.resendTitle")} intro={t("email.resendIntro")} endpoint="/auth/verify-email/resend" submit={t("email.resend")}
        sentTitle={t("email.checkInbox")} sentBody={(e) => t("email.confirmSent", { email: e })} />
    </AuthFrame>
  );
}

/** The link in the reset e-mail lands here: choose a new password (twice). */
export function ResetPasswordPage() {
  const { t } = useTranslation();
  const [params] = useSearchParams();
  const token = params.get("token") ?? "";
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [done, setDone] = useState(false);
  const [invalid, setInvalid] = useState(!token);
  const go = async (v: { password: string }) => {
    setErr("");
    setBusy(true);
    try {
      await api("/auth/reset-password", json({ token, password: v.password }));
      setDone(true);
    } catch (x) {
      if (x instanceof ApiError && x.status === 422) setErr(t("login.setupPasswordShort"));
      else if (x instanceof ApiError && x.status === 400) setInvalid(true);
      else setErr(t("login.error"));
    } finally {
      setBusy(false);
    }
  };
  return (
    <AuthFrame>
      {done ? (
        <Result status="success" title={t("email.resetDoneTitle")} subTitle={t("email.resetDoneBody")} extra={back(t)} />
      ) : invalid ? (
        <Result status="warning" title={t("email.invalidTitle")} subTitle={t("email.invalidReset")}
          extra={<Link to="/forgot-password"><Button type="primary">{t("email.sendLink")}</Button></Link>} />
      ) : (
        <>
          <Typography.Title level={1} className="fx-auth-h1">{t("email.resetTitle")}</Typography.Title>
          <Form layout="vertical" requiredMark={false} aria-label={t("email.resetTitle")} onFinish={(v) => void go(v)} validateTrigger="onBlur">
            <Form.Item name="password" label={t("email.newPassword")} htmlFor="reset-password" extra={t("login.setupPasswordHint")}
              rules={[{ required: true, message: t("login.passwordRequired") }, { min: 10, message: t("login.setupPasswordShort") }]}>
              <Input.Password id="reset-password" size="large" autoComplete="new-password" autoFocus prefix={<LockOutlined aria-hidden="true" className="fx-auth-icon" />} />
            </Form.Item>
            <Form.Item name="confirm" label={t("login.setupConfirm")} htmlFor="reset-confirm" dependencies={["password"]}
              rules={[{ required: true, message: t("login.confirmRequired") },
                ({ getFieldValue }) => ({ validator: (_r, v) => (!v || v === getFieldValue("password") ? Promise.resolve() : Promise.reject(new Error(t("login.setupMismatch")))) })]}>
              <Input.Password id="reset-confirm" size="large" autoComplete="new-password" prefix={<LockOutlined aria-hidden="true" className="fx-auth-icon" />} />
            </Form.Item>
            <div aria-live="polite">{err && <Alert type="error" showIcon title={err} style={{ marginBottom: 16 }} />}</div>
            <Button type="primary" htmlType="submit" size="large" block loading={busy}>{t("email.setPassword")}</Button>
          </Form>
        </>
      )}
    </AuthFrame>
  );
}
