import { useQueries, useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { Table, Typography } from "antd";
import { api } from "../net/client";
import { EmptyState, ErrorState, Loading, PageHeader, StatusTag, TableBox } from "../components/ui";
import { loadFiles, StateTag } from "../components/RoomFiles";
import type { FileRow } from "../components/RoomFiles";
import type { Room } from "./DistillPage";

interface Doc {
  sid: string;
  rel: string;
  verdict: string;
  files: number;
  pages: number;
  single_file?: boolean;
  checks?: Record<string, boolean>;
  instruction_like?: number;
  triage?: { class: string; reason: string };
}

interface Row extends FileRow {
  room: string;
  roomName: string;
}

const STATES = ["ok", "below", "unprocessable", "published", "pending"] as const;

function notes(d: Doc, instruction: string) {
  const failed = d.checks ? Object.entries(d.checks).filter(([, ok]) => ok === false).map(([k]) => k) : [];
  return [d.triage ? `${d.triage.class}: ${d.triage.reason}` : "", d.instruction_like ? instruction : "", failed.join(", ")]
    .filter(Boolean)
    .join(" ");
}

/** Documents checked by the earlier pipeline (before rooms): shown only when there are any. */
function Earlier() {
  const { t } = useTranslation();
  const [verdict, setVerdict] = useState("");
  const q = useQuery({
    queryKey: ["documents", verdict],
    queryFn: () => api<Doc[]>("/documents" + (verdict ? `?verdict=${encodeURIComponent(verdict)}` : "")),
  });
  const any = useQuery({ queryKey: ["documents", ""], queryFn: () => api<Doc[]>("/documents") });
  if (!any.data?.length) return null;
  return (
    <section aria-labelledby="earlier" className="fx-stack" style={{ gap: 8 }}>
      <h2 id="earlier" style={{ margin: 0, fontSize: 15, fontWeight: 600 }}>{t("pages.documents.earlier")}</h2>
      <div className="fx-row" style={{ gap: 10, flexWrap: "wrap" }}>
        <span className="fx-muted fx-tiny" id="doc-filter">{t("pages.documents.filter")}</span>
        <div className="fx-chips" role="radiogroup" aria-labelledby="doc-filter">
          {[["", t("pages.documents.all")], ["PASS", t("status.PASS")], ["FAIL", t("status.FAIL")], ["SKIP", t("status.SKIP")]].map(([v, label]) => (
            <button key={v} role="radio" aria-checked={verdict === v} className={`fx-chip${verdict === v ? " on" : ""}`} onClick={() => setVerdict(v)}>{label}</button>
          ))}
        </div>
      </div>
      {q.isError && <ErrorState message={(q.error as Error).message} onRetry={() => void q.refetch()} />}
      {q.data && (
        <TableBox label={t("pages.documents.earlier")}>
        <Table<Doc>
          rowKey={(d) => d.sid + d.rel}
          dataSource={q.data}
          pagination={{ pageSize: 25, hideOnSinglePage: true, showSizeChanger: false }}
          scroll={{ x: 640 }}
          columns={[
            { title: t("pages.jobs.file"), dataIndex: "rel", render: (v: string) => <span style={{ wordBreak: "break-all" }}>{v}</span> },
            { title: t("pages.documents.result"), dataIndex: "verdict", render: (v: string) => <StatusTag status={v} /> },
            { title: t("pages.documents.pages"), dataIndex: "pages" },
            { title: t("pages.documents.files"), render: (_, d) => (d.single_file ? t("pages.documents.single") : d.files) },
            { title: t("pages.documents.notes"), render: (_, d) => <Typography.Text type="secondary">{notes(d, t("pages.documents.instruction"))}</Typography.Text> },
          ]}
        />
        </TableBox>
      )}
    </section>
  );
}

/** Results: every distilled file of every room in one list, to find a file and open it where it can be fixed. */
export function DocumentsPage() {
  const { t } = useTranslation();
  const [state, setState] = useState<string>("");
  const [q, setQ] = useState("");
  const rooms = useQuery({ queryKey: ["rooms", "all-for-results"], queryFn: async () => {
    const [a, b] = await Promise.all([api<{ rooms: Room[] }>("/rooms?archived=false"), api<{ rooms: Room[] }>("/rooms?archived=true")]);
    return [...(a.rooms ?? []), ...(b.rooms ?? [])];
  } });
  const list = (rooms.data ?? []).filter((r) => r.counts.total > 0);
  const files = useQueries({ queries: list.map((r) => ({ queryKey: ["room-files", r.id, "", ""], queryFn: () => loadFiles(r.id, "", "") })) });
  const loading = files.some((f) => f.isLoading);
  const failed = files.find((f) => f.isError);
  const rows: Row[] = useMemo(
    () => list.flatMap((r, i) => (files[i]?.data ?? []).map((f) => ({ ...f, room: r.id, roomName: r.name }))),
    [list, files],
  );
  const count = (s: string) => rows.filter((r) => r.state === s).length;
  const needle = q.trim().toLowerCase();
  const shown = rows.filter((r) => (!state || r.state === state) && (!needle || r.rel.toLowerCase().includes(needle) || r.roomName.toLowerCase().includes(needle)));
  return (
    <div className="fx-stack">
      <PageHeader title={t("pages.documents.title")} desc={t("pages.documents.intro")} />
      {rooms.isLoading && <Loading />}
      {rooms.isError && <ErrorState message={(rooms.error as Error).message} onRetry={() => void rooms.refetch()} />}
      {rooms.data && !list.length && <EmptyState title={t("pages.documents.emptyRooms")} hint={t("pages.documents.emptyRoomsHint")} />}
      {list.length > 0 && (
        <>
          <div className="fx-row" style={{ gap: 10, flexWrap: "wrap" }}>
            <div className="fx-chips" role="group" aria-label={t("pages.distill.filterByState")}>
              <button className={`fx-chip${!state ? " on" : ""}`} aria-pressed={!state} onClick={() => setState("")}>{t("pages.documents.all")} {rows.length}</button>
              {STATES.filter((s) => count(s)).map((s) => (
                <button key={s} className={`fx-chip${state === s ? " on" : ""}`} aria-pressed={state === s} onClick={() => setState(s)}>
                  {t(`pages.distill.state.${s}`)} {count(s)}
                </button>
              ))}
            </div>
            <span className="fx-sp" />
            <label className="fx-field sm" style={{ minWidth: 240 }}>
              <input value={q} onChange={(e) => setQ(e.target.value)} placeholder={t("pages.documents.search")} aria-label={t("pages.documents.search")} />
            </label>
          </div>
          {failed && <ErrorState message={(failed.error as Error).message} onRetry={() => void failed.refetch()} />}
          <TableBox label={t("pages.documents.title")}>
          <Table<Row>
            rowKey={(r) => r.room + r.rel}
            dataSource={shown}
            loading={loading}
            size="small"
            pagination={{ pageSize: 50, hideOnSinglePage: true, showSizeChanger: false }}
            scroll={{ x: 720 }}
            locale={{ emptyText: t("pages.documents.nothingMatches") }}
            columns={[
              { title: t("pages.documents.colFile"), dataIndex: "rel", render: (v: string) => <span style={{ wordBreak: "break-all" }}>{v.replace(/^\//, "")}</span>, sorter: (a, b) => a.rel.localeCompare(b.rel) },
              { title: t("pages.distill.colRoom"), dataIndex: "roomName", sorter: (a, b) => a.roomName.localeCompare(b.roomName) },
              { title: t("pages.distill.colState"), dataIndex: "state", render: (_, r) => <StateTag state={r.state} /> },
              { title: t("pages.distill.colAccuracyShort"), dataIndex: "accuracy", align: "right", render: (v: number | null) => <span className="fx-num">{v == null ? "—" : `${v}%`}</span>,
                sorter: (a, b) => (a.accuracy ?? -1) - (b.accuracy ?? -1) },
              { title: t("pages.documents.pages"), dataIndex: "pages", align: "right", render: (v: number | null) => <span className="fx-num">{v ?? "—"}</span> },
              { title: <span className="sr-only">{t("pages.distill.colActions")}</span>, key: "open", render: (_, r) => (
                <Link className="fx-a" to={`/distill?room=${r.room}&file=${encodeURIComponent(r.rel)}`} aria-label={t("pages.documents.openFile", { name: r.name })}>
                  {r.state === "below" ? t("pages.distill.review") : t("pages.documents.open")}
                </Link>
              ) },
            ]}
          />
          </TableBox>
        </>
      )}
      <Earlier />
    </div>
  );
}
