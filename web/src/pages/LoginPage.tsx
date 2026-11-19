import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import type { FormEvent } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { ApiError, api, json } from "../net/client";
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
  const [confirm, setConfirm] = useState("");
  const setup = useQuery({ queryKey: ["setup"], queryFn: () => api<{ needs_setup: boolean }>("/setup"), retry: false });
  const firstRun = setup.data?.needs_setup === true;

  if (loading) return <Loading />;
  if (me) return <Navigate to={loc.state?.from || "/"} replace />;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
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
    <div className="flex min-h-full items-center justify-center p-4">
      <Card className="w-full max-w-sm">
        <h1 className="mb-1 text-xl font-semibold">{t("app.name")}</h1>
        <p className="mb-4 text-sm text-fg-muted">{t("app.tagline")}</p>
        {firstRun && (
          <div className="mb-3 rounded-md bg-muted p-3 text-sm">
            <h2 className="font-medium">{t("login.setupTitle")}</h2>
            <p className="text-fg-muted">{t("login.setupHint")}</p>
          </div>
        )}
        <form onSubmit={submit} className="flex flex-col gap-3" aria-label={firstRun ? t("login.setupTitle") : t("login.title")}>
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
              autoComplete={firstRun ? "new-password" : "current-password"}
              minLength={firstRun ? 10 : undefined}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="rounded-md border border-border bg-surface px-3 py-2"
            />
          </label>
          {firstRun && (
            <label className="flex flex-col gap-1 text-sm">
              {t("login.setupConfirm")}
              <input
                type="password"
                required
                autoComplete="new-password"
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
                className="rounded-md border border-border bg-surface px-3 py-2"
              />
            </label>
          )}
          {err && (
            <p role="alert" className="text-sm text-danger">
              {err}
            </p>
          )}
          <Button type="submit" disabled={busy}>
            {busy ? t("login.submitting") : firstRun ? t("login.setupSubmit") : t("login.submit")}
          </Button>
        </form>
      </Card>
    </div>
  );
}
