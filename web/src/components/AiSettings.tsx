import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Alert, AutoComplete, Button, Card, Input, InputNumber, Popconfirm, Segmented, Select, Space, Switch, Table, Tag, Typography } from "antd";
import { api, json } from "../net/client";
import { ErrorState, Loading } from "./ui";

type Skill = "arbitrate" | "explain" | "transcribe" | "suggest";
interface Provider {
  id: string;
  kind: string;
  label: string;
  base_url: string | null;
  models: string[];
  prices: Record<string, [number, number]>;
  last4: string;
}
interface SkillCfg {
  provider: string | null;
  model: string | null;
  level: 0 | 1 | 2;
  budget_usd: number;
  monthly_cap: number;
}
interface SkillStats {
  calls: number;
  cached: number;
  blocked: number;
  errors: number;
  invalid: number;
  spend: number;
  adopted: number;
  modified: number;
  rejected: number;
  adoption: number | null;
  paused_s: number;
}
export interface AiSettingsData {
  enabled: boolean;
  providers: Provider[];
  skills: Record<Skill, SkillCfg>;
  scope: { allowed_prefixes: string[]; block_licensed: boolean };
  evals: Record<string, { score: number; n: number; at: number }>;
  kinds: Record<string, { label: string; models: string[]; custom: boolean }>;
  stats: { skills: Record<Skill, SkillStats>; memory: { cache: number; examples: number; rules: number } };
  examples: Record<Skill, number>;
}
const SKILLS: Skill[] = ["arbitrate", "explain", "transcribe", "suggest"];

function SkillRow({ name, data, onSaved }: { name: Skill; data: AiSettingsData; onSaved: (d: AiSettingsData) => void }) {
  const { t } = useTranslation();
  const cfg = data.skills[name];
  const [v, setV] = useState<SkillCfg>(cfg);
  useEffect(() => setV(cfg), [cfg]);
  const prov = data.providers.find((p) => p.id === v.provider);
  const st = data.stats.skills[name];
  const dirty = JSON.stringify(v) !== JSON.stringify(cfg);
  const save = useMutation({ mutationFn: () => api<AiSettingsData>("/ai/settings", { ...json({ skills: { [name]: v } }), method: "PUT" }), onSuccess: onSaved });
  const test = useMutation({
    mutationFn: () => api<{ score: number; n: number; settings: AiSettingsData }>(`/ai/skills/${name}/evaluate`, json({ provider: v.provider, model: v.model })),
    onSuccess: (r) => onSaved(r.settings),
  });
  const score = v.provider && v.model ? data.evals[`${name}|${v.provider}|${v.model}`] : undefined;
  const err = (save.error || test.error) as Error | null;
  return (
    <Card size="small" title={t(`pages.ai.skill.${name}`)} extra={<Typography.Text type="secondary" style={{ fontSize: 12 }}>{t(`pages.ai.skillHint.${name}`)}</Typography.Text>}>
      <Space orientation="vertical" size={10} style={{ width: "100%" }}>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 10 }}>
          <label style={{ display: "grid", gap: 4 }}>
            <span>{t("pages.ai.provider")}</span>
            <Select
              value={v.provider ?? undefined}
              placeholder={t("pages.ai.none")}
              allowClear
              onChange={(x) => setV({ ...v, provider: x ?? null, model: x ? (data.providers.find((p) => p.id === x)?.models[0] ?? null) : null })}
              options={data.providers.map((p) => ({ value: p.id, label: `${p.label} ••••${p.last4}` }))}
            />
          </label>
          <label style={{ display: "grid", gap: 4 }}>
            <span>{t("pages.ai.model")}</span>
            <AutoComplete
              value={v.model ?? ""}
              disabled={!v.provider}
              onChange={(x) => setV({ ...v, model: x || null })}
              options={(prov?.models ?? []).map((m) => ({ value: m }))}
            />
          </label>
          <div style={{ display: "grid", gap: 4 }}>
            <span>{t("pages.ai.level")}</span>
            <Segmented
              value={v.level}
              onChange={(x) => setV({ ...v, level: x as SkillCfg["level"] })}
              options={[
                { value: 0, label: t("pages.ai.level0") },
                { value: 1, label: t("pages.ai.level1") },
                ...(name === "arbitrate" ? [{ value: 2, label: t("pages.ai.level2") }] : []),
              ]}
            />
          </div>
          <label style={{ display: "grid", gap: 4 }}>
            <span>{t("pages.ai.budget")}</span>
            <InputNumber min={0} step={5} prefix="$" value={v.budget_usd} onChange={(x) => setV({ ...v, budget_usd: x ?? 0 })} style={{ width: "100%" }} />
          </label>
          <label style={{ display: "grid", gap: 4 }}>
            <span>{t("pages.ai.cap")}</span>
            <InputNumber min={0} step={50} value={v.monthly_cap} onChange={(x) => setV({ ...v, monthly_cap: x ?? 0 })} style={{ width: "100%" }} />
          </label>
        </div>
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          {t("pages.ai.thisMonth", { calls: st.calls, cached: st.cached, spend: st.spend.toFixed(2) })}
          {" · "}
          {st.adoption == null ? t("pages.ai.noDecisions") : t("pages.ai.adoption", { pct: st.adoption, n: st.adopted + st.modified + st.rejected })}
          {st.blocked ? ` · ${t("pages.ai.blocked", { n: st.blocked })}` : ""}
          {st.errors ? ` · ${t("pages.ai.errors", { n: st.errors })}` : ""}
        </Typography.Text>
        {st.paused_s > 0 && <Alert type="warning" showIcon title={t("pages.ai.paused", { min: Math.ceil(st.paused_s / 60) })} />}
        {err && <Alert type="error" showIcon title={err.message} />}
        <Space wrap>
          <Button type="primary" disabled={!dirty} loading={save.isPending} onClick={() => save.mutate()}>{t("pages.ai.save")}</Button>
          {name === "arbitrate" && (
            <Button disabled={!v.provider || !v.model || !data.examples[name]} loading={test.isPending} onClick={() => test.mutate()}>
              {t("pages.ai.test", { n: data.examples[name] })}
            </Button>
          )}
          {score && <Tag color={score.score >= 85 ? "success" : "warning"}>{t("pages.ai.score", { score: score.score, n: score.n })}</Tag>}
        </Space>
      </Space>
    </Card>
  );
}

