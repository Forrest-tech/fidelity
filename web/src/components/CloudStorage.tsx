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
