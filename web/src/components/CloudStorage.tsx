import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { api, json } from "../net/client";
import { Button, Card, cx } from "./ui";

type Role = "reader" | "writer";
interface Conn { connected: boolean; app_key: string; account: { name?: string; email?: string; error?: string } | null }
type Status = Record<Role, Conn>;

function Connection({ role, c, loading }: { role: Role; c: Conn | undefined; loading: boolean }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [key, setKey] = useState(c?.app_key ?? "");
  const [url, setUrl] = useState("");
  const [code, setCode] = useState("");
  const done = () => void qc.invalidateQueries({ queryKey: ["storage"] });
  const start = useMutation({
    mutationFn: () => api<{ url: string }>("/storage/dropbox/start", json({ role, app_key: key || c?.app_key || "" })),
    onSuccess: (r) => {
      setUrl(r.url);
      setCode("");
    },
  });
  const finish = useMutation({
    mutationFn: () => api<{ connected: boolean }>("/storage/dropbox/finish", json({ role, code })),
    onSuccess: () => {
      setUrl("");
      done();
    },
  });
  const drop = useMutation({
    mutationFn: () => api(`/storage/dropbox/${role}`, { method: "DELETE" }),
    onSuccess: done,
  });
  const err = (start.error || finish.error || drop.error) as Error | null;
  return (
    <section className="flex flex-col gap-2 rounded-md border border-border p-3" aria-labelledby={`conn-${role}`}>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 id={`conn-${role}`} className="font-medium">{t(`pages.settings.storage.${role}`)}</h3>
        <span className={cx("text-sm", c?.connected ? (c.account ? "text-ok" : "text-warn") : "text-fg-muted")}>
          {loading
            ? t("pages.settings.storage.checking")
            : !c?.connected
            ? t("pages.settings.storage.notConnected")
            : c.account?.error === "missing_scope"
              ? t("pages.settings.storage.connectedNoName")
              : c.account
                ? t("pages.settings.storage.connectedAs", { name: c.account.name, email: c.account.email })
                : t("pages.settings.storage.connectedUnchecked")}
        </span>
      </div>
      <p className="text-xs text-fg-muted">{t(`pages.settings.storage.${role}Hint`)}</p>
      {!url && (
        <div className="flex flex-wrap items-end gap-2">
          <label className="grid flex-1 gap-1 text-sm">
            {t("pages.settings.storage.appKey")}
            <input className="min-w-0 rounded-md border border-border bg-surface px-2 py-2" value={key}
              onChange={(e) => setKey(e.target.value)} placeholder={c?.app_key || "abc123…"} autoComplete="off" spellCheck={false} />
          </label>
          <Button onClick={() => start.mutate()} disabled={start.isPending || !(key || c?.app_key)}>
            {c?.connected ? t("pages.settings.storage.reconnect") : t("pages.settings.storage.connect")}
          </Button>
          {c?.connected && (
            <Button variant="ghost" disabled={drop.isPending}
              onClick={() => window.confirm(t("pages.settings.storage.disconnectConfirm")) && drop.mutate()}>
              {t("pages.settings.storage.disconnect")}
            </Button>
          )}
        </div>
      )}
      {url && (
        <form className="flex flex-col gap-2" onSubmit={(e) => { e.preventDefault(); finish.mutate(); }}>
          <ol className="list-decimal pl-5 text-sm">
            <li>
              <a href={url} target="_blank" rel="noopener noreferrer" className="text-primary underline">
                {t("pages.settings.storage.step1")}
              </a>
            </li>
            <li>{t("pages.settings.storage.step2")}</li>
          </ol>
          <div className="flex flex-wrap items-end gap-2">
            <label className="grid flex-1 gap-1 text-sm">
              {t("pages.settings.storage.code")}
              <input className="min-w-0 rounded-md border border-border bg-surface px-2 py-2" value={code}
                onChange={(e) => setCode(e.target.value)} required autoComplete="off" spellCheck={false} />
            </label>
            <Button type="submit" disabled={finish.isPending || !code.trim()}>{t("pages.settings.storage.finish")}</Button>
            <Button variant="ghost" type="button" onClick={() => setUrl("")}>{t("pages.settings.storage.cancel")}</Button>
          </div>
        </form>
      )}
      {err && <p role="alert" className="text-sm text-danger">{err.message}</p>}
      {finish.isSuccess && !url && <p role="status" className="text-sm text-ok">{t("pages.settings.storage.saved")}</p>}
    </section>
  );
}

export function CloudStorage() {
  const { t } = useTranslation();
  const q = useQuery({ queryKey: ["storage"], queryFn: () => api<Status>("/storage/dropbox") });
  return (
    <Card className="flex max-w-2xl flex-col gap-3">
      <div>
        <h2 className="font-medium">{t("pages.settings.storage.title")}</h2>
        <p className="text-sm text-fg-muted">{t("pages.settings.storage.intro")}</p>
      </div>
      {q.isError && <p role="alert" className="text-sm text-danger">{(q.error as Error).message}</p>}
      {(["reader", "writer"] as Role[]).map((r) => (
        <Connection key={`${r}-${q.data?.[r]?.app_key ?? ""}`} role={r} c={q.data?.[r]} loading={q.isLoading} />
      ))}
      <details className="text-sm">
        <summary className="cursor-pointer text-fg-muted">{t("pages.settings.storage.helpTitle")}</summary>
        <ol className="mt-2 list-decimal pl-5 text-fg-muted">
          <li>{t("pages.settings.storage.help1")}</li>
          <li>{t("pages.settings.storage.help2")}</li>
          <li>{t("pages.settings.storage.help3")}</li>
        </ol>
      </details>
    </Card>
  );
}

