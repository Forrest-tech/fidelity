import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { api } from "../net/client";
import { EmptyState, ErrorState, Loading, PageHeader, cx } from "../components/ui";

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

export function StatusBadge({ status }: { status: string }) {
  const { t } = useTranslation();
  const tone =
    status === "done" || status === "PASS"
      ? "text-ok border-ok"
      : status === "error" || status === "FAIL"
        ? "text-danger border-danger"
        : "text-fg-muted border-border";
  return (
    <span className={cx("inline-block rounded-full border px-2 py-0.5 text-xs font-medium", tone)}>
      {t(`status.${status}`, { defaultValue: status })}
    </span>
  );
}

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
        <div className="overflow-x-auto rounded-lg border border-border">
          <table className="w-full min-w-[32rem] text-left text-sm">
            <caption className="sr-only">{t("pages.jobs.title")}</caption>
            <thead className="bg-muted text-fg-muted">
              <tr>
                <th scope="col" className="px-3 py-2">{t("pages.jobs.file")}</th>
                <th scope="col" className="px-3 py-2">{t("pages.jobs.kind")}</th>
                <th scope="col" className="px-3 py-2">{t("pages.jobs.status")}</th>
                <th scope="col" className="px-3 py-2">{t("pages.jobs.message")}</th>
              </tr>
            </thead>
            <tbody>
              {q.data.map((j) => (
                <tr key={j.id} className="border-t border-border">
                  <td className="break-all px-3 py-2">{j.rel || "—"}</td>
                  <td className="px-3 py-2">{j.kind.split(":")[0]}</td>
                  <td className="px-3 py-2">
                    <StatusBadge status={j.status} />
                    {j.status === "running" && <span className="ml-2 text-fg-muted">{Math.round(j.progress)}%</span>}
                  </td>
                  <td className="px-3 py-2 text-fg-muted">{j.message}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
