import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Alert, Button, Card, Modal, Segmented, Space, Switch, Table, Tag, Typography } from "antd";
import { DownloadOutlined } from "@ant-design/icons";
import { api, json } from "../net/client";
import { useAuth } from "../auth/AuthProvider";
import { EmptyState, ErrorState, Loading, PageHeader } from "../components/ui";
import { RuleSuggestions } from "../components/RuleSuggestions";

interface Rule {
  id: string;
  num: number;
  find: string;
  replace: string;
  before: string;
  after: string;
  kind: "text" | "number" | "pattern";
  scope: "document" | "series" | "all";
  series: string | null;
  doc: string | null;
  enabled: boolean;
  reverts: number;
  hits: number;
  documents: number;
  often_undone: boolean;
  source_name: string;
  created_by: string;
  created_at: number;
}
interface Library {
  rules: Rule[];
  total: number;
  enabled: number;
  disabled: number;
  often_undone: number;
}
interface Doc {
  room_id: string;
  room: string;
  rel: string;
  places: number;
}
type Filter = "all" | "on" | "off" | "undone";

export function CorrectionsPage() {
  const { t } = useTranslation();
  const { me } = useAuth();
  const qc = useQueryClient();
  const canEdit = me?.role === "reviewer" || me?.role === "admin";
  const [filter, setFilter] = useState<Filter>("all");
  const [changed, setChanged] = useState<{ rule: Rule; docs: Doc[] } | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const lib = useQuery({ queryKey: ["corrections"], queryFn: () => api<Library>("/corrections") });
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ["corrections"] });
    void qc.invalidateQueries({ queryKey: ["room-files"] });
    void qc.invalidateQueries({ queryKey: ["rooms"] });
  };
  const toggle = useMutation({
    mutationFn: (p: { id: string; enabled: boolean }) =>
      api<{ rule: Rule; affected: Doc[] }>(`/corrections/${p.id}`, { ...json({ enabled: p.enabled }), method: "PATCH" }),
    onSuccess: (r) => {
      refresh();
      if (r.affected.length) setChanged({ rule: r.rule, docs: r.affected });
    },
  });
  const apply = useMutation({
    mutationFn: (id: string) => api<{ documents: number; changed: number }>(`/corrections/${id}/apply`, { method: "POST" }),
    onSuccess: (r) => {
      setChanged(null);
      setDone(t("pages.corrections.appliedDone", { count: r.changed }));
      refresh();
    },
  });
  const err = (toggle.error || apply.error) as Error | null;
  const d = lib.data;
  const rows = (d?.rules ?? []).filter((r) =>
    filter === "on" ? r.enabled : filter === "off" ? !r.enabled : filter === "undone" ? r.often_undone : true,
  );

  const exportRules = () => {
    const blob = new Blob([JSON.stringify(d?.rules ?? [], null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "correction-rules.json";
    a.click();
    URL.revokeObjectURL(a.href);
  };

  const scopeText = (r: Rule) =>
    r.scope === "all" ? t("pages.corrections.scopeAll") : r.scope === "series" ? t("pages.corrections.scopeSeries", { series: r.series }) : r.doc ?? "";

  return (
    <Space orientation="vertical" size={16} style={{ width: "100%" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 12, flexWrap: "wrap" }}>
        <PageHeader title={t("pages.corrections.title")} />
        <Button icon={<DownloadOutlined />} disabled={!d?.total} onClick={exportRules}>
          {t("pages.corrections.export")}
        </Button>
      </div>
      <Typography.Text type="secondary">{t("pages.corrections.intro")}</Typography.Text>
      <RuleSuggestions
        canEdit={canEdit}
        onApproved={(a) => {
          refresh();
          if (a.affected.length) setChanged({ rule: a.rule as unknown as Rule, docs: a.affected });
        }}
      />
      {err && <Alert type="error" showIcon title={err.message} />}
      {done && <Alert type="success" showIcon closable onClose={() => setDone(null)} title={done} />}
      {lib.isLoading && <Loading />}
      {lib.isError && <ErrorState message={(lib.error as Error).message} onRetry={() => void lib.refetch()} />}
      {d && d.total === 0 && <EmptyState title={t("pages.corrections.empty")} hint={t("pages.corrections.emptyHint")} />}
      {d && d.total > 0 && (
        <Card size="small">
          <Space orientation="vertical" size={12} style={{ width: "100%" }}>
            <Segmented
              aria-label={t("pages.corrections.filter")}
              value={filter}
              onChange={(v) => setFilter(v as Filter)}
              options={[
                { value: "all", label: `${t("pages.corrections.all")} ${d.total}` },
                { value: "on", label: `${t("pages.corrections.on")} ${d.enabled}` },
                { value: "off", label: `${t("pages.corrections.off")} ${d.disabled}` },
                { value: "undone", label: `${t("pages.corrections.undone")} ${d.often_undone}` },
              ]}
            />
            <Table<Rule>
              size="small"
              rowKey="id"
              dataSource={rows}
              pagination={rows.length > 50 ? { pageSize: 50 } : false}
              scroll={{ x: 900 }}
              columns={[
                {
                  title: t("pages.corrections.colFix"),
                  render: (_: unknown, r) => (
                    <Space orientation="vertical" size={2}>
                      <span>
                        <Tag>#{r.num}</Tag>
                        <code>{r.find}</code> → <code>{r.replace}</code>
                        {r.kind === "pattern" && <Tag color="processing" style={{ marginInlineStart: 6 }}>{t("pages.corrections.pattern")}</Tag>}
                      </span>
                      {r.kind === "number" && (
                        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                          {t("pages.corrections.onlyIn")} <code>{r.before}<mark>{r.find}</mark>{r.after}</code>
                        </Typography.Text>
                      )}
                    </Space>
                  ),
                },
                { title: t("pages.corrections.colScope"), width: 170, render: (_: unknown, r) => scopeText(r) },
                {
                  title: t("pages.corrections.colSource"),
                  width: 220,
                  render: (_: unknown, r) => (
                    <Typography.Text style={{ fontSize: 12 }}>
                      {r.source_name}
                      <br />
                      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                        {r.created_by} · {new Date(r.created_at * 1000).toLocaleDateString()}
                      </Typography.Text>
                    </Typography.Text>
                  ),
                },
                {
                  title: t("pages.corrections.colHits"),
                  width: 110,
                  render: (_: unknown, r) => (
                    <span>
                      <strong>{r.hits}</strong>{" "}
                      <Typography.Text type="secondary" style={{ fontSize: 12 }}>{t("pages.corrections.inDocs", { count: r.documents })}</Typography.Text>
                    </span>
                  ),
                },
                {
                  title: t("pages.corrections.colUndone"),
                  width: 90,
                  render: (_: unknown, r) => (r.often_undone ? <Tag color="warning">{r.reverts}</Tag> : r.reverts),
                },
                {
                  title: t("pages.corrections.colOn"),
                  width: 150,
                  render: (_: unknown, r) => (
                    <Space>
                      <Switch
                        checked={r.enabled}
                        disabled={!canEdit}
                        loading={toggle.isPending && toggle.variables?.id === r.id}
                        aria-label={t("pages.corrections.toggle", { num: r.num })}
                        onChange={(on) => toggle.mutate({ id: r.id, enabled: on })}
                      />
                      {canEdit && (
                        <Button size="small" type="link" loading={apply.isPending && apply.variables === r.id} onClick={() => apply.mutate(r.id)}>
                          {t("pages.corrections.apply")}
                        </Button>
                      )}
                    </Space>
                  ),
                },
              ]}
            />
          </Space>
        </Card>
      )}
      <Modal
        open={!!changed}
        title={changed ? t("pages.corrections.changedTitle", { num: changed.rule.num }) : ""}
        okText={changed ? t("pages.corrections.applyTo", { count: changed.docs.length }) : ""}
        cancelText={t("pages.corrections.later")}
        confirmLoading={apply.isPending}
        onOk={() => changed && apply.mutate(changed.rule.id)}
        onCancel={() => setChanged(null)}
      >
        {changed && (
          <Space orientation="vertical" size={6} style={{ width: "100%" }}>
            <span>{t(changed.rule.enabled ? "pages.corrections.changedOn" : "pages.corrections.changedOff", { count: changed.docs.length })}</span>
            {changed.docs.slice(0, 12).map((x) => (
              <Typography.Text key={x.room_id + x.rel} type="secondary" style={{ fontSize: 12 }}>
                {x.room} · {x.rel.split("/").pop()}
              </Typography.Text>
            ))}
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>{t("pages.corrections.keepsUndone")}</Typography.Text>
          </Space>
        )}
      </Modal>
    </Space>
  );
}
