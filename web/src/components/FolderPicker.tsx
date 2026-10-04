import { useEffect, useState } from "react";
import { api } from "../api";
import type { BrowseResp } from "../types";
import { useI18n } from "../i18n";

/** 后端目录浏览器：本机部署下比 HTML 目录选择器更好用，可逐级下钻到任意盘。 */
export default function FolderPicker({
  title,
  onClose,
  onPick,
}: {
  title: string;
  onClose: () => void;
  onPick: (path: string) => void;
}) {
  const [t] = useI18n();
  const [b, setB] = useState<BrowseResp>({ cwd: "", dirs: [], files: [] });
  const [err, setErr] = useState("");

  const load = async (p: string) => {
    try {
      setErr("");
      setB(await api.browse(p));
    } catch (e: any) {
      setErr(e.message);
    }
  };
  useEffect(() => {
    load("");
  }, []);

  const parent = b.cwd ? b.cwd.replace(/[\\/]+$/, "").split(/[\\/]/).slice(0, -1).join("\\") || "C:\\" : "";

  return (
    <div className="mask" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <header>
          <h3>{title}</h3>
          <div className="spacer" />
          <button onClick={onClose}>{t("src.close")}</button>
        </header>
        <div className="body">
          {err && <div className="notice err" style={{ margin: "0 0 11px" }}>{err}</div>}
          <div className="cwd">{t("folder.current", { p: b.cwd || t("folder.noDrive") })}</div>
          <div className="dirgrid" style={{ marginBottom: 10 }}>
            {!!b.cwd && (
              <div className="di" onClick={() => load(parent)}>
                {t("folder.up")}
              </div>
            )}
            {b.dirs.map((d) => (
              <div
                key={d}
                className="di"
                onClick={() => load(b.cwd ? `${b.cwd.replace(/[\\/]+$/, "")}\\${d}` : `${d}\\`)}
              >
                {d}
              </div>
            ))}
          </div>
          {b.dirs.length === 0 && !b.cwd && <div className="empty">{t("folder.noDriveFound")}</div>}
        </div>
        <footer>
          <button onClick={onClose}>{t("act.cancel")}</button>
          <button className="primary" disabled={!b.cwd} onClick={() => onPick(b.cwd)}>
            {t("folder.pickThis")}
          </button>
        </footer>
      </div>
    </div>
  );
}
