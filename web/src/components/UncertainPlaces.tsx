import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Button, Space, Tag, Typography } from "antd";
import { RobotOutlined } from "@ant-design/icons";
import { api, json } from "../net/client";

interface Suggestion {
  call: string;
  skill: "arbitrate" | "explain";
  status: "ok" | "cached" | "invalid" | "error" | "blocked";
  message: string | null;
  decision: string | null;
  result: { text?: string | null; choice?: number | null; confidence?: number; reason?: string; needs_human?: boolean; action?: string } | null;
}
interface Place {
  i: number;
  kind: string;
  page: number | null;
  detail: string;
  candidates?: string[];
  in_text?: string | null;
  before?: string;
  after?: string;
  suggestion?: Suggestion | null;
}
interface Review {
  items: Place[];
  ai: { enabled: boolean; skills: { arbitrate: { level: number }; explain: { level: number } } };
}
const SHOW = 30;

/** The places of one file that were uncertain when it was distilled. A reading can be taken over into the fix form;
 * the AI can be asked for a suggestion, which is only ever a suggestion. */
export function UncertainPlaces({
  roomId,
  rel,
  canEdit,
  onUse,
}: {
  roomId: string;
  rel: string;
  canEdit: boolean;
  onUse: (find: string, replace: string, call: string | null) => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [all, setAll] = useState(false);
  const q = useQuery({ queryKey: ["review", roomId, rel], queryFn: () => api<Review>(`/rooms/${roomId}/review?rel=${encodeURIComponent(rel)}`), retry: false });
  const refetch = () => void qc.invalidateQueries({ queryKey: ["review", roomId, rel] });
  const ask = useMutation({ mutationFn: (i: number) => api(`/rooms/${roomId}/ask`, json({ rel, item: i })), onSuccess: refetch });
  const reject = useMutation({ mutationFn: (call: string) => api(`/ai/calls/${call}/decision`, json({ decision: "rejected" })), onSuccess: refetch });
  // level 2: the AI is asked about new places by default when the file is opened (once)
  const asked = useRef(false);
  const level2 = !!q.data?.ai?.enabled && (q.data.ai.skills?.arbitrate?.level ?? 0) >= 2;
  useEffect(() => {
    if (!canEdit || !level2 || asked.current) return;
    asked.current = true;
    void api(`/rooms/${roomId}/ask-default`, json({ rel })).then(refetch, () => undefined);
  }, [level2, canEdit]); // eslint-disable-line react-hooks/exhaustive-deps

  const items = q.data?.items ?? [];
  if (!items.length) return null;
  const shown = all ? items : items.slice(0, SHOW);
  const level = (k: string) => (q.data?.ai?.enabled ? (k === "reading" ? q.data.ai.skills?.arbitrate?.level : q.data.ai.skills?.explain?.level) ?? 0 : 0);
  return (
    <section aria-label={t("pages.distill.places.title")}>
      <Typography.Title level={5} style={{ marginTop: 0 }}>
        {t("pages.distill.places.title")} <Typography.Text type="secondary" style={{ fontSize: 13, fontWeight: 400 }}>{items.length}</Typography.Text>
      </Typography.Title>
      <Space orientation="vertical" size={8} style={{ width: "100%" }}>
        {shown.map((p) => {
          const s = p.suggestion;
          const okS = s && (s.status === "ok" || s.status === "cached") && s.result;
          return (
            <div key={p.i} style={{ padding: "6px 0", borderBottom: "1px solid var(--ant-color-border-secondary)", display: "grid", gap: 4 }}>
              <Space wrap size={6}>
                <Tag style={{ marginInlineEnd: 0 }}>{t(`pages.distill.places.kind.${p.kind}`, { defaultValue: p.kind })}</Tag>
                {p.page != null && <Typography.Text type="secondary" style={{ fontSize: 12 }}>{t("pages.distill.places.page", { n: p.page })}</Typography.Text>}
                {p.kind !== "reading" && <span style={{ fontSize: 13 }}>{p.detail}</span>}
              </Space>
              {p.kind === "reading" && (
                <div style={{ fontSize: 13 }}>
                  {p.in_text ? (
                    <span>
                      <Typography.Text type="secondary">…{p.before} </Typography.Text>
                      <mark>{p.in_text}</mark>
                      <Typography.Text type="secondary"> {p.after}…</Typography.Text>
                    </span>
                  ) : (
                    <Typography.Text type="secondary">{t("pages.distill.places.notInText")}</Typography.Text>
                  )}
                  <div style={{ marginTop: 4, display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center" }}>
                    <Typography.Text type="secondary" style={{ fontSize: 12 }}>{t("pages.distill.places.readings")}</Typography.Text>
                    {(p.candidates ?? []).map((c, k) =>
                      canEdit && p.in_text && c !== p.in_text ? (
                        <Button key={k} size="small" onClick={() => onUse(p.in_text!, c, null)}>
                          {t("pages.distill.places.use", { text: c })}
                        </Button>
                      ) : (
                        <Tag key={k} style={{ marginInlineEnd: 0 }}><code>{c}</code></Tag>
                      ),
                    )}
                  </div>
                </div>
              )}
              {okS && s!.skill === "arbitrate" && (
                <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap", fontSize: 13 }}>
                  <RobotOutlined aria-hidden />
                  {s!.result!.text == null ? (
                    <span>{t("pages.distill.places.aiUnsure")}</span>
                  ) : (
                    <span>
                      {t("pages.distill.places.aiSays")} <code>{s!.result!.text}</code>{" "}
                      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                        {Math.round((s!.result!.confidence ?? 0) * 100)}% · {s!.result!.reason}
                      </Typography.Text>
                    </span>
                  )}
                  {s!.result!.needs_human && <Tag color="warning">{t("pages.distill.places.checkYourself")}</Tag>}
                  {s!.decision && <Tag>{t(`pages.distill.places.decision.${s!.decision}`)}</Tag>}
                  {canEdit && !s!.decision && s!.result!.text != null && p.in_text && s!.result!.text !== p.in_text && (
                    <Button size="small" type="primary" onClick={() => onUse(p.in_text!, s!.result!.text!, s!.call)}>
                      {t("pages.distill.places.useAi")}
                    </Button>
                  )}
                  {canEdit && !s!.decision && (
                    <Button size="small" type="link" onClick={() => reject.mutate(s!.call)}>
                      {t("pages.distill.places.notRight")}
                    </Button>
                  )}
                </div>
              )}
              {okS && s!.skill === "explain" && (
                <div style={{ fontSize: 13, display: "flex", gap: 8 }}>
                  <RobotOutlined aria-hidden style={{ marginTop: 3 }} />
                  <span>
                    {s!.result!.reason} <Typography.Text type="secondary">{s!.result!.action}</Typography.Text>
                  </span>
                </div>
              )}
              {s && !okS && (
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  <RobotOutlined aria-hidden /> {s.message || t(`pages.distill.places.status.${s.status}`)}
                </Typography.Text>
              )}
              {canEdit && level(p.kind) >= 1 && !okS && (
                <div>
                  <Button
                    size="small"
                    icon={<RobotOutlined />}
                    loading={ask.isPending && ask.variables === p.i}
                    onClick={() => ask.mutate(p.i)}
                  >
                    {p.kind === "reading" ? t("pages.distill.places.askAi") : t("pages.distill.places.explain")}
                  </Button>
                </div>
              )}
            </div>
          );
        })}
        {!all && items.length > SHOW && (
          <Button size="small" type="link" onClick={() => setAll(true)}>{t("pages.distill.places.showAll", { count: items.length })}</Button>
        )}
        {(ask.error || reject.error) && <Typography.Text type="danger">{((ask.error || reject.error) as Error).message}</Typography.Text>}
      </Space>
    </section>
  );
}
