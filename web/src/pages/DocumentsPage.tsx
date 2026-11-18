import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../net/client";
import { EmptyState, ErrorState, Loading, PageHeader } from "../components/ui";
import { StatusBadge } from "./JobsPage";

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
      <label className="mb-3 flex items-center gap-2 text-sm text-fg-muted">
        {t("pages.documents.filter")}
        <select
          className="rounded-md border border-border bg-surface px-2 py-1 text-fg"
          value={verdict}
          onChange={(e) => setVerdict(e.target.value)}
        >
          <option value="">{t("pages.documents.all")}</option>
          <option value="PASS">{t("status.PASS")}</option>
          <option value="FAIL">{t("status.FAIL")}</option>
          <option value="SKIP">{t("status.SKIP")}</option>
        </select>
      </label>
      {q.isLoading && <Loading />}
      {q.isError && <ErrorState message={(q.error as Error).message} onRetry={() => void q.refetch()} />}
      {q.data && q.data.length === 0 && <EmptyState title={t("pages.documents.empty")} hint={t("pages.documents.emptyHint")} />}
      {q.data && q.data.length > 0 && (
        <div className="overflow-x-auto rounded-lg border border-border">
          <table className="w-full min-w-[36rem] text-left text-sm">
            <caption className="sr-only">{t("pages.documents.title")}</caption>
            <thead className="bg-muted text-fg-muted">
              <tr>
                <th scope="col" className="px-3 py-2">{t("pages.jobs.file")}</th>
                <th scope="col" className="px-3 py-2">{t("pages.documents.result")}</th>
                <th scope="col" className="px-3 py-2">{t("pages.documents.pages")}</th>
                <th scope="col" className="px-3 py-2">{t("pages.documents.files")}</th>
                <th scope="col" className="px-3 py-2">{t("pages.documents.notes")}</th>
              </tr>
            </thead>
            <tbody>
              {q.data.map((d) => (
                <tr key={d.sid + d.rel} className="border-t border-border">
                  <td className="break-all px-3 py-2">{d.rel}</td>
                  <td className="px-3 py-2">
                    <StatusBadge status={d.verdict} />
                  </td>
                  <td className="px-3 py-2">{d.pages}</td>
                  <td className="px-3 py-2">{d.single_file ? t("pages.documents.single") : d.files}</td>
                  <td className="px-3 py-2 text-fg-muted">
                    {d.triage ? `${d.triage.class}: ${d.triage.reason}` : ""}
                    {d.instruction_like ? ` ${t("pages.documents.instruction")}` : ""}
                    {d.checks && Object.entries(d.checks).some(([, ok]) => ok === false)
                      ? " " + Object.entries(d.checks).filter(([, ok]) => ok === false).map(([k]) => k).join(", ")
                      : ""}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
