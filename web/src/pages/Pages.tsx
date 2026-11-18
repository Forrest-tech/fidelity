import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { api } from "../net/client";
import { EmptyState, ErrorState, Loading, PageHeader } from "../components/ui";

interface SourceRow {
  id: string;
  name: string;
  src_root: string;
  md_root: string;
  enabled?: boolean;
}

/** Page with no data yet (filled by later work): honest empty state, never a blank screen. */
function Stub({ k }: { k: "overview" | "jobs" | "documents" | "settings" | "users" }) {
  const { t } = useTranslation();
  return (
    <>
      <PageHeader title={t(`pages.${k}.title`)} />
      <EmptyState title={t(`pages.${k}.empty`)} hint={t(`pages.${k}.emptyHint`, { defaultValue: "" }) || undefined} />
    </>
  );
}

export const OverviewPage = () => <Stub k="overview" />;
export const JobsPage = () => <Stub k="jobs" />;
export const DocumentsPage = () => <Stub k="documents" />;
export const SettingsPage = () => <Stub k="settings" />;
export const UsersPage = () => <Stub k="users" />;

export function SourcesPage() {
  const { t } = useTranslation();
  const q = useQuery({ queryKey: ["sources"], queryFn: () => api<SourceRow[]>("/sources") });
  return (
    <>
      <PageHeader title={t("pages.sources.title")} />
      {q.isLoading && <Loading />}
      {q.isError && <ErrorState message={(q.error as Error).message} onRetry={() => void q.refetch()} />}
      {q.data && q.data.length === 0 && <EmptyState title={t("pages.sources.empty")} hint={t("pages.sources.emptyHint")} />}
      {q.data && q.data.length > 0 && (
        <ul className="grid gap-3 md:grid-cols-2">
          {q.data.map((s) => (
            <li key={s.id} className="rounded-lg border border-border bg-surface p-4">
              <p className="font-medium">{s.name}</p>
              <p className="break-all text-sm text-fg-muted">{s.src_root}</p>
            </li>
          ))}
        </ul>
      )}
    </>
  );
}
