import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Table, Typography } from "antd";
import { api } from "../net/client";
import { EmptyState, ErrorState, Loading, PageHeader, StatusTag, TableBox } from "../components/ui";

export interface Job {
  id: string;
  kind: string;
  rel: string;
  status: "queued" | "running" | "done" | "error" | string;
  progress: number;
  message: string;
  created_at: number;
  updated_at: number;
}

export const StatusBadge = StatusTag;

export function JobsPage() {
  const { t } = useTranslation();
  const q = useQuery({ queryKey: ["jobs"], queryFn: () => api<Job[]>("/jobs?limit=100"), refetchInterval: 3000 });
  return (
    <>
      <PageHeader title={t("pages.jobs.title")} />
      {q.isLoading && <Loading />}
      {q.isError && <ErrorState message={(q.error as Error).message} onRetry={() => void q.refetch()} />}
      {q.data && q.data.length === 0 && <EmptyState title={t("pages.jobs.empty")} hint={t("pages.jobs.emptyHint")} />}
      {q.data && q.data.length > 0 && (
        <TableBox label={t("pages.jobs.title")}>
        <Table<Job>
          rowKey="id"
          dataSource={q.data}
          pagination={{ pageSize: 25, hideOnSinglePage: true, showSizeChanger: false }}
          scroll={{ x: 600 }}
          columns={[
            { title: t("pages.jobs.file"), dataIndex: "rel", render: (v: string) => <span style={{ wordBreak: "break-all" }}>{v || "—"}</span> },
            { title: t("pages.jobs.kind"), dataIndex: "kind", render: (v: string) => v.split(":")[0] },
            {
              title: t("pages.jobs.status"),
              dataIndex: "status",
              render: (s: string, j) => (
                <>
                  <StatusTag status={s} />
                  {s === "running" && <Typography.Text type="secondary">{Math.round(j.progress)}%</Typography.Text>}
                </>
              ),
            },
            { title: t("pages.jobs.message"), dataIndex: "message", render: (v: string) => <Typography.Text type="secondary">{v}</Typography.Text> },
          ]}
        />
        </TableBox>
      )}
    </>
  );
}
