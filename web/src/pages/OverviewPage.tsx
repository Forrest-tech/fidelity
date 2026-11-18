import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { api } from "../net/client";
import { Card, EmptyState, ErrorState, Loading, PageHeader } from "../components/ui";

interface Overview {
  sources: number;
  jobs: Record<string, number>;
  documents: Record<string, number>;
  needs_attention: Array<{ rel: string; sid: string; verdict: string; instruction_like: number }>;
}

function Stat({ label, value }: { label: string; value: number | string }) {
  return (
    <Card>
      <p className="text-sm text-fg-muted">{label}</p>
      <p className="text-3xl font-semibold" data-testid={`stat-${label}`}>
        {value}
      </p>
    </Card>
  );
}

export function OverviewPage() {
  const { t } = useTranslation();
  const q = useQuery({ queryKey: ["overview"], queryFn: () => api<Overview>("/overview"), refetchInterval: 10_000 });
  const d = q.data && { ...q.data, documents: q.data.documents ?? {}, jobs: q.data.jobs ?? {}, needs_attention: q.data.needs_attention ?? [], sources: q.data.sources ?? 0 };
  const docTotal = d ? Object.values(d.documents).reduce((a, b) => a + b, 0) : 0;
  return (
    <>
      <PageHeader title={t("pages.overview.title")} />
      {q.isLoading && <Loading />}
      {q.isError && <ErrorState message={(q.error as Error).message} onRetry={() => void q.refetch()} />}
      {d && docTotal === 0 && d.sources === 0 && (
        <EmptyState title={t("pages.overview.empty")} hint={t("pages.overview.emptyHint")} />
      )}
      {d && (docTotal > 0 || d.sources > 0) && (
        <div className="flex flex-col gap-6">
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <Stat label={t("pages.overview.sources")} value={d.sources} />
            <Stat label={t("pages.overview.documents")} value={docTotal} />
            <Stat label={t("pages.overview.verified")} value={d.documents.PASS ?? 0} />
            <Stat label={t("pages.overview.running")} value={(d.jobs.running ?? 0) + (d.jobs.queued ?? 0)} />
          </div>
          <section aria-labelledby="attn">
            <h2 id="attn" className="mb-2 text-lg font-medium">
              {t("pages.overview.attention")}
            </h2>
            {d.needs_attention.length === 0 ? (
              <p className="text-sm text-fg-muted">{t("pages.overview.attentionNone")}</p>
            ) : (
              <ul className="flex flex-col gap-2">
                {d.needs_attention.map((a) => (
                  <li key={a.sid + a.rel} className="rounded-md border border-border bg-surface px-3 py-2 text-sm">
                    <span className="font-medium">{a.rel}</span> · {t(`verdict.${a.verdict}`, { defaultValue: a.verdict })}
                    {a.instruction_like > 0 && <span className="text-warn"> · {t("pages.documents.instruction")}</span>}
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>
      )}
    </>
  );
}
