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
    <div className="mask" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <header>
          <h3>数据源管理</h3>
          <span className="sub">源目录 → .md 镜像目录的映射</span>
          <div className="spacer" />
          <button onClick={onClose}>关闭</button>
        </header>
        <div className="body">
          {err && <div className="notice err" style={{ margin: "0 0 11px" }}>{err}</div>}

          <div className="callout">已配置 {sources.length} 个数据源</div>
          {sources.map((s) => (
            <div className="lrow" key={s.id}>
              <div className="info">
                <div className="nm">
                  {s.name}
                  <span className="badge unreviewed">{s.id}</span>
                </div>
                <div className="pp">源：{s.src_root}</div>
                <div className="pp">.md：{s.md_root}</div>
              </div>
              <div className="a">
                <button onClick={() => edit(s)}>编辑</button>
                <button className="danger" onClick={() => del(s)}>
                  删除
                </button>
              </div>
            </div>
          ))}

          <div className="callout" style={{ marginTop: 14 }}>
            新增 / 修改
          </div>
          <div className="row2">
            <div className="field">
              <label>数据源 ID（英文，唯一）</label>
              <input value={draft.id || ""} onChange={(e) => setDraft({ ...draft, id: e.target.value })} />
            </div>
            <div className="field">
              <label>显示名称</label>
              <input value={draft.name || ""} onChange={(e) => setDraft({ ...draft, name: e.target.value })} />
            </div>
          </div>
          <div className="field">
            <label>源文件目录（放原始 PDF / Word / CAD 等）</label>
            <div style={{ display: "flex", gap: 6 }}>
              <input readOnly value={draft.src_root || ""} placeholder="点击右侧选择" />
              <button onClick={() => onPick("src_root")} style={{ flexShrink: 0 }}>
                选择…
              </button>
            </div>
          </div>
          <div className="field">
            <label>.md 输出镜像目录（转换结果按同构路径落盘）</label>
            <div style={{ display: "flex", gap: 6 }}>
              <input readOnly value={draft.md_root || ""} placeholder="点击右侧选择" />
              <button onClick={() => onPick("md_root")} style={{ flexShrink: 0 }}>
                选择…
              </button>
            </div>
          </div>
        </div>
        <footer>
          <button onClick={() => setDraft({ id: "", name: "", src_root: "", md_root: "", enabled: true })}>
            清空
          </button>
          <div className="spacer" />
          <button onClick={onClose}>取消</button>
          <button className="primary" onClick={save}>
            保存数据源
          </button>
        </footer>
      </div>
    </div>
  );
}
