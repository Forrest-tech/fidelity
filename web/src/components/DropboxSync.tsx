import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Alert, Button, Card, Checkbox, Col, Collapse, Form, Input, Popconfirm, Progress, Row, Space, Statistic, Steps, Switch, Tag, Typography } from "antd";
import { StopOutlined } from "@ant-design/icons";
import { api, json } from "../net/client";

interface Params { source_link?: string; dest_link?: string; dry_run?: boolean; force?: boolean; only?: string; rollback?: string }
interface Run { id: string; status: string; progress: number; message: string; created_at: number; params: Params }
interface Doc { source: string; verdict: string }
interface Summary {
  exit_code: number;
  published_run?: string;
  report?: { documents?: Doc[]; unchanged?: string[]; duplicates?: unknown[]; unsupported?: unknown[]; triaged_out?: unknown[]; source_unchanged?: boolean };
}
interface LiveStatus {
  started: number; updated: number; total: number; index: number; file: string; stage: string;
  page: number; pages: number; scan: boolean; counts: Record<string, number>; skipped: number;
}
interface RunDetail extends Run { log: string[]; summary: Summary | null; live?: LiveStatus | null }

function useNow(active: boolean) {
  const [now, setNow] = useState(() => Date.now() / 1000);
  useEffect(() => {
    if (!active) return;
    const t = window.setInterval(() => setNow(Date.now() / 1000), 1000);
    return () => window.clearInterval(t);
  }, [active]);
  return now;
}

function dur(sec: number) {
  const s = Math.max(0, Math.floor(sec));
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), r = s % 60;
  return h ? `${h}h ${m}m` : m ? `${m}m ${r}s` : `${r}s`;
}

// The stages of one file, in order; the step shown as current follows the sync's own stage names.
const STEPS = ["listing", "downloading", "ocr", "verifying", "uploading", "publishing"] as const;
const STEP_OF: Record<string, number> = {
  starting: 0, listing: 0, preparing: 1, downloading: 1, ocr: 2, verifying: 3, uploading: 4, next: 4, publishing: 5, finished: 5,
};

function LivePanel({ run, canEdit }: { run: RunDetail; canEdit: boolean }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const live = run.live;
  const now = useNow(true);
  const stop = useMutation({
    mutationFn: () => api(`/dropbox/sync/${run.id}/cancel`, { method: "POST" }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["dropbox-runs"] }),
  });
  const started = run.created_at; // one clock for the whole run, so the elapsed time never jumps back
  const quiet = live ? now - live.updated : 0;
  const stage = live?.stage ?? "starting";
  const c = live?.counts ?? {};
  return (
    <Card
      size="small"
      aria-live="polite"
      title={
        <Space>
          <span aria-hidden="true" className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-current border-t-transparent" />
          <span>{t(`pages.sources.dropbox.stage.${stage}`, { defaultValue: stage })}</span>
          {live && live.total > 0 && live.index > 0 && (
            <Typography.Text type="secondary">{t("pages.sources.dropbox.fileOf", { index: live.index, total: live.total })}</Typography.Text>
          )}
        </Space>
      }
      extra={<Typography.Text type="secondary">{t("pages.sources.dropbox.elapsed", { time: dur(now - started) })}</Typography.Text>}
    >
      <Space orientation="vertical" size={12} style={{ width: "100%" }}>
        <Steps size="small" current={STEP_OF[stage] ?? 0} responsive items={STEPS.map((k) => ({ title: t(`pages.sources.dropbox.step.${k}`) }))} />
        {live?.file && (
          <Typography.Text ellipsis={{ tooltip: live.file }} code style={{ maxWidth: "100%" }}>
            {live.file}
          </Typography.Text>
        )}
        <div>
          <Typography.Text type="secondary">{t("pages.sources.dropbox.progress")}</Typography.Text>
          <Progress percent={Math.round(run.progress)} status="active" aria-label={t("pages.sources.dropbox.progress")} />
        </div>
        {stage === "ocr" && live && live.pages > 0 && (
          <div>
            <Typography.Text type="secondary">{t("pages.sources.dropbox.ocrPage", { page: live.page, pages: live.pages })}</Typography.Text>
            <Progress
              percent={Math.round((100 * live.page) / live.pages)}
              status="active"
              strokeColor="#13c2c2"
              aria-label={t("pages.sources.dropbox.ocrProgress")}
            />
          </div>
        )}
        {live?.scan && <Alert type="info" showIcon title={t("pages.sources.dropbox.scanHint")} />}
        <Row gutter={[16, 8]}>
          <Col xs={12} sm={6}>
            <Statistic title={t("pages.sources.dropbox.pass")} value={c.PASS ?? 0} styles={{ content: { color: "var(--ant-color-success)" } }} />
          </Col>
          <Col xs={12} sm={6}>
            <Statistic title={t("pages.sources.dropbox.review")} value={c.REVIEW ?? 0} styles={{ content: { color: "var(--ant-color-warning)" } }} />
          </Col>
          <Col xs={12} sm={6}>
            <Statistic title={t("pages.sources.dropbox.fail")} value={c.FAIL ?? 0} styles={{ content: { color: "var(--ant-color-error)" } }} />
          </Col>
          <Col xs={12} sm={6}>
            <Statistic title={t("pages.sources.dropbox.unchanged")} value={live?.skipped ?? 0} />
          </Col>
        </Row>
        <Space wrap style={{ width: "100%", justifyContent: "space-between" }}>
          <Typography.Text type="secondary">{t("pages.sources.dropbox.lastActivity", { time: dur(quiet) })}</Typography.Text>
          {canEdit && (
            <Popconfirm title={t("pages.sources.dropbox.cancelConfirm")} onConfirm={() => stop.mutate()}>
              <Button danger icon={<StopOutlined />} disabled={stop.isPending}>
                {t("pages.sources.dropbox.cancel")}
              </Button>
            </Popconfirm>
          )}
        </Space>
        {quiet > 120 && <Alert type="warning" title={t("pages.sources.dropbox.quiet")} />}
        {stop.isError && <Alert type="error" showIcon title={(stop.error as Error).message} />}
      </Space>
    </Card>
  );
}

