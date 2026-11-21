import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Alert, Button, Card, Space, Tag, Typography } from "antd";
import { BulbOutlined } from "@ant-design/icons";
import { api } from "../net/client";

interface Sample {
  rel: string;
  room: string;
  before: string;
  old: string;
  new: string;
  after: string;
}
export interface Suggestion {
  id: string;
  kind: "widen" | "pattern";
  rule_ids: string[];
  data: {
    find: string;
    replace: string;
    scope: string;
    series: string | null;
    nums: number[];
    counterexamples?: string[];
    reason?: string;
    accuracy?: number;
    signature?: string;
  };
  preview: { documents: number; places: number; samples: Sample[] };
}
interface Found {
  widen: number;
  pattern: number;
  pattern_needs_ai: number;
  pattern_rejected: number;
  pattern_not_allowed?: number;
}
export interface Approved {
  rule: { id: string; num: number; enabled: boolean };
  affected: { room_id: string; room: string; rel: string; places: number }[];
}

/** Suggestions for the library, found from the fixes people confirmed. A person approves each one; documents change
 * only when the rule is applied. */
export function RuleSuggestions({ canEdit, onApproved }: { canEdit: boolean; onApproved: (a: Approved) => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [found, setFound] = useState<Found | null>(null);
  const list = useQuery({ queryKey: ["rule-suggestions"], queryFn: () => api<{ suggestions: Suggestion[] }>("/corrections/suggestions") });
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ["rule-suggestions"] });
    void qc.invalidateQueries({ queryKey: ["corrections"] });
  };
  const scan = useMutation({
    mutationFn: () => api<{ found: Found; suggestions: Suggestion[] }>("/corrections/suggestions/scan", { method: "POST" }),
    onSuccess: (r) => {
      setFound(r.found);
      qc.setQueryData(["rule-suggestions"], { suggestions: r.suggestions });
    },
  });
  const approve = useMutation({
    mutationFn: (id: string) => api<Approved>(`/corrections/suggestions/${id}/approve`, { method: "POST" }),
    onSuccess: (a) => {
      refresh();
      onApproved(a);
    },
  });
  const dismiss = useMutation({ mutationFn: (id: string) => api(`/corrections/suggestions/${id}/dismiss`, { method: "POST" }), onSuccess: refresh });
  const items = list.data?.suggestions ?? [];
  const err = (scan.error || approve.error || dismiss.error) as Error | null;
  const scopeText = (d: Suggestion["data"]) => (d.scope === "series" ? t("pages.corrections.scopeSeries", { series: d.series }) : t("pages.corrections.scopeAll"));
  return (
    <Card
      size="small"
      title={
        <Space>
          <BulbOutlined aria-hidden />
          {t("pages.corrections.sugTitle")}
          {items.length > 0 && <Tag>{items.length}</Tag>}
        </Space>
      }
      extra={
        canEdit && (
          <Button size="small" loading={scan.isPending} onClick={() => scan.mutate()}>
            {t("pages.corrections.sugScan")}
          </Button>
        )
      }
    >
      <Space orientation="vertical" size={10} style={{ width: "100%" }}>
        {found && (
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            {t("pages.corrections.sugFound", { count: found.widen + found.pattern })}
            {found.pattern_needs_ai ? ` ${t("pages.corrections.sugNeedsAi", { count: found.pattern_needs_ai })}` : ""}
            {found.pattern_not_allowed ? ` ${t("pages.corrections.sugNotAllowed", { count: found.pattern_not_allowed })}` : ""}
            {found.pattern_rejected ? ` ${t("pages.corrections.sugRejected", { count: found.pattern_rejected })}` : ""}
          </Typography.Text>
        )}
        {!items.length && !found && <Typography.Text type="secondary">{t("pages.corrections.sugNone")}</Typography.Text>}
        {items.map((s) => (
          <div key={s.id} style={{ display: "grid", gap: 6, paddingBottom: 10, borderBottom: "1px solid var(--ant-color-border-secondary)" }}>
            <div>
              {s.kind === "widen" ? (
                <span>
                  {t("pages.corrections.sugWiden", { rules: s.data.nums.map((n) => `#${n}`).join(", ") })} <code>{s.data.find}</code> → <code>{s.data.replace}</code>
                </span>
              ) : (
                <span>
                  {t("pages.corrections.sugPattern", { rules: s.data.nums.map((n) => `#${n}`).join(", "), kind: s.data.signature })}
                </span>
              )}
            </div>
            {s.kind === "pattern" && (
              <Space wrap size={6}>
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>{t("pages.corrections.sugProposed")}</Typography.Text>
                <code>{s.data.find}</code>→<code>{s.data.replace}</code>
                <Tag color="processing">AI</Tag>
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  {t("pages.corrections.sugAccuracy", { pct: s.data.accuracy })}
                  {s.data.counterexamples?.length ? ` · ${t("pages.corrections.sugKeeps", { words: s.data.counterexamples.join(", ") })}` : ""}
                </Typography.Text>
              </Space>
            )}
            <Typography.Text style={{ fontSize: 13 }}>
              {t("pages.corrections.sugScope", { scope: scopeText(s.data) })}{" "}
              <strong>{t("pages.corrections.sugPreview", { places: s.preview.places, count: s.preview.documents })}</strong>
            </Typography.Text>
            {s.preview.samples.length > 0 && (
              <div style={{ fontSize: 12, display: "grid", gap: 2 }}>
                {s.preview.samples.map((x, i) => (
                  <span key={i}>
                    <Typography.Text type="secondary">{x.rel.split("/").pop()}: …{x.before} </Typography.Text>
                    <del>{x.old}</del> <ins>{x.new}</ins>
                    <Typography.Text type="secondary"> {x.after}…</Typography.Text>
                  </span>
                ))}
              </div>
            )}
            {canEdit && (
              <Space>
                <Button size="small" type="primary" loading={approve.isPending && approve.variables === s.id} onClick={() => approve.mutate(s.id)}>
                  {t("pages.corrections.sugApprove")}
                </Button>
                <Button size="small" loading={dismiss.isPending && dismiss.variables === s.id} onClick={() => dismiss.mutate(s.id)}>
                  {t("pages.corrections.sugDismiss")}
                </Button>
              </Space>
            )}
          </div>
        ))}
        {err && <Alert type="error" showIcon title={err.message} />}
      </Space>
    </Card>
  );
}
