import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Alert, Button, Card, Collapse, Form, Input, Popconfirm, Space, Tag, Typography } from "antd";
import { api, json } from "../net/client";

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
  const text = loading
    ? t("pages.settings.storage.checking")
    : !c?.connected
      ? t("pages.settings.storage.notConnected")
      : c.account?.error === "missing_scope"
        ? t("pages.settings.storage.connectedNoName")
        : c.account
          ? t("pages.settings.storage.connectedAs", { name: c.account.name, email: c.account.email })
          : t("pages.settings.storage.connectedUnchecked");
  const tone = c?.connected ? (c.account && !c.account.error ? "success" : "warning") : "default";
  return (
    <section aria-labelledby={`conn-${role}`}>
      <Card
        size="small"
        title={
          <h3 id={`conn-${role}`} style={{ margin: 0, fontSize: 16 }}>
            {t(`pages.settings.storage.${role}`)}
          </h3>
        }
        extra={<Tag color={tone} style={{ marginInlineEnd: 0, whiteSpace: "normal" }}>{text}</Tag>}
      >
        <Space orientation="vertical" size={12} style={{ width: "100%" }}>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            {t(`pages.settings.storage.${role}Hint`)}
          </Typography.Text>
          {!url && (
            <Form layout="vertical">
              <Form.Item label={t("pages.settings.storage.appKey")} htmlFor={`appkey-${role}`} style={{ marginBottom: 0 }}>
                <Space.Compact style={{ width: "100%" }}>
                  <Input
                    id={`appkey-${role}`}
                    value={key}
                    onChange={(e) => setKey(e.target.value)}
                    placeholder={c?.app_key || "abc123…"}
                    autoComplete="off"
                    spellCheck={false}
                  />
                  <Button type="primary" onClick={() => start.mutate()} disabled={start.isPending || !(key || c?.app_key)}>
                    {c?.connected ? t("pages.settings.storage.reconnect") : t("pages.settings.storage.connect")}
                  </Button>
                  {c?.connected && (
                    <Popconfirm title={t("pages.settings.storage.disconnectConfirm")} onConfirm={() => drop.mutate()}>
                      <Button danger disabled={drop.isPending}>
                        {t("pages.settings.storage.disconnect")}
                      </Button>
                    </Popconfirm>
                  )}
                </Space.Compact>
              </Form.Item>
            </Form>
          )}
          {url && (
            <Form layout="vertical" onFinish={() => finish.mutate()}>
              <ol style={{ paddingLeft: 20, marginTop: 0 }}>
                <li>
                  <a href={url} target="_blank" rel="noopener noreferrer">
                    {t("pages.settings.storage.step1")}
                  </a>
                </li>
                <li>{t("pages.settings.storage.step2")}</li>
              </ol>
              <Form.Item label={t("pages.settings.storage.code")} htmlFor={`code-${role}`}>
                <Input id={`code-${role}`} value={code} onChange={(e) => setCode(e.target.value)} required autoComplete="off" spellCheck={false} />
              </Form.Item>
              <Space>
                <Button type="primary" htmlType="submit" loading={finish.isPending} disabled={!code.trim()}>
                  {t("pages.settings.storage.finish")}
                </Button>
                <Button onClick={() => setUrl("")}>{t("pages.settings.storage.cancel")}</Button>
              </Space>
            </Form>
          )}
          {err && <Alert type="error" showIcon title={err.message} />}
          {finish.isSuccess && !url && <Alert type="success" showIcon title={t("pages.settings.storage.saved")} />}
        </Space>
      </Card>
    </section>
  );
}

/** One click: the browser goes to Dropbox (sign in if needed, Allow twice: read, then write) and comes back. */
function OneClick({ s }: { s: Status | undefined }) {
  const { t } = useTranslation();
  const go = useMutation({
    mutationFn: () => api<{ url: string }>("/storage/dropbox/connect?role=both"),
    onSuccess: (r) => window.location.assign(r.url),
  });
  const result = new URLSearchParams(window.location.search).get("dropbox");
  const both = !!(s?.reader?.connected && s?.writer?.connected);
  return (
    <Space orientation="vertical" size={8} style={{ width: "100%" }}>
      {result === "connected" && <Alert type="success" showIcon title={t("pages.settings.storage.oneClick.done")} />}
      {result && result !== "connected" && <Alert type="warning" showIcon title={t(`pages.settings.storage.oneClick.${result}`, { defaultValue: t("pages.settings.storage.oneClick.failed") })} />}
      <Button type="primary" size="large" onClick={() => go.mutate()} loading={go.isPending}>
        {both ? t("pages.settings.storage.oneClick.again") : t("pages.settings.storage.oneClick.button")}
      </Button>
      <Typography.Text type="secondary" style={{ fontSize: 12 }}>{t("pages.settings.storage.oneClick.hint")}</Typography.Text>
      {go.isError && <Alert type="info" showIcon title={(go.error as Error).message} />}
    </Space>
  );
}

