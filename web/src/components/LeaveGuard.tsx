import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useBlocker } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Modal } from "antd";

/** Parts of a page with changes that are not saved yet (a new room, a room's edited folders) say so here.
 * Leaving the page then asks first:
 *  - inside the app (a link, the menu, Back): our own dialog — Save, Discard, or Stay;
 *  - reload or closing the tab: the browser's own "Leave site?" question. Browsers do not let a page offer
 *    "Save" there, so a draft is also kept in this browser tab and comes back after a reload. */
type Saver = () => Promise<unknown>;
interface Ctx { set: (id: string, save: Saver | null) => void }
const UnsavedCtx = createContext<Ctx>({ set: () => {} });

/** Report this part's unsaved state: `save` while there is something to save, null when there is none. */
export function useUnsaved(id: string, save: Saver | null) {
  const { set } = useContext(UnsavedCtx);
  const ref = useRef(save);
  ref.current = save;
  const has = !!save;
  useEffect(() => {
    set(id, has ? () => (ref.current ? ref.current() : Promise.resolve()) : null);
    return () => set(id, null);
  }, [id, has, set]);
}

export function LeaveGuard({ children }: { children: ReactNode }) {
  const { t } = useTranslation();
  const [savers, setSavers] = useState<Map<string, Saver>>(new Map());
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const set = useCallback((id: string, save: Saver | null) => {
    setSavers((m) => {
      if (!save && !m.has(id)) return m;
      const n = new Map(m);
      if (save) n.set(id, save);
      else n.delete(id);
      return n;
    });
  }, []);
  const ctx = useMemo(() => ({ set }), [set]);
  const dirty = savers.size > 0;
  const blocker = useBlocker(({ currentLocation, nextLocation }) => dirty && currentLocation.pathname !== nextLocation.pathname);
  useEffect(() => {
    if (!dirty) return;
    const h = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = "";                                  // older browsers need it set to show their question
    };
    window.addEventListener("beforeunload", h);
    return () => window.removeEventListener("beforeunload", h);
  }, [dirty]);
  const stay = () => {
    setErr(null);
    blocker.reset?.();
  };
  const discard = () => {
    setErr(null);
    setSavers(new Map());
    blocker.proceed?.();
  };
  const save = async () => {
    setBusy(true);
    setErr(null);
    try {
      for (const s of savers.values()) await s();
      setSavers(new Map());
      blocker.proceed?.();
    } catch (e) {
      setErr((e as Error).message || t("leave.saveFailed"));
    } finally {
      setBusy(false);
    }
  };
  return (
    <UnsavedCtx.Provider value={ctx}>
      {children}
      <Modal open={blocker.state === "blocked"} onCancel={stay} title={t("leave.title")} width={440} maskClosable={false}
        footer={[
          <button key="stay" className="fx-btn" onClick={stay}>{t("leave.stay")}</button>,
          <button key="discard" className="fx-btn danger" style={{ marginLeft: 8 }} disabled={busy} onClick={discard}>{t("leave.discard")}</button>,
          <button key="save" className="fx-btn pri" style={{ marginLeft: 8 }} disabled={busy} onClick={() => void save()}>{busy ? t("leave.saving") : t("leave.save")}</button>,
        ]}>
        <div className="fx-tiny">{t("leave.body")}</div>
        {err && <div className="fx-errnote" role="alert" style={{ marginTop: 8 }}>{err}</div>}
      </Modal>
    </UnsavedCtx.Provider>
  );
}