function Providers({ data, onSaved }: { data: AiSettingsData; onSaved: (d: AiSettingsData) => void }) {
  const { t } = useTranslation();
  const [kind, setKind] = useState("anthropic");
  const [key, setKey] = useState("");
  const [url, setUrl] = useState("");
  const [tested, setTested] = useState<Record<string, string>>({});
  const add = useMutation({
    mutationFn: () => api<AiSettingsData>("/ai/providers", json({ kind, key, base_url: data.kinds[kind]?.custom ? url : null })),
    onSuccess: (d) => {
      setKey("");
      setUrl("");
      onSaved(d);
    },
  });
  const remove = useMutation({ mutationFn: (id: string) => api<AiSettingsData>(`/ai/providers/${id}`, { method: "DELETE" }), onSuccess: onSaved });
  const models = useMutation({
    mutationFn: (p: { id: string; models: string[] }) => api<AiSettingsData>(`/ai/providers/${p.id}`, { ...json({ models: p.models }), method: "PATCH" }),
    onSuccess: onSaved,
  });
  const test = useMutation({
    mutationFn: (p: Provider) => api<{ ok: boolean; seconds?: number; message?: string }>(`/ai/providers/${p.id}/test`, json({ model: p.models[0] ?? "" })),
    onSuccess: (r, p) => setTested({ ...tested, [p.id]: r.ok ? t("pages.ai.testOk", { s: r.seconds }) : r.message || t("pages.ai.testFailed") }),
  });
  const err = (add.error || remove.error || models.error || test.error) as Error | null;
  return (
    <Card title={t("pages.ai.providers")}>
      <Space orientation="vertical" size={12} style={{ width: "100%" }}>
        {data.providers.length === 0 && <Typography.Text type="secondary">{t("pages.ai.noProviders")}</Typography.Text>}
        {data.providers.map((p) => (
          <div key={p.id} style={{ display: "grid", gap: 6, paddingBottom: 10, borderBottom: "1px solid var(--ant-color-border-secondary)" }}>
            <Space wrap>
              <strong>{p.label}</strong>
              <Typography.Text type="secondary">{t("pages.ai.keyEnds", { last4: p.last4 })}</Typography.Text>
              {p.base_url && <Typography.Text type="secondary" style={{ fontSize: 12 }}>{p.base_url}</Typography.Text>}
              <Button size="small" disabled={!p.models.length} loading={test.isPending && test.variables?.id === p.id} onClick={() => test.mutate(p)}>
                {t("pages.ai.testConnection")}
              </Button>
              <Popconfirm title={t("pages.ai.removeConfirm")} okText={t("pages.ai.remove")} cancelText={t("pages.distill.cancel")} onConfirm={() => remove.mutate(p.id)}>
                <Button size="small" danger type="link">{t("pages.ai.remove")}</Button>
              </Popconfirm>
              {tested[p.id] && <Typography.Text style={{ fontSize: 12 }}>{tested[p.id]}</Typography.Text>}
            </Space>
            <label style={{ display: "grid", gap: 4 }}>
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>{t("pages.ai.models")}</Typography.Text>
              <Select
                mode="tags"
                value={p.models}
                aria-label={t("pages.ai.modelsOf", { name: p.label })}
                onChange={(m) => models.mutate({ id: p.id, models: m })}
                tokenSeparators={[",", " "]}
                open={false}
                style={{ width: "100%" }}
              />
            </label>
          </div>
        ))}
        <Typography.Text strong>{t("pages.ai.addProvider")}</Typography.Text>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: 10 }}>
          <label style={{ display: "grid", gap: 4 }}>
            <span>{t("pages.ai.provider")}</span>
            <Select value={kind} onChange={setKind} options={Object.entries(data.kinds).map(([k, v]) => ({ value: k, label: v.label }))} />
          </label>
          <label style={{ display: "grid", gap: 4 }}>
            <span>{t("pages.ai.apiKey")}</span>
            <Input.Password value={key} onChange={(e) => setKey(e.target.value)} autoComplete="off" />
          </label>
          {data.kinds[kind]?.custom && (
            <label style={{ display: "grid", gap: 4 }}>
              <span>{t("pages.ai.address")}</span>
              <Input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://" autoComplete="off" />
            </label>
          )}
        </div>
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>{t("pages.ai.keyNote")}</Typography.Text>
        <div>
          <Button type="primary" disabled={key.length < 8} loading={add.isPending} onClick={() => add.mutate()}>{t("pages.ai.add")}</Button>
        </div>
        {err && <Alert type="error" showIcon title={err.message} />}
      </Space>
    </Card>
  );
}

