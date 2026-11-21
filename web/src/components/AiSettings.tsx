import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { AutoComplete, Modal, Popconfirm, Select } from "antd";
import { api, json } from "../net/client";
import { ErrorState, Loading, PageHeader, Pill, Seg } from "./ui";

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
  level: number;
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
  level3?: Level3;
  demotions?: Demotion[];
}
interface Level3 {
  eligible: boolean;
  decided: number;
  adoption: number | null;
  missing: { code: "decided" | "adoption" | "wrong" | "glossary"; have?: number | null; need?: number; at?: number }[];
  auto: { total: number; right: number; wrong: number };
  pending: number;
}

/** Why automatic adoption (level 3) cannot be switched on yet, or how it is doing. */
function Level3Info({ data, level }: { data: AiSettingsData; level: number }) {
  const { t, i18n } = useTranslation();
  const l3 = data.level3;
  const last = data.demotions?.[data.demotions.length - 1];
  if (!l3) return null;
  const why = (m: Level3["missing"][number]) =>
    m.code === "decided"
      ? t("pages.ai.l3.decided", { have: m.have ?? 0, need: m.need })
      : m.code === "adoption"
        ? t("pages.ai.l3.adoption", { have: m.have ?? 0, need: m.need })
        : m.code === "wrong"
          ? t("pages.ai.l3.wrong", { date: m.at ? new Date(m.at * 1000).toLocaleDateString(i18n.language) : "" })
          : t("pages.ai.l3.glossary");
  return (
    <div className="fx-stack" style={{ gap: 6 }}>
      <div className="fx-tiny fx-muted" role="status">
        {level === 3
          ? t("pages.ai.l3.on", { total: l3.auto.total, right: l3.auto.right, wrong: l3.auto.wrong, pending: l3.pending })
          : l3.eligible
            ? t("pages.ai.l3.earned")
            : `${t("pages.ai.l3.notYet")} ${l3.missing.map(why).join(" · ")}`}
      </div>
      {last && <Demoted last={last} />}
    </div>
  );
}

/** The skill went back a level by itself (an automatic adoption was found wrong). */
interface Demotion { at: number; from: number; to: number; reason: string; code?: string | null; args?: Record<string, string | null> }
function Demoted({ last }: { last: Demotion }) {
  const { t, i18n } = useTranslation();
  // said in the reader's language when the server says what happened; the server's English sentence otherwise
  const why = last.code && i18n.exists(`pages.ai.l3.why.${last.code}`) ? t(`pages.ai.l3.why.${last.code}`, last.args ?? {}) : last.reason;
  return (
    <div className="fx-note" role="alert" style={{ borderLeftColor: "var(--warn)", background: "var(--warn-soft)" }}>
      <b>{t("pages.ai.l3.demoted", { from: last.from, to: last.to, date: new Date(last.at * 1000).toLocaleString(i18n.language) })}</b>
      {why && <div className="fx-muted" style={{ overflowWrap: "anywhere" }}>{why}</div>}
    </div>
  );
}
const SKILLS: Skill[] = ["arbitrate", "explain", "transcribe", "suggest"];
const MAX_LEVEL: Record<Skill, number> = { arbitrate: 3, explain: 1, transcribe: 1, suggest: 1 };

