import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { Alert, Button, Card, Dropdown, Input, InputNumber, Popconfirm, Progress, Segmented, Space, Switch, Tabs, Tag, Typography } from "antd";
import { CaretDownOutlined, CaretRightOutlined, EditOutlined, EllipsisOutlined, PlusOutlined } from "@ant-design/icons";
import { api, json } from "../net/client";
import { useAuth } from "../auth/AuthProvider";
import { EmptyState, ErrorState, Loading, PageHeader } from "../components/ui";
import { RoomFiles } from "../components/RoomFiles";

interface Loc {
  kind: string;
  link: string;
}
interface Counts {
  total: number;
  pending: number;
  processing: number;
  ok: number;
  below: number;
  unprocessable: number;
  publishing: number;
  published: number;
  finished: number;
  rate: number;
}
interface Job {
  id: string;
  status: string;
  progress: number | null;
  message: string | null;
  position?: number;
}
export interface Room {
  id: string;
  name: string;
  source: Loc | null;
  dest: Loc | null;
  mode: "distill" | "upload";
  threshold: number;
  number_guard: boolean;
  priority: number;
  points: number;
  archived: boolean;
  updated_at: number;
  counts: Counts;
  job: Job | null;
}
interface QueueView {
  capacity: number;
  used: number;
  running: { job: string; name: string; points: number }[];
  queued: { job: string; name: string; position: number; points: number }[];
}
interface Preview {
  ok: number;
  below: number;
  published: number;
  publishing: number;
  has_dest: boolean;
  dest: string | null;
}

const isActive = (r: Room) => r.job?.status === "queued" || r.job?.status === "running";
const loc = (l: Loc | null) => l?.link ?? "";

function RoomStatus({ room }: { room: Room }) {
  const { t } = useTranslation();
  const j = room.job;
  if (j?.status === "running") return <Tag color="processing">{t("pages.distill.room.running", { pct: Math.round(j.progress ?? 0) })}</Tag>;
  if (j?.status === "queued") return <Tag>{t("pages.distill.room.queued", { n: j.position ?? 1 })}</Tag>;
  if (j?.status === "interrupted") return <Tag color="warning">{t("pages.distill.room.interrupted")}</Tag>;
  if (j?.status === "error") return <Tag color="error">{t("pages.distill.room.failed")}</Tag>;
  const c = room.counts;
  if (!c.total) return <Tag>{room.source ? t("pages.distill.room.notRun") : t("pages.distill.room.notConfigured")}</Tag>;
  if (c.below) return <Tag color="warning">{t("pages.distill.room.review", { n: c.below })}</Tag>;
  if (c.unprocessable) return <Tag color="error">{t("pages.distill.room.cannot", { n: c.unprocessable })}</Tag>;
  if (c.pending || c.processing) return <Tag>{t("pages.distill.room.partial")}</Tag>;
  return <Tag color="success">{t("pages.distill.room.done")}</Tag>;
}

