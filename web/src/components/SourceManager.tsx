import { useState } from "react";
import { api } from "../api";
import type { Source } from "../types";

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
  const [err, setErr] = useState("");

  const save = async () => {
    try {
      setErr("");
      if (!draft.id || !draft.name || !draft.src_root || !draft.md_root) {
        setErr("请填写 id、名称、源目录与镜像目录");
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
    if (!confirm(`删除数据源「${s.name}」？已入库的文件不受影响。`)) return;
    await api.deleteSource(s.id);
    onSaved();
  };

  return (
    <div className="modal-mask" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <header>
          数据源管理
          <div className="spacer" />
          <button onClick={onClose}>关闭</button>
        </header>
        <div className="body">
          {err && <div className="notice err">{err}</div>}

          <div style={{ fontSize: 12, color: "var(--muted)", marginBottom: 8 }}>已配置</div>
          {sources.map((s) => (
            <div className="src-card" key={s.id}>
              <div className="info">
                <b>{s.name}</b>（{s.id}）
                <div>源：{s.src_root}</div>
                <div>.md：{s.md_root}</div>
              </div>
              <button onClick={() => edit(s)}>编辑</button>
              <button onClick={() => del(s)}>删除</button>
            </div>
          ))}

          <div style={{ fontSize: 12, color: "var(--muted)", margin: "14px 0 8px" }}>
            新增 / 修改
          </div>
          <div className="form-row">
            <label>数据源 ID（英文，唯一）</label>
            <input value={draft.id || ""} onChange={(e) => setDraft({ ...draft, id: e.target.value })} />
          </div>
          <div className="form-row">
            <label>显示名称</label>
            <input value={draft.name || ""} onChange={(e) => setDraft({ ...draft, name: e.target.value })} />
          </div>
          <div className="form-row">
            <label>源文件目录（放原始 PDF/Word 等）</label>
            <div style={{ display: "flex", gap: 6 }}>
              <input readOnly value={draft.src_root || ""} placeholder="点击右侧选择" />
              <button onClick={() => onPick("src_root")}>选择…</button>
            </div>
          </div>
          <div className="form-row">
            <label>.md 输出镜像目录（转换结果按同构路径落盘）</label>
            <div style={{ display: "flex", gap: 6 }}>
              <input readOnly value={draft.md_root || ""} placeholder="点击右侧选择" />
              <button onClick={() => onPick("md_root")}>选择…</button>
            </div>
          </div>
        </div>
        <footer>
          <button
            onClick={() =>
              setDraft({ id: "", name: "", src_root: "", md_root: "", enabled: true })
            }
          >
            清空
          </button>
          <button onClick={onClose}>取消</button>
          <button className="primary" onClick={save}>
            保存数据源
          </button>
        </footer>
      </div>
    </div>
  );
}