const KEY = "fidelity.dropboxLinks";
const active = (s: string) => s === "queued" || s === "running";
const TAG: Record<string, string> = { done: "success", error: "error", running: "processing", queued: "default" };

function loadLinks(): { src: string; dest: string } {
  try {
    return JSON.parse(localStorage.getItem(KEY) || "") as { src: string; dest: string };
  } catch {
    return { src: "", dest: "" };
  }
}

function Counts({ s }: { s: Summary }) {
  const { t } = useTranslation();
  const docs = s.report?.documents ?? [];
  const n = (v: string) => docs.filter((d) => d.verdict === v).length;
  const items: Array<[string, number, string?]> = [
    [t("pages.sources.dropbox.pass"), n("PASS") + n("METADATA"), "var(--ant-color-success)"],
    [t("pages.sources.dropbox.review"), n("REVIEW"), "var(--ant-color-warning)"],
    [t("pages.sources.dropbox.fail"), n("FAIL"), "var(--ant-color-error)"],
    [t("pages.sources.dropbox.unchanged"), s.report?.unchanged?.length ?? 0],
    [t("pages.sources.dropbox.duplicates"), s.report?.duplicates?.length ?? 0],
    [t("pages.sources.dropbox.unsupported"), (s.report?.unsupported?.length ?? 0) + (s.report?.triaged_out?.length ?? 0)],
  ];
  return (
    <Space orientation="vertical" size={8} style={{ width: "100%" }}>
      <Row gutter={[16, 8]}>
        {items.map(([k, v, c]) => (
          <Col key={k} xs={8} sm={4}>
            <Statistic title={k} value={v} styles={{ content: c ? { color: c } : undefined }} />
          </Col>
        ))}
      </Row>
      {s.report && (
        <Alert
          type={s.report.source_unchanged ? "success" : "error"}
          showIcon
          title={s.report.source_unchanged ? t("pages.sources.dropbox.sourceOk") : t("pages.sources.dropbox.sourceChanged")}
        />
      )}
    </Space>
  );
}