// ------------------------------------------------------------------ one skill, edited in a dialog
function SkillEdit({ name, data, onSaved, onClose }: { name: Skill; data: AiSettingsData; onSaved: (d: AiSettingsData) => void; onClose: () => void }) {
  const { t } = useTranslation();
  const cfg = data.skills[name];
  const [v, setV] = useState<SkillCfg>(cfg);
  const prov = data.providers.find((p) => p.id === v.provider);
  const dirty = JSON.stringify(v) !== JSON.stringify(cfg);
  const save = useMutation({
    mutationFn: () => api<AiSettingsData>("/ai/settings", { ...json({ skills: { [name]: v } }), method: "PUT" }),
    onSuccess: (d) => {
      onSaved(d);
      onClose();
    },
  });
  const test = useMutation({
    mutationFn: () => api<{ score: number; n: number; settings: AiSettingsData }>(`/ai/skills/${name}/evaluate`, json({ provider: v.provider, model: v.model })),
    onSuccess: (r) => onSaved(r.settings),
  });
  const score = v.provider && v.model ? data.evals[`${name}|${v.provider}|${v.model}`] : undefined;
  const err = (save.error || test.error) as Error | null;
  const levels = [
    { value: 0, label: t("pages.ai.level0") },
    { value: 1, label: t("pages.ai.level1") },
    ...(MAX_LEVEL[name] >= 2 ? [{ value: 2, label: t("pages.ai.level2") }] : []),
    // level 3 is earned: it can be chosen only once the record allows it (or to keep it when it is already on)
    ...(MAX_LEVEL[name] >= 3
      ? [{ value: 3, label: t("pages.ai.level3"), disabled: cfg.level !== 3 && !data.level3?.eligible, title: cfg.level !== 3 && !data.level3?.eligible ? t("pages.ai.levelLocked") : undefined }]
      : []),
  ];
  return (
    <Modal open onCancel={onClose} title={t(`pages.ai.skill.${name}`)} width={520}
      footer={[
        <button key="c" className="fx-btn" onClick={onClose}>{t("pages.distill.cancel")}</button>,
        <button key="s" className="fx-btn pri" style={{ marginLeft: 8 }} disabled={!dirty || save.isPending} onClick={() => save.mutate()}>{t("pages.ai.save")}</button>,
      ]}>
      <div className="fx-stack" style={{ gap: 12 }}>
        <div className="fx-tiny fx-muted">{t(`pages.ai.skillHint.${name}`)}</div>
        <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) minmax(0, 1fr)", gap: 10 }}>
          <label>
            <span className="fx-lab">{t("pages.ai.provider")}</span>
            <Select value={v.provider ?? undefined} placeholder={t("pages.ai.none")} allowClear style={{ width: "100%" }} aria-label={t("pages.ai.provider")}
              onChange={(x) => setV({ ...v, provider: x ?? null, model: x ? (data.providers.find((p) => p.id === x)?.models[0] ?? null) : null })}
              options={data.providers.map((p) => ({ value: p.id, label: `${p.label} ••••${p.last4}` }))} />
          </label>
          <label>
            <span className="fx-lab">{t("pages.ai.model")}</span>
            <AutoComplete value={v.model ?? ""} disabled={!v.provider} style={{ width: "100%" }} aria-label={t("pages.ai.model")}
              onChange={(x) => setV({ ...v, model: x || null })} options={(prov?.models ?? []).map((m) => ({ value: m }))} />
          </label>
        </div>
        <div>
          <span className="fx-lab">{t("pages.ai.level")}</span>
          <div style={{ overflowX: "auto", maxWidth: "100%" }}>
            <Seg label={t("pages.ai.level")} value={v.level} onChange={(x) => setV({ ...v, level: x })} options={levels} />
          </div>
          {name === "arbitrate" && <div style={{ marginTop: 6 }}><Level3Info data={data} level={v.level} /></div>}
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) minmax(0, 1fr)", gap: 10 }}>
          <label>
            <span className="fx-lab">{t("pages.ai.budget")}</span>
            <span className="fx-field"><span className="fx-muted">$</span>
              <input inputMode="decimal" value={String(v.budget_usd)} aria-label={t("pages.ai.budget")} onChange={(e) => setV({ ...v, budget_usd: Number(e.target.value.replace(/[^\d.]/g, "")) || 0 })} /></span>
          </label>
          <label>
            <span className="fx-lab">{t("pages.ai.cap")}</span>
            <span className="fx-field"><input inputMode="numeric" value={String(v.monthly_cap)} aria-label={t("pages.ai.cap")} onChange={(e) => setV({ ...v, monthly_cap: Number(e.target.value.replace(/\D/g, "")) || 0 })} /></span>
          </label>
        </div>
        {name === "arbitrate" && (
          <div className="fx-row fx-wrap">
            <button className="fx-btn" disabled={!v.provider || !v.model || !data.examples[name] || test.isPending} onClick={() => test.mutate()}>
              {t("pages.ai.test", { n: data.examples[name] })}
            </button>
            {score && <Pill tone={score.score >= 85 ? "ok" : "warn"}>{t("pages.ai.score", { score: score.score, n: score.n })}</Pill>}
          </div>
        )}
        {err && <div className="fx-errnote" role="alert">{err.message}</div>}
      </div>
    </Modal>
  );
}