interface GoogleStatus {
  client_configured: boolean;
  client_id: string;
  redirect_uri: string;
  reader: { connected: boolean; account: { name: string; email: string } | null };
  writer: { connected: boolean; account: { name: string; email: string } | null };
}

export function GoogleDrive() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["google"], queryFn: () => api<GoogleStatus>("/storage/google") });
  const [cid, setCid] = useState("");
  const [secret, setSecret] = useState("");
  const [editClient, setEditClient] = useState(false);
  const done = () => void qc.invalidateQueries({ queryKey: ["google"] });
  const save = useMutation({
    mutationFn: () => api("/storage/google/client", { ...json({ client_id: cid, client_secret: secret }), method: "PUT" }),
    onSuccess: () => {
      setSecret("");
      setEditClient(false);
      done();
    },
  });
  const start = useMutation({
    mutationFn: (role: Role) => api<{ url: string }>("/storage/google/start", json({ role })),
    onSuccess: (r) => {
      window.location.assign(r.url); // Google's consent page; it returns to this app
    },
  });
  const drop = useMutation({ mutationFn: (role: Role) => api(`/storage/google/${role}`, { method: "DELETE" }), onSuccess: done });
  const params = new URLSearchParams(window.location.search);
  const result = params.get("google");
  const err = (save.error || start.error || drop.error) as Error | null;
  const s = q.data;
  const showClientForm = s && (!s.client_configured || editClient);
  return (
    <Card className="flex max-w-2xl flex-col gap-3">
      <div>
        <h2 className="font-medium">{t("pages.settings.google.title")}</h2>
        <p className="text-sm text-fg-muted">{t("pages.settings.google.intro")}</p>
      </div>
      {result === "connected" && <p role="status" className="text-sm text-ok">{t("pages.settings.google.connectedNow")}</p>}
      {result === "error" && (
        <p role="alert" className="text-sm text-danger">{t("pages.settings.google.failed", { reason: params.get("reason") || "" })}</p>
      )}
      {q.isLoading && <p className="text-sm text-fg-muted">{t("pages.settings.storage.checking")}</p>}
      {s && (
        <div className="rounded-md bg-muted p-2 text-sm">
          <p>{t("pages.settings.google.redirect")}</p>
          <code className="block break-all">{s.redirect_uri}</code>
        </div>
      )}
      {s && !showClientForm && (
        <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
          <span className="break-all">{t("pages.settings.google.clientSet", { id: s.client_id })}</span>
          <Button variant="ghost" onClick={() => setEditClient(true)}>{t("pages.settings.google.changeClient")}</Button>
        </div>
      )}
      {showClientForm && (
        <form className="grid gap-2" onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
          <label className="grid gap-1 text-sm">
            {t("pages.settings.google.clientId")}
            <input className="rounded-md border border-border bg-surface px-2 py-2" value={cid} onChange={(e) => setCid(e.target.value)}
              placeholder="123…-abc.apps.googleusercontent.com" required autoComplete="off" spellCheck={false} />
          </label>
          <label className="grid gap-1 text-sm">
            {t("pages.settings.google.clientSecret")}
            <input type="password" className="rounded-md border border-border bg-surface px-2 py-2" value={secret}
              onChange={(e) => setSecret(e.target.value)} required autoComplete="off" />
          </label>
          <div><Button type="submit" disabled={save.isPending}>{t("pages.settings.google.saveClient")}</Button></div>
        </form>
      )}
      {s?.client_configured &&
        (["reader", "writer"] as Role[]).map((role) => (
          <section key={role} className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-border p-3" aria-labelledby={`g-${role}`}>
            <div>
              <h3 id={`g-${role}`} className="font-medium">{t(`pages.settings.storage.${role}`)}</h3>
              <p className={cx("text-sm", s[role].connected ? "text-ok" : "text-fg-muted")}>
                {!s[role].connected
                  ? t("pages.settings.storage.notConnected")
                  : s[role].account
                    ? t("pages.settings.storage.connectedAs", { name: s[role].account!.name, email: s[role].account!.email })
                    : t("pages.settings.storage.connectedUnchecked")}
              </p>
            </div>
            <div className="flex gap-2">
              <Button onClick={() => start.mutate(role)} disabled={start.isPending}>
                {s[role].connected ? t("pages.settings.storage.reconnect") : t("pages.settings.storage.connect")}
              </Button>
              {s[role].connected && (
                <Button variant="ghost" disabled={drop.isPending}
                  onClick={() => window.confirm(t("pages.settings.storage.disconnectConfirm")) && drop.mutate(role)}>
                  {t("pages.settings.storage.disconnect")}
                </Button>
              )}
            </div>
          </section>
        ))}
      {err && <p role="alert" className="text-sm text-danger">{err.message}</p>}
      <details className="text-sm">
        <summary className="cursor-pointer text-fg-muted">{t("pages.settings.google.helpTitle")}</summary>
        <ol className="mt-2 list-decimal pl-5 text-fg-muted">
          <li>{t("pages.settings.google.help1")}</li>
          <li>{t("pages.settings.google.help2")}</li>
          <li>{t("pages.settings.google.help3")}</li>
          <li>{t("pages.settings.google.help4")}</li>
        </ol>
      </details>
    </Card>
  );
}
