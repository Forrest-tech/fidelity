import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Segmented, Space, Table, Typography } from "antd";
import { api } from "../net/client";
import { EmptyState, ErrorState, Loading, PageHeader, StatusTag } from "../components/ui";

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

function notes(d: Doc, instruction: string) {
  const failed = d.checks ? Object.entries(d.checks).filter(([, ok]) => ok === false).map(([k]) => k) : [];
  return [d.triage ? `${d.triage.class}: ${d.triage.reason}` : "", d.instruction_like ? instruction : "", failed.join(", ")]
    .filter(Boolean)
    .join(" ");
}

export function DocumentsPage() {
  const { t } = useTranslation();
  const [verdict, setVerdict] = useState("");
  const q = useQuery({
    queryKey: ["documents", verdict],
    queryFn: () => api<Doc[]>("/documents" + (verdict ? `?verdict=${encodeURIComponent(verdict)}` : "")),
  });
  return (
    <>
      <PageHeader title={t("pages.documents.title")} />
      <Space style={{ marginBottom: 12 }} wrap>
        <Typography.Text type="secondary" id="doc-filter">
          {t("pages.documents.filter")}
        </Typography.Text>
        <Segmented
          aria-labelledby="doc-filter"
          value={verdict}
          onChange={(v) => setVerdict(String(v))}
          options={[
            { value: "", label: t("pages.documents.all") },
            { value: "PASS", label: t("status.PASS") },
            { value: "FAIL", label: t("status.FAIL") },
            { value: "SKIP", label: t("status.SKIP") },
          ]}
        />
      </Space>
      {q.isLoading && <Loading />}
      {q.isError && <ErrorState message={(q.error as Error).message} onRetry={() => void q.refetch()} />}
      {q.data && q.data.length === 0 && <EmptyState title={t("pages.documents.empty")} hint={t("pages.documents.emptyHint")} />}
      {q.data && q.data.length > 0 && (
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
      )}
    </>
  );
}