// ------------------------------------------------------------------ providers
function AddProvider({ data, onSaved, onClose }: { data: AiSettingsData; onSaved: (d: AiSettingsData) => void; onClose: () => void }) {
  const { t } = useTranslation();
  const [kind, setKind] = useState("anthropic");
  const [key, setKey] = useState("");
  const [url, setUrl] = useState("");
  const add = useMutation({
    mutationFn: () => api<AiSettingsData>("/ai/providers", json({ kind, key, base_url: data.kinds[kind]?.custom ? url : null })),
    onSuccess: (d) => {
      onSaved(d);
      onClose();
    },
  });
  return (
    <Modal open onCancel={onClose} title={t("pages.ai.addProvider")} width={460}
      footer={[
        <button key="c" className="fx-btn" onClick={onClose}>{t("pages.distill.cancel")}</button>,
        <button key="a" className="fx-btn pri" style={{ marginLeft: 8 }} disabled={key.length < 8 || add.isPending} onClick={() => add.mutate()}>{t("pages.ai.add")}</button>,
      ]}>
      <div className="fx-stack" style={{ gap: 12 }}>
        <label>
          <span className="fx-lab">{t("pages.ai.provider")}</span>
          <Select value={kind} onChange={setKind} style={{ width: "100%" }} aria-label={t("pages.ai.provider")} options={Object.entries(data.kinds).map(([k, v]) => ({ value: k, label: v.label }))} />
        </label>
        <label>
          <span className="fx-lab">{t("pages.ai.apiKey")}</span>
          <span className="fx-field"><input type="password" value={key} onChange={(e) => setKey(e.target.value)} autoComplete="off" aria-label={t("pages.ai.apiKey")} /></span>
        </label>
        {data.kinds[kind]?.custom && (
          <label>
            <span className="fx-lab">{t("pages.ai.address")}</span>
            <span className="fx-field"><input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://" autoComplete="off" aria-label={t("pages.ai.address")} /></span>
          </label>
        )}
        <div className="fx-tiny fx-muted">{t("pages.ai.keyNote")}</div>
        {add.error && <div className="fx-errnote" role="alert">{(add.error as Error).message}</div>}
      </div>
    </Modal>
  );
}

