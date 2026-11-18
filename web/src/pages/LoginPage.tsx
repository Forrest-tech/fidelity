import { useState } from "react";
import type { FormEvent } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { ApiError } from "../net/client";
import { useAuth } from "../auth/AuthProvider";
import { Button, Card, Loading } from "../components/ui";

export function LoginPage() {
  const { t } = useTranslation();
  const { me, loading, login } = useAuth();
  const loc = useLocation() as { state?: { from?: string } };
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  if (loading) return <Loading />;
  if (me) return <Navigate to={loc.state?.from || "/"} replace />;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setErr("");
    try {
      await login(email, password);
    } catch (x) {
      if (x instanceof ApiError && x.status === 429) setErr(t("login.tooMany"));
      else if (x instanceof ApiError && x.status === 400) setErr(t("login.failed"));
      else setErr(t("login.error"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex min-h-full items-center justify-center p-4">
      <Card className="w-full max-w-sm">
        <h1 className="mb-1 text-xl font-semibold">{t("app.name")}</h1>
        <p className="mb-4 text-sm text-fg-muted">{t("app.tagline")}</p>
        <form onSubmit={submit} className="flex flex-col gap-3" aria-label={t("login.title")}>
          <label className="flex flex-col gap-1 text-sm">
            {t("login.email")}
            <input
              type="email"
              required
              autoComplete="username"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="rounded-md border border-border bg-surface px-3 py-2"
            />
          </label>
          <label className="flex flex-col gap-1 text-sm">
            {t("login.password")}
            <input
              type="password"
              required
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="rounded-md border border-border bg-surface px-3 py-2"
            />
          </label>
          {err && (
            <p role="alert" className="text-sm text-danger">
              {err}
            </p>
          )}
          <Button type="submit" disabled={busy}>
            {busy ? t("login.submitting") : t("login.submit")}
          </Button>
        </form>
      </Card>
    </div>
  );
}