function RoomBody({ room, canEdit }: { room: Room; canEdit: boolean }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [source, setSource] = useState(loc(room.source));
  const [dest, setDest] = useState(loc(room.dest));
  const [mode, setMode] = useState(room.mode);
  const [threshold, setThreshold] = useState<number>(room.threshold);
  const [guard, setGuard] = useState(room.number_guard);
  useEffect(() => {
    setSource(loc(room.source));
    setDest(loc(room.dest));
    setMode(room.mode);
    setThreshold(room.threshold);
    setGuard(room.number_guard);
  }, [room.updated_at]); // eslint-disable-line react-hooks/exhaustive-deps
  const dirty =
    source !== loc(room.source) || dest !== loc(room.dest) || mode !== room.mode || threshold !== room.threshold || guard !== room.number_guard;
  const active = isActive(room);
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ["rooms"] });
    void qc.invalidateQueries({ queryKey: ["queue"] });
    void qc.invalidateQueries({ queryKey: ["room-files", room.id] });
    void qc.invalidateQueries({ queryKey: ["accept-preview", room.id] });
  };
  const save = useMutation({
    mutationFn: () =>
      api(`/rooms/${room.id}`, { ...json({ source, dest: dest || null, mode, threshold, number_guard: guard }), method: "PATCH" }),
    onSuccess: refresh,
  });
  const run = useMutation({ mutationFn: () => api(`/rooms/${room.id}/run`, json({})), onSuccess: refresh });
  const cancel = useMutation({ mutationFn: () => api(`/rooms/${room.id}/cancel`, { method: "POST" }), onSuccess: refresh });
  const front = useMutation({ mutationFn: () => api(`/rooms/${room.id}/front`, { method: "POST" }), onSuccess: refresh });
  const preview = useQuery({ queryKey: ["accept-preview", room.id], queryFn: () => api<Preview>(`/rooms/${room.id}/accept-preview`), refetchInterval: active ? 4000 : false });
  const accept = useMutation({ mutationFn: () => api(`/rooms/${room.id}/accept`, json({ all_ok: true })), onSuccess: refresh });
  const err = (save.error || run.error || cancel.error || front.error || accept.error) as Error | null;
  const okCount = preview.data?.ok ?? 0;

  return (
    <Space orientation="vertical" size={14} style={{ width: "100%" }}>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: 12 }}>
        <label style={{ display: "grid", gap: 4 }}>
          <span style={{ fontWeight: 500 }}>{t("pages.distill.input")} <Typography.Text type="secondary" style={{ fontSize: 12 }}>({t("pages.distill.readOnly")})</Typography.Text></span>
          <Input value={source} onChange={(e) => setSource(e.target.value)} disabled={!canEdit || active} placeholder="/as 3500" autoComplete="off" spellCheck={false} />
        </label>
        <label style={{ display: "grid", gap: 4 }}>
          <span style={{ fontWeight: 500 }}>{t("pages.distill.output")}</span>
          <Input value={dest} onChange={(e) => setDest(e.target.value)} disabled={!canEdit || active} placeholder="/Transfer_Md/as 3500" autoComplete="off" spellCheck={false} />
        </label>
        <div style={{ display: "grid", gap: 4 }}>
          <span style={{ fontWeight: 500 }}>{t("pages.distill.afterDistill")}</span>
          <Segmented
            block
            disabled={!canEdit || active}
            value={mode}
            onChange={(v) => setMode(v as Room["mode"])}
            options={[
              { value: "distill", label: t("pages.distill.modeDistill") },
              { value: "upload", label: t("pages.distill.modeUpload") },
            ]}
          />
        </div>
        <div style={{ display: "grid", gap: 4 }}>
          <span style={{ fontWeight: 500 }}>{t("pages.distill.threshold")}</span>
          <Space wrap>
            <InputNumber
              min={50}
              max={100}
              step={0.1}
              value={threshold}
              onChange={(v) => v != null && setThreshold(v)}
              disabled={!canEdit}
              suffix="%"
              aria-label={t("pages.distill.threshold")}
              style={{ width: 110 }}
            />
            <Switch checked={guard} onChange={setGuard} disabled={!canEdit} aria-label={t("pages.distill.numberGuard")} />
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>{t("pages.distill.numberGuard")}</Typography.Text>
          </Space>
        </div>
      </div>

      {err && <Alert type="error" showIcon title={err.message} />}
      {room.job?.status === "interrupted" && <Alert type="warning" showIcon title={t("pages.distill.interruptedNote")} />}
      {room.job?.status === "error" && room.job.message && <Alert type="error" showIcon title={room.job.message} />}

      {canEdit && (
        <Space wrap>
          {dirty && (
            <Button type="primary" loading={save.isPending} onClick={() => save.mutate()}>
              {t("pages.distill.save")}
            </Button>
          )}
          {!active && (
            <Button type={dirty ? "default" : "primary"} disabled={dirty || !room.source} loading={run.isPending} onClick={() => run.mutate()}>
              {room.job?.status === "interrupted" ? t("pages.distill.resume") : t("pages.distill.start")}
            </Button>
          )}
          {active && <Button loading={cancel.isPending} onClick={() => cancel.mutate()}>{t("pages.distill.cancel")}</Button>}
          {room.job?.status === "queued" && <Button loading={front.isPending} onClick={() => front.mutate()}>{t("pages.distill.front")}</Button>}
          <Popconfirm
            title={t("pages.distill.acceptTitle", { count: okCount })}
            description={t("pages.distill.acceptBody", { dest: preview.data?.dest ?? "" })}
            okText={t("pages.distill.acceptOk")}
            cancelText={t("pages.distill.cancel")}
            onConfirm={() => accept.mutate()}
            disabled={!okCount || active || !preview.data?.has_dest}
          >
            <Button disabled={!okCount || active || !preview.data?.has_dest} loading={accept.isPending}>
              {t("pages.distill.accept", { count: okCount })}
            </Button>
          </Popconfirm>
          {!preview.data?.has_dest && okCount > 0 && <Typography.Text type="secondary" style={{ fontSize: 12 }}>{t("pages.distill.needOutput")}</Typography.Text>}
        </Space>
      )}
      {room.job?.status === "running" && room.job.message && (
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>{room.job.message}</Typography.Text>
      )}
      <RoomFiles roomId={room.id} live={active || (preview.data?.publishing ?? 0) > 0} />
    </Space>
  );
}

