import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Button, Empty, Input, Progress, Segmented, Space, Table, Tag, Typography } from "antd";
import { CaretDownOutlined, CaretRightOutlined } from "@ant-design/icons";
import { api } from "../net/client";

export type FileState = "pending" | "processing" | "ok" | "below" | "unprocessable" | "publishing" | "published";
export const STATES: FileState[] = ["pending", "processing", "ok", "below", "unprocessable", "publishing", "published"];

export interface FileRow {
  rel: string;
  name: string;
  kind: string | null;
  size: number | null;
  state: FileState;
  accuracy: number | null;
  diffs: number;
  number_diffs: number;
  reason: string | null;
  detail: string | null;
  pages: number | null;
}

type Counts = Record<FileState, number> & { total: number };
const zero = (): Counts => ({ total: 0, pending: 0, processing: 0, ok: 0, below: 0, unprocessable: 0, publishing: 0, published: 0 });

interface Node {
  key: string;
  name: string;
  depth: number;
  folder: boolean;
  file?: FileRow;
  counts?: Counts;
  kids?: Node[];
}

/** The folder structure of the source, built from the file paths. Every folder carries the roll-up of everything below it. */
export function buildTree(files: FileRow[]): Node {
  const root: Node = { key: "", name: "", depth: -1, folder: true, counts: zero(), kids: [] };
  const index = new Map<string, Node>([["", root]]);
  for (const f of files) {
    const parts = f.rel.split("/").filter(Boolean);
    let parent = root;
    let path = "";
    const chain: Node[] = [root];                       // the folders this file sits in, from the top
    for (let i = 0; i < parts.length - 1; i++) {
      path += "/" + parts[i];
      let n = index.get(path);
      if (!n) {
        n = { key: path, name: parts[i], depth: i, folder: true, counts: zero(), kids: [] };
        index.set(path, n);
        parent.kids!.push(n);
      }
      parent = n;
      chain.push(n);
    }
    parent.kids!.push({ key: f.rel, name: parts[parts.length - 1] ?? f.rel, depth: parts.length - 1, folder: false, file: f });
    for (const n of chain) {
      n.counts!.total += 1;
      n.counts![f.state] += 1;
    }
  }
  const sort = (n: Node) => {
    n.kids?.sort((a, b) => (a.folder === b.folder ? a.name.localeCompare(b.name, undefined, { numeric: true }) : a.folder ? -1 : 1));
    n.kids?.forEach(sort);
  };
  sort(root);
  return root;
}

/** The rows that are visible: a folder's children are listed only when it is expanded. */
export function flatten(root: Node, open: Set<string>): Node[] {
  const out: Node[] = [];
  const walk = (n: Node) => {
    for (const k of n.kids ?? []) {
      out.push(k);
      if (k.folder && open.has(k.key)) walk(k);
    }
  };
  walk(root);
  return out;
}

const TONE: Record<FileState, string> = {
  pending: "default",
  processing: "processing",
  ok: "success",
  below: "warning",
  unprocessable: "error",
  publishing: "processing",
  published: "success",
};

export function StateTag({ state, detail }: { state: FileState; detail?: string }) {
  const { t } = useTranslation();
  return (
    <Tag color={TONE[state]} style={{ marginInlineEnd: 0 }}>
      {t(`pages.distill.state.${state}`)}
      {detail ? ` · ${detail}` : ""}
    </Tag>
  );
}

function rollupText(c: Counts, t: (k: string, o?: Record<string, unknown>) => string): string {
  const parts: string[] = [];
  for (const s of ["ok", "published", "below", "unprocessable", "processing", "publishing"] as FileState[]) {
    if (c[s]) parts.push(`${t(`pages.distill.state.${s}`)} ${c[s]}`);
  }
  return parts.join(" · ") || t("pages.distill.notStarted");
}

const storeKey = (room: string) => `fidelity.distill.open.${room}`;

function loadOpen(room: string): Set<string> {
  try {
    return new Set(JSON.parse(sessionStorage.getItem(storeKey(room)) || "[]") as string[]);
  } catch {
    return new Set();
  }
}

/** All files of a room, in pages of 1000. */
async function loadFiles(room: string, state: string, q: string): Promise<FileRow[]> {
  const out: FileRow[] = [];
  for (let offset = 0; offset < 50000; offset += 1000) {
    const qs = new URLSearchParams({ offset: String(offset), limit: "1000" });
    if (state) qs.set("state", state);
    if (q) qs.set("q", q);
    const r = await api<{ total: number; files: FileRow[] }>(`/rooms/${room}/files?${qs}`);
    out.push(...r.files);
    if (out.length >= r.total) break;
  }
  return out;
}

