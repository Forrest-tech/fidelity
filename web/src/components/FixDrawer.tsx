import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { Alert, Button, Drawer, Input, Segmented, Space, Spin, Tag, Typography, theme } from "antd";
import { api, json } from "../net/client";

interface Applied {
  rule: string;
  num: number;
  find: string;
  replace: string;
  kind: "text" | "number";
  count: number;
  check: boolean;
}
interface ResultView {
  rel: string;
  series: string | null;
  files: { path: string; text: string; cut: boolean }[];
  corrections: Applied[];
}
interface Match {
  room_id: string;
  room: string;
  rel: string;
  places: number;
}
interface Preview {
  kind: "text" | "number";
  before: string;
  after: string;
  series: string | null;
  here: number;
  others: Match[];
  other_places: number;
}
interface Saved {
  rule: { id: string; num: number };
  others: Match[];
}
type Scope = "document" | "series" | "all";

/** Look at one file's result, fix a misread once, and keep the fix as a rule for the documents that belong with it. */
export function FixDrawer({ roomId, rel, canEdit, onClose }: { roomId: string; rel: string | null; canEdit: boolean; onClose: () => void }) {
  const { t } = useTranslation();
  const { token } = theme.useToken();
  const qc = useQueryClient();
  const view = useQuery({
    queryKey: ["result", roomId, rel],
    queryFn: () => api<ResultView>(`/rooms/${roomId}/result?rel=${encodeURIComponent(rel!)}`),
    enabled: !!rel,
    retry: false,
  });
  const [find, setFind] = useState("");
  const [replace, setReplace] = useState("");
  const [scope, setScope] = useState<Scope>("series");
  const [preview, setPreview] = useState<Preview | null>(null);
  const [saved, setSaved] = useState<Saved | null>(null);
  const [applied, setApplied] = useState<number | null>(null);
  useEffect(() => {
    setFind("");
    setReplace("");
    setPreview(null);
    setSaved(null);
    setApplied(null);
  }, [rel]);
  useEffect(() => setScope(view.data?.series ? "series" : "document"), [view.data?.series]);
  useEffect(() => setPreview(null), [find, replace, scope]);

  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ["result", roomId, rel] });
    void qc.invalidateQueries({ queryKey: ["room-files"] });
    void qc.invalidateQueries({ queryKey: ["rooms"] });
    void qc.invalidateQueries({ queryKey: ["accept-preview"] });
    void qc.invalidateQueries({ queryKey: ["corrections"] });
  };
  const draft = () => ({ room_id: roomId, rel, find, replace, scope });
  const check = useMutation({ mutationFn: () => api<Preview>("/corrections/preview", json(draft())), onSuccess: setPreview });
  const save = useMutation({
    mutationFn: () => api<Saved>("/corrections", json(draft())),
    onSuccess: (s) => {
      setSaved(s);
      setApplied(null);
      setFind("");
      setReplace("");
      refresh();
    },
  });
  const applyAll = useMutation({
    mutationFn: (id: string) => api<{ documents: number; changed: number }>(`/corrections/${id}/apply`, { method: "POST" }),
    onSuccess: (r) => {
      setApplied(r.changed);
      refresh();
    },
  });
  const place = useMutation({
    mutationFn: (p: { what: "undo" | "confirm"; rule: string }) =>
      api(`/rooms/${roomId}/corrections/${p.what}`, json({ rel, rule_id: p.rule })),
    onSuccess: refresh,
  });
  const err = (check.error || save.error || applyAll.error || place.error) as Error | null;
  const v = view.data;
  const name = rel?.split("/").pop() ?? "";

  // selecting text in the result fills in the wrong text
  const takeSelection = () => {
    const s = window.getSelection()?.toString() ?? "";
    if (canEdit && s && !s.includes("\n") && s.length <= 200) {
      setFind(s);
      if (!replace) setReplace(s);
    }
  };

  return (
    <Drawer open={!!rel} onClose={onClose} size="large" title={t("pages.distill.fix.title", { name })} destroyOnHidden>
      {view.isLoading && <Spin />}
      {view.isError && <Alert type="error" showIcon title={(view.error as Error).message} />}
      {v && (
        <Space orientation="vertical" size={14} style={{ width: "100%" }}>
          {v.corrections.length > 0 && (
            <section aria-label={t("pages.distill.fix.applied")}>
              <Typography.Title level={5} style={{ marginTop: 0 }}>{t("pages.distill.fix.applied")}</Typography.Title>
              <Space orientation="vertical" size={6} style={{ width: "100%" }}>
                {v.corrections.map((c) => (
                  <div key={c.rule} style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                    <Tag>#{c.num}</Tag>
                    <code>{c.find}</code>→<code>{c.replace}</code>
                    <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                      {t("pages.distill.fix.places", { count: c.count })}
                    </Typography.Text>
                    {c.check && <Tag color="warning">{t("pages.distill.fix.needsCheck")}</Tag>}
                    <span style={{ flex: 1 }} />
                    {canEdit && c.check && (
                      <Button size="small" onClick={() => place.mutate({ what: "confirm", rule: c.rule })}>
                        {t("pages.distill.fix.confirm")}
                      </Button>
                    )}
                    {canEdit && (
                      <Button size="small" type="link" danger onClick={() => place.mutate({ what: "undo", rule: c.rule })}>
                        {t("pages.distill.fix.undo")}
                      </Button>
                    )}
                  </div>
                ))}
              </Space>
            </section>
          )}

          {canEdit && (
            <section aria-label={t("pages.distill.fix.remember")}>
              <Typography.Title level={5} style={{ marginTop: 0 }}>{t("pages.distill.fix.remember")}</Typography.Title>
              <Space orientation="vertical" size={10} style={{ width: "100%" }}>
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>{t("pages.distill.fix.hint")}</Typography.Text>
                <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: 10 }}>
                  <label style={{ display: "grid", gap: 4 }}>
                    <span>{t("pages.distill.fix.wrong")}</span>
                    <Input value={find} onChange={(e) => setFind(e.target.value)} maxLength={200} spellCheck={false} />
                  </label>
                  <label style={{ display: "grid", gap: 4 }}>
                    <span>{t("pages.distill.fix.right")}</span>
                    <Input value={replace} onChange={(e) => setReplace(e.target.value)} maxLength={200} spellCheck={false} />
                  </label>
                </div>
                <div style={{ display: "grid", gap: 4 }}>
                  <span>{t("pages.distill.fix.scope")}</span>
                  <Segmented
                    value={scope}
                    onChange={(x) => setScope(x as Scope)}
                    options={[
                      { value: "document", label: t("pages.distill.fix.scopeDocument") },
                      { value: "series", label: v.series ? t("pages.distill.fix.scopeSeries", { series: v.series }) : t("pages.distill.fix.scopeNoSeries"), disabled: !v.series },
                      { value: "all", label: t("pages.distill.fix.scopeAll") },
                    ]}
                  />
                </div>
                <Space wrap>
                  <Button disabled={!find || find === replace} loading={check.isPending} onClick={() => check.mutate()}>
                    {t("pages.distill.fix.preview")}
                  </Button>
                  <Button type="primary" disabled={!preview} loading={save.isPending} onClick={() => save.mutate()}>
                    {t("pages.distill.fix.save")}
                  </Button>
                </Space>
                {preview && (
                  <Alert
                    type="info"
                    showIcon
                    title={t("pages.distill.fix.previewHere", { count: preview.here })}
                    description={
                      <Space orientation="vertical" size={4}>
                        <span>
                          {preview.others.length
                            ? t("pages.distill.fix.previewOthers", { places: preview.other_places, count: preview.others.length })
                            : t("pages.distill.fix.previewNoOthers")}
                        </span>
                        {preview.others.slice(0, 8).map((m) => (
                          <Typography.Text key={m.room_id + m.rel} type="secondary" style={{ fontSize: 12 }}>
                            {m.room} · {m.rel.split("/").pop()} · {t("pages.distill.fix.places", { count: m.places })}
                          </Typography.Text>
                        ))}
                        {preview.kind === "number" && (
                          <span>
                            {t("pages.distill.fix.numberNote")}{" "}
                            <code>
                              {preview.before}
                              <mark>{find}</mark>
                              {preview.after}
                            </code>
                          </span>
                        )}
                      </Space>
                    }
                  />
                )}
                {saved && (
                  <Alert
                    type="success"
                    showIcon
                    title={t("pages.distill.fix.saved", { num: saved.rule.num })}
                    description={
                      applied !== null ? (
                        t("pages.distill.fix.appliedOthers", { count: applied })
                      ) : saved.others.length ? (
                        <Space wrap>
                          <span>{t("pages.distill.fix.othersWaiting", { count: saved.others.length })}</span>
                          <Button size="small" type="primary" loading={applyAll.isPending} onClick={() => applyAll.mutate(saved.rule.id)}>
                            {t("pages.distill.fix.applyOthers", { count: saved.others.length })}
                          </Button>
                        </Space>
                      ) : undefined
                    }
                  />
                )}
              </Space>
            </section>
          )}
          {err && <Alert type="error" showIcon title={err.message} />}

          <section aria-label={t("pages.distill.fix.result")}>
            <Space style={{ width: "100%", justifyContent: "space-between" }}>
              <Typography.Title level={5} style={{ margin: 0 }}>{t("pages.distill.fix.result")}</Typography.Title>
              <Link to="/corrections">{t("pages.distill.fix.library")}</Link>
            </Space>
            {v.files.map((f) => (
              <div key={f.path} style={{ marginTop: 8 }}>
                {v.files.length > 1 && <Typography.Text type="secondary" style={{ fontSize: 12 }}>{f.path}</Typography.Text>}
                <pre
                  tabIndex={0}
                  onMouseUp={takeSelection}
                  style={{
                    whiteSpace: "pre-wrap",
                    wordBreak: "break-word",
                    maxHeight: "45vh",
                    overflow: "auto",
                    margin: 0,
                    padding: 10,
                    fontSize: 12.5,
                    border: `1px solid ${token.colorBorderSecondary}`,
                    borderRadius: 6,
                    background: token.colorFillQuaternary,
                  }}
                >
                  {f.text}
                </pre>
                {f.cut && <Typography.Text type="secondary" style={{ fontSize: 12 }}>{t("pages.distill.fix.cut")}</Typography.Text>}
              </div>
            ))}
          </section>
        </Space>
      )}
    </Drawer>
  );
}