function ProviderCard({ p, onSaved }: { p: Provider; onSaved: (d: AiSettingsData) => void }) {
  const { t } = useTranslation();
  const [tested, setTested] = useState<string | null>(null);
  const [editing, setEditing] = useState<"key" | "models" | null>(null);
  const [key, setKey] = useState("");
  const [models, setModels] = useState<string[]>(p.models);
  useEffect(() => setModels(p.models), [p.models]);
  const test = useMutation({
    mutationFn: () => api<{ ok: boolean; seconds?: number; message?: string }>(`/ai/providers/${p.id}/test`, json({ model: p.models[0] ?? "" })),
    onSuccess: (r) => setTested(r.ok ? t("pages.ai.testOk", { s: r.seconds }) : r.message || t("pages.ai.testFailed")),
  });
  const patch = useMutation({
    mutationFn: (b: Record<string, unknown>) => api<AiSettingsData>(`/ai/providers/${p.id}`, { ...json(b), method: "PATCH" }),
    onSuccess: (d) => {
      onSaved(d);
      setEditing(null);
      setKey("");
    },
  });
  const remove = useMutation({ mutationFn: () => api<AiSettingsData>(`/ai/providers/${p.id}`, { method: "DELETE" }), onSuccess: onSaved });
  return (
    <div className="fx-prov">
      <div className="fx-row"><b>{p.label}</b><Pill tone="ok">{t("pages.ai.connected")}</Pill></div>
      <span className="fx-muted fx-tiny">{t("pages.ai.keyEnds", { last4: p.last4 })}{p.base_url ? ` · ${p.base_url}` : ""}</span>
      <span className="fx-muted fx-tiny" style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={p.models.join(", ")}>
        {t("pages.ai.modelsList", { list: p.models.join(", ") || "—" })}
      </span>
      <div className="fx-row fx-wrap" style={{ gap: 10 }}>
        <button className="fx-a" disabled={!p.models.length || test.isPending} onClick={() => test.mutate()}>{t("pages.ai.testConnection")}</button>
        <button className="fx-a" onClick={() => setEditing("key")}>{t("pages.ai.changeKey")}</button>
        <button className="fx-a" onClick={() => setEditing("models")}>{t("pages.ai.editModels")}</button>
        <Popconfirm title={t("pages.ai.removeConfirm")} okText={t("pages.ai.remove")} cancelText={t("pages.distill.cancel")} onConfirm={() => remove.mutate()}>
          <button className="fx-a" style={{ color: "var(--bad)" }}>{t("pages.ai.remove")}</button>
        </Popconfirm>
      </div>
      {tested && <span className="fx-tiny" role="status">{tested}</span>}
      {(patch.error || remove.error) && <span className="fx-tiny" style={{ color: "var(--bad)" }}>{((patch.error || remove.error) as Error).message}</span>}
      <Modal open={editing === "key"} onCancel={() => setEditing(null)} title={t("pages.ai.changeKeyOf", { name: p.label })} width={420}
        footer={[<button key="c" className="fx-btn" onClick={() => setEditing(null)}>{t("pages.distill.cancel")}</button>,
          <button key="s" className="fx-btn pri" style={{ marginLeft: 8 }} disabled={key.length < 8} onClick={() => patch.mutate({ key })}>{t("pages.ai.save")}</button>]}>
        <label><span className="fx-lab">{t("pages.ai.apiKey")}</span><span className="fx-field"><input type="password" value={key} onChange={(e) => setKey(e.target.value)} autoComplete="off" aria-label={t("pages.ai.apiKey")} /></span></label>
      </Modal>
      <Modal open={editing === "models"} onCancel={() => setEditing(null)} title={t("pages.ai.modelsOf", { name: p.label })} width={460}
        footer={[<button key="c" className="fx-btn" onClick={() => setEditing(null)}>{t("pages.distill.cancel")}</button>,
          <button key="s" className="fx-btn pri" style={{ marginLeft: 8 }} onClick={() => patch.mutate({ models })}>{t("pages.ai.save")}</button>]}>
        <Select mode="tags" value={models} onChange={setModels} open={false} tokenSeparators={[",", " "]} style={{ width: "100%" }} aria-label={t("pages.ai.modelsOf", { name: p.label })} />
        <div className="fx-tiny fx-muted" style={{ marginTop: 6 }}>{t("pages.ai.models")}</div>
      </Modal>
    </div>
  );
}