export function RoomFiles({ roomId, live }: { roomId: string; live: boolean }) {
  const { t } = useTranslation();
  const [state, setState] = useState<string>("");
  const [q, setQ] = useState("");
  const [open, setOpen] = useState<Set<string>>(() => loadOpen(roomId));
  const files = useQuery({
    queryKey: ["room-files", roomId, state, q],
    queryFn: () => loadFiles(roomId, state, q),
    refetchInterval: live ? 3000 : false,
  });
  const tree = useMemo(() => buildTree(files.data ?? []), [files.data]);
  // searching shows where the hits are: every folder above a hit opens
  const effective = useMemo(() => {
    if (!q) return open;
    const all = new Set(open);
    const walk = (n: Node) => {
      if (n.folder && n.key) all.add(n.key);
      n.kids?.forEach(walk);
    };
    walk(tree);
    return all;
  }, [open, q, tree]);
  const rows = useMemo(() => flatten(tree, effective), [tree, effective]);

  useEffect(() => {
    try {
      sessionStorage.setItem(storeKey(roomId), JSON.stringify([...open]));
    } catch {
      /* storage unavailable: the tree still works, it just forgets on reload */
    }
  }, [open, roomId]);

  const toggle = (k: string) =>
    setOpen((p) => {
      const n = new Set(p);
      if (n.has(k)) n.delete(k);
      else n.add(k);
      return n;
    });
  const allFolders = (pred: (n: Node) => boolean) => {
    const s = new Set<string>();
    const walk = (n: Node): boolean => {
      let any = false;
      for (const k of n.kids ?? []) if (k.folder && walk(k)) any = true;
      const mine = n.folder && n.key !== "" && pred(n);
      if (mine || any) s.add(n.key);
      return mine || any;
    };
    walk(tree);
    s.delete("");
    return s;
  };

  const totals = tree.counts!;
  return (
    <Space orientation="vertical" size={10} style={{ width: "100%" }}>
      <Space wrap style={{ width: "100%", justifyContent: "space-between" }}>
        <Segmented
          size="small"
          aria-label={t("pages.distill.filterByState")}
          value={state}
          onChange={(v) => setState(String(v))}
          options={[
            { value: "", label: t("pages.distill.all") },
            ...(["below", "unprocessable", "ok", "pending"] as FileState[]).map((s) => ({ value: s, label: t(`pages.distill.state.${s}`) })),
          ]}
        />
        <Space wrap>
          <Input.Search
            size="small"
            allowClear
            placeholder={t("pages.distill.searchFiles")}
            aria-label={t("pages.distill.searchFiles")}
            onSearch={setQ}
            style={{ width: 200 }}
          />
          <Button size="small" onClick={() => setOpen(allFolders(() => true))}>{t("pages.distill.expandAll")}</Button>
          <Button size="small" onClick={() => setOpen(new Set())}>{t("pages.distill.collapseAll")}</Button>
          <Button size="small" onClick={() => setOpen(allFolders((n) => !!n.counts && (n.counts.below > 0 || n.counts.unprocessable > 0)))}>
            {t("pages.distill.expandProblems")}
          </Button>
        </Space>
      </Space>
      {files.isError && <Typography.Text type="danger" role="alert">{(files.error as Error).message}</Typography.Text>}
      {!files.isLoading && !rows.length ? (
        <Empty description={totals.total === 0 && !q && !state ? t("pages.distill.noFilesYet") : t("pages.distill.noMatch")} />
      ) : (
        <Table<Node>
          size="small"
          virtual
          pagination={false}
          rowKey="key"
          loading={files.isLoading}
          dataSource={rows}
          scroll={{ x: 760, y: 340 }}
          aria-label={t("pages.distill.files")}
          columns={[
            {
              title: t("pages.distill.colName"),
              dataIndex: "name",
              width: 380,
              render: (_: string, n) =>
                n.folder ? (
                  <span style={{ paddingLeft: n.depth * 18, display: "inline-flex", alignItems: "center", gap: 4 }}>
                    <Button
                      type="text"
                      size="small"
                      aria-expanded={effective.has(n.key)}
                      aria-label={t(effective.has(n.key) ? "pages.distill.collapse" : "pages.distill.expand", { name: n.name })}
                      icon={effective.has(n.key) ? <CaretDownOutlined /> : <CaretRightOutlined />}
                      onClick={() => toggle(n.key)}
                    />
                    <strong>{n.name}</strong>
                  </span>
                ) : (
                  <span style={{ paddingLeft: n.depth * 18 + 32 }} title={n.file!.rel}>{n.name}</span>
                ),
            },
            {
              title: t("pages.distill.colSize"),
              width: 110,
              render: (_: unknown, n) =>
                n.folder ? t("pages.distill.fileCount", { count: n.counts!.total }) : n.file!.pages ? t("pages.distill.pageCount", { count: n.file!.pages }) : "—",
            },
            {
              title: t("pages.distill.colState"),
              width: 230,
              render: (_: unknown, n) =>
                n.folder ? (
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>{rollupText(n.counts!, t)}</Typography.Text>
                ) : (
                  <StateTag state={n.file!.state} detail={n.file!.state === "unprocessable" && n.file!.reason ? t(`pages.distill.reason.${n.file!.reason}`, { defaultValue: n.file!.reason }) : n.file!.state === "below" && n.file!.diffs ? t("pages.distill.diffs", { count: n.file!.diffs }) : undefined} />
                ),
            },
            {
              title: t("pages.distill.colAccuracy"),
              width: 150,
              render: (_: unknown, n) => {
                if (n.folder) {
                  const c = n.counts!;
                  const done = c.total - c.pending - c.processing;
                  return <Progress percent={c.total ? Math.round((100 * done) / c.total) : 0} size="small" aria-label={n.name} />;
                }
                return n.file!.accuracy == null ? "—" : <strong>{n.file!.accuracy}%</strong>;
              },
            },
          ]}
        />
      )}
    </Space>
  );
}