export function CloudStorage() {
  const { t } = useTranslation();
  const q = useQuery({ queryKey: ["storage"], queryFn: () => api<Status>("/storage/dropbox") });
  return (
    <Card title={t("pages.settings.storage.title")}>
      <Space orientation="vertical" size={16} style={{ width: "100%" }}>
        <Typography.Text type="secondary">{t("pages.settings.storage.intro")}</Typography.Text>
        {q.isError && <Alert type="error" showIcon title={(q.error as Error).message} />}
        <OneClick s={q.data} />
        <Collapse
          size="small"
          items={[{
            key: "manual",
            label: t("pages.settings.storage.oneClick.manual"),
            children: (
              <Space orientation="vertical" size={16} style={{ width: "100%" }}>
                {(["reader", "writer"] as Role[]).map((r) => (
                  <Connection key={`${r}-${q.data?.[r]?.app_key ?? ""}`} role={r} c={q.data?.[r]} loading={q.isLoading} />
                ))}
              </Space>
            ),
          }]}
        />
        <Collapse
          size="small"
          ghost
          items={[
            {
              key: "help",
              label: t("pages.settings.storage.helpTitle"),
              children: (
                <ol style={{ paddingLeft: 20, margin: 0 }}>
                  <li>{t("pages.settings.storage.help1")}</li>
                  <li>{t("pages.settings.storage.help2")}</li>
                  <li>{t("pages.settings.storage.help3")}</li>
                </ol>
              ),
            },
          ]}
        />
      </Space>
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
    <Card title={t("pages.settings.google.title")}>
      <Space orientation="vertical" size={16} style={{ width: "100%" }}>
        <Typography.Text type="secondary">{t("pages.settings.google.intro")}</Typography.Text>
        {result === "connected" && <Alert type="success" showIcon title={t("pages.settings.google.connectedNow")} />}
        {result === "error" && <Alert type="error" showIcon title={t("pages.settings.google.failed", { reason: params.get("reason") || "" })} />}
        {q.isLoading && <Typography.Text type="secondary">{t("pages.settings.storage.checking")}</Typography.Text>}
        {s && (
          <Alert
            type="info"
            title={t("pages.settings.google.redirect")}
            description={<Typography.Text code copyable style={{ wordBreak: "break-all" }}>{s.redirect_uri}</Typography.Text>}
          />
        )}
        {s && !showClientForm && (
          <Space wrap style={{ width: "100%", justifyContent: "space-between" }}>
            <span style={{ wordBreak: "break-all" }}>{t("pages.settings.google.clientSet", { id: s.client_id })}</span>
            <Button onClick={() => setEditClient(true)}>{t("pages.settings.google.changeClient")}</Button>
          </Space>
        )}
        {showClientForm && (
          <Form layout="vertical" onFinish={() => save.mutate()}>
            <Form.Item label={t("pages.settings.google.clientId")} htmlFor="g-client-id">
              <Input id="g-client-id" value={cid} onChange={(e) => setCid(e.target.value)} placeholder="123…-abc.apps.googleusercontent.com" required autoComplete="off" spellCheck={false} />
            </Form.Item>
            <Form.Item label={t("pages.settings.google.clientSecret")} htmlFor="g-client-secret">
              <Input id="g-client-secret" type="password" value={secret} onChange={(e) => setSecret(e.target.value)} required autoComplete="off" />
            </Form.Item>
            <Button type="primary" htmlType="submit" loading={save.isPending}>
              {t("pages.settings.google.saveClient")}
            </Button>
          </Form>
        )}
        {s?.client_configured &&
          (["reader", "writer"] as Role[]).map((role) => (
            <section key={role} aria-labelledby={`g-${role}`}>
              <Card
                size="small"
                title={
                  <h3 id={`g-${role}`} style={{ margin: 0, fontSize: 16 }}>
                    {t(`pages.settings.storage.${role}`)}
                  </h3>
                }
                extra={
                  <Tag color={s[role].connected ? (s[role].account ? "success" : "warning") : "default"} style={{ marginInlineEnd: 0, whiteSpace: "normal" }}>
                    {!s[role].connected
                      ? t("pages.settings.storage.notConnected")
                      : s[role].account
                        ? t("pages.settings.storage.connectedAs", { name: s[role].account!.name, email: s[role].account!.email })
                        : t("pages.settings.storage.connectedUnchecked")}
                  </Tag>
                }
              >
                <Space>
                  <Button type="primary" onClick={() => start.mutate(role)} disabled={start.isPending}>
                    {s[role].connected ? t("pages.settings.storage.reconnect") : t("pages.settings.storage.connect")}
                  </Button>
                  {s[role].connected && (
                    <Popconfirm title={t("pages.settings.storage.disconnectConfirm")} onConfirm={() => drop.mutate(role)}>
                      <Button danger disabled={drop.isPending}>
                        {t("pages.settings.storage.disconnect")}
                      </Button>
                    </Popconfirm>
                  )}
                </Space>
              </Card>
            </section>
          ))}
        {err && <Alert type="error" showIcon title={err.message} />}
        <Collapse
          size="small"
          ghost
          items={[
            {
              key: "help",
              label: t("pages.settings.google.helpTitle"),
              children: (
                <ol style={{ paddingLeft: 20, margin: 0 }}>
                  <li>{t("pages.settings.google.help1")}</li>
                  <li>{t("pages.settings.google.help2")}</li>
                  <li>{t("pages.settings.google.help3")}</li>
                  <li>{t("pages.settings.google.help4")}</li>
                </ol>
              ),
            },
          ]}
        />
      </Space>
    </Card>
  );
}