// ------------------------------------------------------------------ send scope
function Scope({ data, onSaved }: { data: AiSettingsData; onSaved: (d: AiSettingsData) => void }) {
  const { t } = useTranslation();
  const [prefixes, setPrefixes] = useState<string[]>(data.scope.allowed_prefixes);
  useEffect(() => setPrefixes(data.scope.allowed_prefixes), [data.scope]);
  const save = useMutation({
    mutationFn: (b: { allowed_prefixes?: string[]; block_licensed?: boolean }) => api<AiSettingsData>("/ai/settings", { ...json({ scope: { ...data.scope, ...b } }), method: "PUT" }),
    onSuccess: onSaved,
  });
  const dirty = JSON.stringify(prefixes) !== JSON.stringify(data.scope.allowed_prefixes);
  return (
    <div className="fx-card" style={{ padding: 14 }}>
      <b>{t("pages.ai.scope")}</b>
      <div className="fx-tiny fx-muted" style={{ marginTop: 2 }}>{t("pages.ai.scopeHint")}</div>
      <label className="fx-row fx-tiny" style={{ marginTop: 8 }}>
        <input type="checkbox" className="fx-cb" checked={data.scope.block_licensed} onChange={(e) => save.mutate({ block_licensed: e.target.checked })} />
        {t("pages.ai.blockLicensed")}
      </label>
      <div className="fx-row fx-tiny fx-wrap" style={{ marginTop: 6 }}>
        <span>{t("pages.ai.onlyFrom")}</span>
        <Select mode="tags" size="small" value={prefixes} onChange={setPrefixes} open={false} style={{ minWidth: 240, flex: 1 }} aria-label={t("pages.ai.allowed")} placeholder={t("pages.ai.allowedPlaceholder")} />
        <button className="fx-btn sm pri" disabled={!dirty || save.isPending} onClick={() => save.mutate({ allowed_prefixes: prefixes })}>{t("pages.ai.save")}</button>
      </div>
      {save.error && <div className="fx-errnote" style={{ marginTop: 6 }}>{(save.error as Error).message}</div>}
    </div>
  );
}

