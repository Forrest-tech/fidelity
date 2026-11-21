import { useEffect, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Button, Input, Space, Tag, Typography, theme } from "antd";
import { RobotOutlined } from "@ant-design/icons";
import { api, json } from "../net/client";

export interface FormulaItem {
  k: number;
  approved: string | null;
  suggestion?: {
    call: string;
    status: string;
    message: string | null;
    decision: string | null;
    result: { latex?: string; plain?: string; confidence?: number; unsure?: boolean; numbers_checked?: boolean | null } | null;
  } | null;
}

/** One formula the text layer cannot decode: the crop of the source page, and a transcription a person approves. */
export function FormulaPlace({
  roomId,
  rel,
  page,
  item,
  f,
  canEdit,
  canAsk,
  onChanged,
}: {
  roomId: string;
  rel: string;
  page: number;
  item: number;
  f: FormulaItem;
  canEdit: boolean;
  canAsk: boolean;
  onChanged: () => void;
}) {
  const { t } = useTranslation();
  const { token } = theme.useToken();
  const s = f.suggestion;
  const ok = s && (s.status === "ok" || s.status === "cached") && s.result?.latex;
  const [latex, setLatex] = useState(f.approved ?? (ok ? s!.result!.latex! : ""));
  useEffect(() => {
    if (!f.approved && ok) setLatex(s!.result!.latex!);
  }, [s?.call]); // eslint-disable-line react-hooks/exhaustive-deps
  const ask = useMutation({ mutationFn: () => api(`/rooms/${roomId}/ask`, json({ rel, item, k: f.k })), onSuccess: onChanged });
  const approve = useMutation({
    mutationFn: () => api(`/rooms/${roomId}/formula/approve`, json({ rel, page, k: f.k, latex, call: ok && !s!.decision ? s!.call : null })),
    onSuccess: onChanged,
  });
  const src = `/api/v1/rooms/${encodeURIComponent(roomId)}/formula.png?rel=${encodeURIComponent(rel)}&page=${page}&k=${f.k}`;
  const err = (ask.error || approve.error) as Error | null;
  return (
    <div style={{ display: "grid", gap: 6, padding: 8, border: `1px solid ${token.colorBorderSecondary}`, borderRadius: 6 }}>
      <Space size={6} wrap>
        <Typography.Text strong style={{ fontSize: 12 }}>{t("pages.distill.places.formulaN", { k: f.k })}</Typography.Text>
        {f.approved && <Tag color="success">{t("pages.distill.places.formulaApproved")}</Tag>}
      </Space>
      <img src={src} alt={t("pages.distill.places.formulaImage", { page, k: f.k })} style={{ maxWidth: "100%", background: "#fff", borderRadius: 4 }} />
      {ok && !f.approved && (
        <div style={{ fontSize: 12, display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center" }}>
          <RobotOutlined aria-hidden />
          <span>{t("pages.distill.places.aiTranscribed", { pct: Math.round((s!.result!.confidence ?? 0) * 100) })}</span>
          {s!.result!.numbers_checked ? (
            <Tag color="success">{t("pages.distill.places.numbersChecked")}</Tag>
          ) : (
            <Tag color="warning">{t("pages.distill.places.numbersUnchecked")}</Tag>
          )}
          {s!.result!.unsure && <Tag color="warning">{t("pages.distill.places.aiUnsureShort")}</Tag>}
        </div>
      )}
      {s && !ok && (
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          <RobotOutlined aria-hidden /> {s.message || t(`pages.distill.places.status.${s.status}`, { defaultValue: s.status })}
        </Typography.Text>
      )}
      {canEdit ? (
        <>
          <Input.TextArea
            value={latex}
            onChange={(e) => setLatex(e.target.value)}
            autoSize={{ minRows: 1, maxRows: 4 }}
            spellCheck={false}
            aria-label={t("pages.distill.places.latex", { k: f.k })}
            placeholder={t("pages.distill.places.latexPlaceholder")}
            style={{ fontFamily: "ui-monospace, SFMono-Regular, Consolas, monospace", fontSize: 12.5 }}
          />
          <Space wrap>
            {canAsk && !f.approved && (
              <Button size="small" icon={<RobotOutlined />} loading={ask.isPending} onClick={() => ask.mutate()}>
                {t("pages.distill.places.transcribe")}
              </Button>
            )}
            <Button size="small" type="primary" disabled={!latex.trim() || latex.trim() === f.approved} loading={approve.isPending} onClick={() => approve.mutate()}>
              {t("pages.distill.places.approveFormula")}
            </Button>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>{t("pages.distill.places.formulaNote")}</Typography.Text>
          </Space>
        </>
      ) : (
        f.approved && <code style={{ fontSize: 12.5 }}>{f.approved}</code>
      )}
      {err && <Typography.Text type="danger">{err.message}</Typography.Text>}
    </div>
  );
}