function RoomCard({ room, open, onToggle, canEdit }: { room: Room; open: boolean; onToggle: () => void; canEdit: boolean }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(room.name);
  const [note, setNote] = useState<string | null>(null);
  useEffect(() => setName(room.name), [room.name]);
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ["rooms"] });
    void qc.invalidateQueries({ queryKey: ["queue"] });
  };
  const rename = useMutation({
    mutationFn: (n: string) => api(`/rooms/${room.id}`, { ...json({ name: n }), method: "PATCH" }),
    onSuccess: () => {
      setEditing(false);
      refresh();
    },
  });
  const archive = useMutation({
    mutationFn: () => api(`/rooms/${room.id}/${room.archived ? "unarchive" : "archive"}`, { method: "POST" }),
    onSuccess: () => {
      setNote(null);
      refresh();
    },
    onError: (e: Error) => setNote(e.message),
  });
  const remove = useMutation({
    mutationFn: () => api(`/rooms/${room.id}`, { method: "DELETE" }),
    onSuccess: refresh,
    onError: (e: Error) => setNote(e.message),
  });
  const c = room.counts;
  return (
    <Card size="small" styles={{ body: { padding: open ? 16 : 0 } }} style={{ borderColor: open ? "var(--ant-color-primary)" : undefined }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12, padding: open ? "0 0 12px" : "10px 16px", flexWrap: "wrap" }}>
        <Button
          type="text"
          aria-expanded={open}
          aria-label={t(open ? "pages.distill.collapseRoom" : "pages.distill.expandRoom", { name: room.name })}
          icon={open ? <CaretDownOutlined /> : <CaretRightOutlined />}
          onClick={onToggle}
        />
        {editing ? (
          <Input
            autoFocus
            style={{ width: 220 }}
            value={name}
            maxLength={80}
            aria-label={t("pages.distill.rename")}
            onChange={(e) => setName(e.target.value)}
            onPressEnter={() => name.trim() && rename.mutate(name)}
            onBlur={() => (name.trim() && name !== room.name ? rename.mutate(name) : setEditing(false))}
          />
        ) : (
          <Space size={4}>
            <Typography.Text strong style={{ fontSize: 15 }}>{room.name}</Typography.Text>
            {canEdit && <Button type="text" size="small" aria-label={t("pages.distill.rename")} icon={<EditOutlined />} onClick={() => setEditing(true)} />}
          </Space>
        )}
        <RoomStatus room={room} />
        <span style={{ flex: 1 }} />
        <Space size={16} wrap>
          <Typography.Text style={{ fontSize: 13 }}><Typography.Text type="secondary">{t("pages.distill.files")} </Typography.Text><strong>{c.total}</strong></Typography.Text>
          <Typography.Text style={{ fontSize: 13 }}><Typography.Text type="secondary">{t("pages.distill.finished")} </Typography.Text><strong>{c.finished}</strong></Typography.Text>
          <Typography.Text style={{ fontSize: 13 }}><Typography.Text type="secondary">{t("pages.distill.rate")} </Typography.Text><strong>{Math.round(c.rate)}%</strong></Typography.Text>
          <Progress percent={Math.round(c.rate)} size="small" showInfo={false} style={{ width: 90, margin: 0 }} aria-label={t("pages.distill.rate")} />
        </Space>
        {canEdit && (
          <Dropdown
            trigger={["click"]}
            menu={{
              items: [
                { key: "archive", label: room.archived ? t("pages.distill.unarchive") : t("pages.distill.archive"), onClick: () => archive.mutate() },
                ...(!room.archived ? [{ key: "delete", danger: true, label: t("pages.distill.delete"), onClick: () => remove.mutate() }] : []),
              ],
            }}
          >
            <Button type="text" aria-label={t("pages.distill.more")} icon={<EllipsisOutlined />} />
          </Dropdown>
        )}
      </div>
      {!open && (
        <div style={{ padding: "0 16px 10px 56px" }}>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            {room.source ? loc(room.source) : t("pages.distill.noInput")} → {room.mode === "upload" && room.dest ? loc(room.dest) : t("pages.distill.keepLocal")}
          </Typography.Text>
        </div>
      )}
      {note && <Alert type="warning" showIcon closable onClose={() => setNote(null)} title={note} style={{ margin: open ? "0 0 12px" : "0 16px 10px" }} />}
      {open && <RoomBody room={room} canEdit={canEdit} />}
    </Card>
  );
}

