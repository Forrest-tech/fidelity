import { useState } from "react";
import { api } from "../api";
import type { Source } from "../types";
import { useI18n } from "../i18n";

/** 数据源管理：新增/编辑/删除「源目录 → .md 镜像目录」映射，不写死路径。 */
export default function SourceManager({
  sources,
  draft,
  setDraft,
  onSaved,
  onPick,
  onClose,
}: {
  sources: Source[];
  draft: Partial<Source>;
  setDraft: (d: Partial<Source>) => void;
  onSaved: () => void;
  onPick: (which: "src_root" | "md_root") => void;
  onClose: () => void;
}) {
  const [t] = useI18n();
  const [err, setErr] = useState("");

  const save = async () => {
    try {
      setErr("");
      if (!draft.id || !draft.name || !draft.src_root || !draft.md_root) {
        setErr(t("src.needFields"));
        return;
      }
      await api.saveSource({
        id: draft.id,
        name: draft.name,
        src_root: draft.src_root,
        md_root: draft.md_root,
        enabled: true,
      });
      onSaved();
    } catch (e: any) {
      setErr(e.message);
    }
  };

  const edit = (s: Source) => setDraft({ ...s });
  const del = async (s: Source) => {
    if (!confirm(t("src.confirmRemove", { name: s.name }))) return;
    await api.deleteSource(s.id);
    onSaved();
  };

  return (
    <div className="mask" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <header>
          <h3>{t("src.mgrTitle")}</h3>
          <span className="sub">{t("src.mgrSub")}</span>
          <div className="spacer" />
          <button onClick={onClose}>{t("src.close")}</button>
        </header>
        <div className="body">
          {err && <div className="notice err" style={{ margin: "0 0 11px" }}>{err}</div>}

          <div className="callout">{t("src.configured", { n: sources.length })}</div>
          {sources.map((s) => (
            <div className="lrow" key={s.id}>
              <div className="info">
                <div className="nm">
                  {s.name}
                  <span className="badge unreviewed">{s.id}</span>
                </div>
                <div className="pp">{t("src.srcLabel", { p: s.src_root })}</div>
                <div className="pp">{t("src.mdLabel", { p: s.md_root })}</div>
              </div>
              <div className="a">
                <button onClick={() => edit(s)}>{t("src.edit")}</button>
                <button className="danger" onClick={() => del(s)}>
                  {t("src.remove")}
                </button>
              </div>
            </div>
          ))}

          <div className="callout" style={{ marginTop: 14 }}>
            {t("src.addEdit")}
          </div>
          <div className="row2">
            <div className="field">
              <label>{t("src.idLabel")}</label>
              <input value={draft.id || ""} onChange={(e) => setDraft({ ...draft, id: e.target.value })} />
            </div>
            <div className="field">
              <label>{t("src.nameLabel")}</label>
              <input value={draft.name || ""} onChange={(e) => setDraft({ ...draft, name: e.target.value })} />
            </div>
          </div>
          <div className="field">
            <label>{t("src.srcDirLabel")}</label>
            <div style={{ display: "flex", gap: 6 }}>
              <input readOnly value={draft.src_root || ""} placeholder={t("src.pickPh")} />
              <button onClick={() => onPick("src_root")} style={{ flexShrink: 0 }}>
                {t("src.pick")}
              </button>
            </div>
          </div>
          <div className="field">
            <label>{t("src.mdDirLabel")}</label>
            <div style={{ display: "flex", gap: 6 }}>
              <input readOnly value={draft.md_root || ""} placeholder={t("src.pickPh")} />
              <button onClick={() => onPick("md_root")} style={{ flexShrink: 0 }}>
                {t("src.pick")}
              </button>
            </div>
          </div>
        </div>
        <footer>
          <button onClick={() => setDraft({ id: "", name: "", src_root: "", md_root: "", enabled: true })}>
            {t("src.clear")}
          </button>
          <div className="spacer" />
          <button onClick={onClose}>{t("act.cancel")}</button>
          <button className="primary" onClick={save}>
            {t("src.save")}
          </button>
        </footer>
      </div>
    </div>
  );
}
