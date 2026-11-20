import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Card, Col, Row, Statistic, Typography } from "antd";
import { api } from "../net/client";
import { EmptyState, ErrorState, Loading, PageHeader } from "../components/ui";

interface Overview {
  sources: number;
  jobs: Record<string, number>;
  documents: Record<string, number>;
  needs_attention: Array<{ rel: string; sid: string; verdict: string; instruction_like: number }>;
}

function Stat({ label, value }: { label: string; value: number | string }) {
  return (
    <Card>
      <Statistic title={label} value={value} formatter={(v) => <span data-testid={`stat-${label}`}>{v}</span>} />
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
      {d && docTotal === 0 && d.sources === 0 && <EmptyState title={t("pages.overview.empty")} hint={t("pages.overview.emptyHint")} />}
      {d && (docTotal > 0 || d.sources > 0) && (
        <div className="flex flex-col gap-6">
          <Row gutter={[16, 16]}>
            <Col xs={12} md={6}>
              <Stat label={t("pages.overview.sources")} value={d.sources} />
            </Col>
            <Col xs={12} md={6}>
              <Stat label={t("pages.overview.documents")} value={docTotal} />
            </Col>
            <Col xs={12} md={6}>
              <Stat label={t("pages.overview.verified")} value={d.documents.PASS ?? 0} />
            </Col>
            <Col xs={12} md={6}>
              <Stat label={t("pages.overview.running")} value={(d.jobs.running ?? 0) + (d.jobs.queued ?? 0)} />
            </Col>
          </Row>
          <section aria-labelledby="attn">
            <Typography.Title level={4} id="attn">
              {t("pages.overview.attention")}
            </Typography.Title>
            {d.needs_attention.length === 0 ? (
              <Typography.Text type="secondary">{t("pages.overview.attentionNone")}</Typography.Text>
            ) : (
              <Card size="small">
                <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
                  {d.needs_attention.map((a) => (
                    <li key={a.sid + a.rel} style={{ padding: "8px 4px", borderBottom: "1px solid var(--ant-color-split)" }}>
                      <strong>{a.rel}</strong> · {t(`verdict.${a.verdict}`, { defaultValue: a.verdict })}
                      {a.instruction_like > 0 && <Typography.Text type="warning"> · {t("pages.documents.instruction")}</Typography.Text>}
                    </li>
                  ))}
                </ul>
              </Card>
            )}
          </section>
        </div>
      )}
    </>
  );
}