/** Settings → AI (administrators only), laid out as screen 4 of the design. AI only suggests; people and rules decide. */
export function AiSettings() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["ai-settings"], queryFn: () => api<AiSettingsData>("/ai/settings") });
  const set = (d: AiSettingsData) => qc.setQueryData(["ai-settings"], d);
  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState<Skill | null>(null);
  const toggle = useMutation({ mutationFn: (on: boolean) => api<AiSettingsData>("/ai/settings", { ...json({ enabled: on }), method: "PUT" }), onSuccess: set });
  const wipe = useMutation({ mutationFn: () => api<AiSettingsData>("/ai/keys", { method: "DELETE" }), onSuccess: set });
  if (q.isLoading) return <Loading />;
  if (q.isError) return <ErrorState message={(q.error as Error).message} onRetry={() => void q.refetch()} />;
  const d = q.data!;
  const m = d.stats.memory;
  const skills = SKILLS.filter((s) => d.skills[s] && d.stats.skills[s]);
  const month = skills.reduce((a, s) => ({ calls: a.calls + d.stats.skills[s].calls, spend: a.spend + d.stats.skills[s].spend, cached: a.cached + d.stats.skills[s].cached }), { calls: 0, spend: 0, cached: 0 });
  const prov = (id: string | null) => d.providers.find((p) => p.id === id);
  const others = Object.entries(d.kinds).filter(([k]) => !d.providers.some((p) => p.kind === k)).map(([, v]) => v.label);
  return (
    <>
      <PageHeader title={t("pages.settings.nav.ai")} desc={t("pages.ai.intro")}
        extra={
          <button role="switch" aria-checked={d.enabled} aria-label={t("pages.ai.master")} className="fx-btn sm" disabled={toggle.isPending} onClick={() => toggle.mutate(!d.enabled)}
            style={{ borderRadius: 999, padding: "1px 10px", background: d.enabled ? "var(--ok-soft)" : "var(--idle-soft)", color: d.enabled ? "var(--ok)" : "var(--idle)", borderColor: "transparent", fontWeight: 500 }}>
            <span aria-hidden style={{ width: 6, height: 6, borderRadius: "50%", background: "currentColor" }} />
            {d.enabled ? t("pages.ai.masterOn") : t("pages.ai.masterOff")}
          </button>
        } />
      {toggle.error && <div className="fx-errnote">{(toggle.error as Error).message}</div>}
      <div className="fx-row fx-wrap" style={{ gap: 18 }}>
        <span className="fx-tiny"><span className="fx-muted">{t("pages.ai.monthCalls")}</span> <b className="fx-num">{month.calls}</b></span>
        <span className="fx-tiny"><span className="fx-muted">{t("pages.ai.monthSpend")}</span> <b className="fx-num">${month.spend.toFixed(2)}</b></span>
        <span className="fx-tiny"><span className="fx-muted">{t("pages.ai.memCacheShort")}</span> <b className="fx-num">{m.cache}</b></span>
        <span className="fx-tiny"><span className="fx-muted">{t("pages.ai.memExamplesShort")}</span> <b className="fx-num">{m.examples}</b></span>
        <span className="fx-tiny"><span className="fx-muted">{t("pages.ai.memRulesShort")}</span> <b className="fx-num">{m.rules}</b></span>
      </div>
      <div className="fx-card" style={{ padding: 14 }}>
        <div className="fx-row"><b>{t("pages.ai.providers")}</b><span className="fx-sp" /><button className="fx-btn pri sm" onClick={() => setAdding(true)}>+ {t("pages.ai.add")}</button></div>
        <div className="fx-pv" style={{ marginTop: 10 }}>
          {d.providers.map((p) => <ProviderCard key={p.id} p={p} onSaved={set} />)}
          <div className="fx-prov">
            <b>{others.join(" · ")}</b>
            <span className="fx-muted fx-tiny">{d.providers.length ? t("pages.ai.pickWithAdd") : t("pages.ai.noProviders")}</span>
          </div>
        </div>
      </div>
      <div className="fx-card" style={{ padding: 14 }}>
        <b>{t("pages.ai.skillsTitle")}</b>
        <div className="fx-tbox" style={{ marginTop: 6 }}>
          <table className="fx-t">
            <thead><tr><th>{t("pages.ai.colSkill")}</th><th>{t("pages.ai.model")}</th><th>{t("pages.ai.colMode")}</th><th>{t("pages.ai.colBudget")}</th><th>{t("pages.ai.colAdoption")}</th><th><span className="sr-only">{t("pages.distill.colActions")}</span></th></tr></thead>
            <tbody>
              {skills.map((s) => {
                const c = d.skills[s];
                const st = d.stats.skills[s];
                const p = prov(c.provider);
                return (
                  <tr key={s}>
                    <td>{t(`pages.ai.skill.${s}`)}{st.paused_s > 0 && <> <Pill tone="warn">{t("pages.ai.pausedShort")}</Pill></>}</td>
                    <td className="fx-tiny">{p && c.model ? `${p.label} · ${c.model}` : <span className="fx-muted">{t("pages.ai.none")}</span>}</td>
                    <td className="fx-tiny">{p && c.model ? t(`pages.ai.mode${c.level}`) : <span className="fx-muted">—</span>}</td>
                    <td className="fx-num">${c.budget_usd} <span className="fx-muted fx-tiny">({t("pages.ai.spent", { n: st.spend.toFixed(2) })})</span></td>
                    <td className="fx-num">{st.adoption == null ? <span className="fx-muted">—</span> : `${st.adoption}%`}</td>
                    <td><button className="fx-a" onClick={() => setEditing(s)} aria-label={t("pages.ai.editSkill", { name: t(`pages.ai.skill.${s}`) })}>{t("pages.ai.edit")}</button></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <div className="fx-tiny fx-muted" style={{ marginTop: 6 }}>{t("pages.ai.levelsNote")}</div>
        {d.demotions?.length ? <div style={{ marginTop: 8 }}><Demoted last={d.demotions[d.demotions.length - 1]} /></div> : null}
      </div>
      <Scope data={d} onSaved={set} />
      <div className="fx-danger">
        <div className="fx-row"><b>{t("pages.ai.danger")}</b><span className="fx-sp" />
          <Popconfirm title={t("pages.ai.wipeConfirm")} okText={t("pages.ai.wipe")} okButtonProps={{ danger: true }} cancelText={t("pages.distill.cancel")} onConfirm={() => wipe.mutate()}>
            <button className="fx-btn" disabled={!d.providers.length || wipe.isPending}>{t("pages.ai.wipe")}</button>
          </Popconfirm>
        </div>
        <div className="fx-tiny fx-muted" style={{ marginTop: 4 }}>{t("pages.ai.wipeHint")}</div>
      </div>
      {adding && <AddProvider data={d} onSaved={set} onClose={() => setAdding(false)} />}
      {editing && <SkillEdit name={editing} data={d} onSaved={set} onClose={() => setEditing(null)} />}
    </>
  );
}