export function DistillPage() {
  const { t } = useTranslation();
  const { me } = useAuth();
  const qc = useQueryClient();
  const canEdit = me?.role === "reviewer" || me?.role === "admin";
  const [tab, setTab] = useState<"active" | "archived">("active");
  const [open, setOpen] = useState<Set<string> | null>(null);
  const rooms = useQuery({
    queryKey: ["rooms", tab],
    queryFn: () => api<{ rooms: Room[] }>(`/rooms?archived=${tab === "archived"}`),
    refetchInterval: (q) => (q.state.data?.rooms.some(isActive) ? 3000 : 15000),
  });
  const queue = useQuery({ queryKey: ["queue"], queryFn: () => api<QueueView>("/queue"), refetchInterval: 5000 });
  const create = useMutation({
    mutationFn: () => api<Room>("/rooms", json({})),
    onSuccess: (r) => {
      setOpen((p) => new Set([...(p ?? []), r.id]));
      void qc.invalidateQueries({ queryKey: ["rooms"] });
    },
  });
  const list = rooms.data?.rooms ?? [];
  // the first room is open by default, the others are folded away
  const shown = open ?? new Set(list[0] ? [list[0].id] : []);
  const toggle = (id: string) =>
    setOpen(() => {
      const n = new Set(shown);
      if (n.has(id)) n.delete(id);
      else n.add(id);
      return n;
    });
  const q = queue.data;
  return (
    <Space orientation="vertical" size={16} style={{ width: "100%" }}>
      <PageHeader title={t("pages.distill.title")} />
      <Typography.Text type="secondary">{t("pages.distill.intro")}</Typography.Text>
      {q && (
        <Card size="small">
          <Space wrap size={16}>
            <strong>{t("pages.distill.queue")}</strong>
            <span>{t("pages.distill.capacity", { used: q.used, cap: q.capacity })}</span>
            <span>{t("pages.distill.runningCount", { n: q.running.length })}</span>
            <span>{t("pages.distill.waitingCount", { n: q.queued.length })}</span>
            {q.queued.length > 0 && <Typography.Text type="secondary">{q.queued.map((x) => `${x.position}. ${x.name}`).join("  ")}</Typography.Text>}
          </Space>
        </Card>
      )}
      {/* the button sits beside the tabs, not inside the tab list (a tab list may only hold tabs) */}
      <div style={{ display: "flex", alignItems: "flex-end", gap: 12, flexWrap: "wrap" }}>
        <Tabs
          style={{ flex: 1, minWidth: 220, marginBottom: -16 }}
          activeKey={tab}
          onChange={(k) => setTab(k as "active" | "archived")}
          items={[
            { key: "active", label: t("pages.distill.tabActive") },
            { key: "archived", label: t("pages.distill.tabArchived") },
          ]}
        />
        {canEdit && tab === "active" && (
          <Button type="primary" icon={<PlusOutlined />} loading={create.isPending} onClick={() => create.mutate()}>
            {t("pages.distill.newRoom")}
          </Button>
        )}
      </div>
      {rooms.isLoading && <Loading />}
      {rooms.isError && <ErrorState message={(rooms.error as Error).message} onRetry={() => void rooms.refetch()} />}
      {!rooms.isLoading && !rooms.isError && list.length === 0 && (
        <EmptyState
          title={tab === "active" ? t("pages.distill.emptyTitle") : t("pages.distill.emptyArchived")}
          hint={tab === "active" ? t("pages.distill.emptyHint") : undefined}
        />
      )}
      <Space orientation="vertical" size={10} style={{ width: "100%" }}>
        {list.map((r) => (
          <RoomCard key={r.id} room={r} open={shown.has(r.id)} onToggle={() => toggle(r.id)} canEdit={canEdit} />
        ))}
      </Space>
      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
        <Link to="/sources">{t("pages.distill.oldPage")}</Link>
      </Typography.Text>
    </Space>
  );
}