function RunView({ id, isAdmin, canEdit }: { id: string; isAdmin: boolean; canEdit: boolean }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const q = useQuery({
    queryKey: ["dropbox-run", id],
    queryFn: () => api<RunDetail>(`/dropbox/sync/${id}`),
    refetchInterval: (query) => (query.state.data && !active(query.state.data.status) ? false : 3000),
  });
  const undo = useMutation({
    mutationFn: (run: string) =>
      api<{ job: string }>("/dropbox/rollback", json({ source_link: q.data?.params.source_link, dest_link: q.data?.params.dest_link, run })),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["dropbox-runs"] }),
  });
  if (!q.data) return null;
  const r = q.data;
  const published = r.summary?.published_run;
  return (
    <Space orientation="vertical" size={12} style={{ width: "100%" }}>
      {active(r.status) && <LivePanel run={r} canEdit={canEdit} />}
      {r.status === "error" && r.message && <Alert type="error" showIcon title={r.message} />}
      {r.summary && <Counts s={r.summary} />}
      {published && isAdmin && (
        <Space wrap>
          <span>{t("pages.sources.dropbox.published", { run: published })}</span>
          <Popconfirm title={t("pages.sources.dropbox.rollbackConfirm", { run: published })} onConfirm={() => undo.mutate(published)}>
            <Button danger disabled={undo.isPending}>
              {t("pages.sources.dropbox.rollback")}
            </Button>
          </Popconfirm>
          {undo.isError && <Typography.Text type="danger">{(undo.error as Error).message}</Typography.Text>}
          {undo.isSuccess && <span role="status">{t("pages.sources.dropbox.rollbackStarted")}</span>}
        </Space>
      )}
      <Collapse
        size="small"
        ghost
        defaultActiveKey={active(r.status) ? ["log"] : []}
        items={[
          {
            key: "log",
            label: t("pages.sources.dropbox.log"),
            children: (
              <pre className="max-h-72 overflow-auto whitespace-pre-wrap break-all text-xs" tabIndex={0}>
                {r.log.join("\n") || "…"}
              </pre>
            ),
          },
        ]}
      />
    </Space>
  );
}