function Scope({ data, onSaved }: { data: AiSettingsData; onSaved: (d: AiSettingsData) => void }) {
  const { t } = useTranslation();
  const [prefixes, setPrefixes] = useState<string[]>(data.scope.allowed_prefixes);
  const [licensed, setLicensed] = useState(data.scope.block_licensed);
  useEffect(() => {
    setPrefixes(data.scope.allowed_prefixes);
    setLicensed(data.scope.block_licensed);
  }, [data.scope]);
  const dirty = JSON.stringify(prefixes) !== JSON.stringify(data.scope.allowed_prefixes) || licensed !== data.scope.block_licensed;
  const save = useMutation({
    mutationFn: () => api<AiSettingsData>("/ai/settings", { ...json({ scope: { allowed_prefixes: prefixes, block_licensed: licensed } }), method: "PUT" }),
    onSuccess: onSaved,
  });
  return (
    <Card title={t("pages.ai.scope")}>
      <Space orientation="vertical" size={10} style={{ width: "100%" }}>
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>{t("pages.ai.scopeHint")}</Typography.Text>
        <Select
          mode="tags"
          value={prefixes}
          onChange={setPrefixes}
          open={false}
          aria-label={t("pages.ai.allowed")}
          placeholder={t("pages.ai.allowedPlaceholder")}
          style={{ width: "100%" }}
        />
        <Space>
          <Switch checked={licensed} onChange={setLicensed} aria-label={t("pages.ai.blockLicensed")} />
          <span>{t("pages.ai.blockLicensed")}</span>
        </Space>
        {save.error && <Alert type="error" showIcon title={(save.error as Error).message} />}
        <div>
          <Button type="primary" disabled={!dirty} loading={save.isPending} onClick={() => save.mutate()}>{t("pages.ai.save")}</Button>
        </div>
      </Space>
    </Card>
  );
}