export function DropboxSync({ canEdit, isAdmin }: { canEdit: boolean; isAdmin: boolean }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const saved = loadLinks();
  const [src, setSrc] = useState(saved.src);
  const [dest, setDest] = useState(saved.dest);
  const [dry, setDry] = useState(true);
  const [force, setForce] = useState(false);
  const [only, setOnly] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const status = useQuery({
    queryKey: ["dropbox-status"],
    queryFn: () => api<{ reader: boolean; writer: boolean; google?: { reader: boolean; writer: boolean } }>("/dropbox/status"),
  });
  const runs = useQuery({
    queryKey: ["dropbox-runs"],
    queryFn: () => api<{ runs: Run[] }>("/dropbox/sync"),
    refetchInterval: (query) => ((query.state.data?.runs ?? []).some((r) => active(r.status)) ? 3000 : false),
  });
  const start = useMutation({
    mutationFn: () => api<{ job: string }>("/dropbox/sync", json({ source_link: src, dest_link: dest, dry_run: dry, force, only })),
    onSuccess: (r) => {
      setOpen(r.job);
      void qc.invalidateQueries({ queryKey: ["dropbox-runs"] });
    },
  });
  useEffect(() => {
    try {
      localStorage.setItem(KEY, JSON.stringify({ src, dest }));
    } catch {
      /* storage may be unavailable */
    }
  }, [src, dest]);
  const isGoogle = (v: string) => /^(https:\/\/drive\.google\.com\/|gdrive:)/.test(v.trim());
  const has = (link: string, role: "reader" | "writer") => (isGoogle(link) ? !!status.data?.google?.[role] : !!status.data?.[role]);
  const ready = has(src || "/", "reader") && has(dest || "/", "writer");
  const missing = [
    !has(src || "/", "reader") && (isGoogle(src) ? "Google Drive reader" : "Dropbox reader"),
    !has(dest || "/", "writer") && (isGoogle(dest) ? "Google Drive writer" : "Dropbox writer"),
  ]
    .filter(Boolean)
    .join(", ");
  const list = Array.isArray(runs.data?.runs) ? runs.data!.runs : [];
  const busy = list.some((r) => active(r.status));
  const runningId = list.find((r) => active(r.status))?.id;
  useEffect(() => {
    if (runningId) setOpen((o) => o ?? runningId);
  }, [runningId]);
  const placeholder = "/Folder · https://www.dropbox.com/… · https://drive.google.com/drive/folders/…";
  const kind = (r: Run) =>
    r.params?.rollback ? t("pages.sources.dropbox.kindRollback") : r.params?.dry_run ? t("pages.sources.dropbox.kindDry") : t("pages.sources.dropbox.kindPublish");

  return (
    <Card style={{ marginBottom: 16 }} title={t("pages.sources.dropbox.title")}>
      <Space orientation="vertical" size={16} style={{ width: "100%" }}>
        <Typography.Text type="secondary">{t("pages.sources.dropbox.intro")}</Typography.Text>
        {status.data && typeof status.data.reader === "boolean" && !ready && (
          <Alert type="warning" showIcon title={t("pages.sources.dropbox.notAuthorised", { roles: missing })} />
        )}
        {canEdit && (
          <Form layout="vertical" onFinish={() => start.mutate()} requiredMark={false}>
            <Row gutter={16}>
              <Col xs={24} lg={12}>
                <Form.Item label={t("pages.sources.dropbox.source")} htmlFor="sync-src">
                  <Input id="sync-src" value={src} onChange={(e) => setSrc(e.target.value)} placeholder={placeholder} required />
                </Form.Item>
              </Col>
              <Col xs={24} lg={12}>
                <Form.Item label={t("pages.sources.dropbox.dest")} htmlFor="sync-dest">
                  <Input id="sync-dest" value={dest} onChange={(e) => setDest(e.target.value)} placeholder={placeholder} required />
                </Form.Item>
              </Col>
            </Row>
            <Form.Item label={t("pages.sources.dropbox.only")} htmlFor="sync-only">
              <Input id="sync-only" value={only} onChange={(e) => setOnly(e.target.value)} />
            </Form.Item>
            <Space size={24} wrap style={{ marginBottom: 16 }}>
              <Space>
                <Switch id="sync-dry" checked={dry} onChange={setDry} />
                <label htmlFor="sync-dry">{t("pages.sources.dropbox.dryRun")}</label>
              </Space>
              <Checkbox checked={force} onChange={(e) => setForce(e.target.checked)}>
                {t("pages.sources.dropbox.force")}
              </Checkbox>
            </Space>
            <Space wrap>
              <Button type="primary" htmlType="submit" loading={start.isPending} disabled={busy || !ready}>
                {dry ? t("pages.sources.dropbox.startDry") : t("pages.sources.dropbox.startPublish")}
              </Button>
              {busy && <Typography.Text type="secondary">{t("pages.sources.dropbox.busy")}</Typography.Text>}
              {start.isError && (
                <Typography.Text type="danger" role="alert">
                  {(start.error as Error).message}
                </Typography.Text>
              )}
            </Space>
            <div style={{ marginTop: 8 }}>
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                {t("pages.sources.dropbox.safety")}
              </Typography.Text>
            </div>
          </Form>
        )}
        {list.length > 0 && (
          <div>
            <Typography.Title level={5}>{t("pages.sources.dropbox.recent")}</Typography.Title>
            <Collapse
              accordion
              destroyOnHidden
              activeKey={open ? [open] : []}
              onChange={(k) => setOpen((Array.isArray(k) ? k[0] : k) ?? null)}
              items={list.slice(0, 10).map((r) => ({
                key: r.id,
                label: (
                  <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 8, minWidth: 0 }}>
                    <Tag color={TAG[r.status] ?? "default"} style={{ marginInlineEnd: 0 }}>
                      {t(`pages.sources.dropbox.status.${r.status}`, { defaultValue: r.status })}
                    </Tag>
                    <span>{kind(r)}</span>
                    <Typography.Text type="secondary">{new Date(r.created_at * 1000).toLocaleString()}</Typography.Text>
                    {active(r.status) && (
                      <Progress percent={Math.round(r.progress)} size="small" status="active" style={{ width: 120, margin: 0 }} aria-label={t("pages.sources.dropbox.progress")} />
                    )}
                    {r.status === "error" && r.message && (
                      <span className="fx-tiny fx-muted" title={r.message}
                        style={{ flexBasis: "100%", minWidth: 0, maxWidth: 480, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                        {r.message}
                      </span>
                    )}
                  </div>
                ),
                children: <RunView id={r.id} isAdmin={isAdmin} canEdit={canEdit} />,
              }))}
            />
          </div>
        )}
      </Space>
    </Card>
  );
}