/** Settings → AI (administrators only). AI only suggests; people and rules decide. */
export function AiSettings() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["ai-settings"], queryFn: () => api<AiSettingsData>("/ai/settings") });
  const set = (d: AiSettingsData) => qc.setQueryData(["ai-settings"], d);
  const toggle = useMutation({ mutationFn: (on: boolean) => api<AiSettingsData>("/ai/settings", { ...json({ enabled: on }), method: "PUT" }), onSuccess: set });
  const wipe = useMutation({ mutationFn: () => api<AiSettingsData>("/ai/keys", { method: "DELETE" }), onSuccess: set });
  if (q.isLoading) return <Loading />;
  if (q.isError) return <ErrorState message={(q.error as Error).message} onRetry={() => void q.refetch()} />;
  const d = q.data!;
  const m = d.stats.memory;
  return (
    <Space orientation="vertical" size={16} style={{ width: "100%" }}>
      <Typography.Text type="secondary">{t("pages.ai.intro")}</Typography.Text>
      <Card>
        <Space>
          <Switch checked={d.enabled} loading={toggle.isPending} onChange={(on) => toggle.mutate(on)} aria-label={t("pages.ai.master")} />
          <strong>{t("pages.ai.master")}</strong>
          <Typography.Text type="secondary">{d.enabled ? t("pages.ai.on") : t("pages.ai.off")}</Typography.Text>
        </Space>
        {toggle.error && <Alert type="error" showIcon title={(toggle.error as Error).message} style={{ marginTop: 10 }} />}
      </Card>
      <Providers data={d} onSaved={set} />
      {SKILLS.filter((s) => d.skills[s] && d.stats.skills[s]).map((s) => (
        <SkillRow key={s} name={s} data={d} onSaved={set} />
      ))}
      <Scope data={d} onSaved={set} />
      <Card title={t("pages.ai.memory")}>
        <Table
          size="small"
          pagination={false}
          rowKey="k"
          showHeader={false}
          dataSource={[
            { k: "rules", label: t("pages.ai.memRules"), n: m.rules },
            { k: "cache", label: t("pages.ai.memCache"), n: m.cache },
            { k: "examples", label: t("pages.ai.memExamples"), n: m.examples },
          ]}
          columns={[{ dataIndex: "label" }, { dataIndex: "n", width: 80, align: "right" }]}
        />
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>{t("pages.ai.memoryHint")}</Typography.Text>
      </Card>
      <Card title={t("pages.ai.danger")} style={{ borderColor: "var(--ant-color-error-border)" }}>
        <Space orientation="vertical" size={8}>
          <Typography.Text>{t("pages.ai.wipeHint")}</Typography.Text>
          <Popconfirm title={t("pages.ai.wipeConfirm")} okText={t("pages.ai.wipe")} okButtonProps={{ danger: true }} cancelText={t("pages.distill.cancel")} onConfirm={() => wipe.mutate()}>
            <Button danger disabled={!d.providers.length} loading={wipe.isPending}>{t("pages.ai.wipe")}</Button>
          </Popconfirm>
        </Space>
      </Card>
    </Space>
  );
}
