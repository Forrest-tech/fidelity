import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Modal } from "antd";
import { Pill } from "./ui";

const STATES = [
  ["ok", "ok"], ["published", "ok"], ["below", "warn"], ["skipped", "idle"], ["unprocessable", "bad"],
  ["pending", "idle"], ["processing", "run"], ["publishing", "run"],
] as const;
const REASONS = ["protected", "covered", "duplicate", "network", "download", "unreadable", "resources", "source_changed", "unsupported"] as const;

/** What every state and every reason on the room page means, and what to do about it (requirements v2, U-6). */
export function StateHelp() {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  return (
    <>
      <button className="fx-a fx-tiny" onClick={() => setOpen(true)} aria-haspopup="dialog">{t("pages.distill.help.open")}</button>
      <Modal open={open} onCancel={() => setOpen(false)} footer={null} width={640} title={t("pages.distill.help.title")}>
        <div className="fx-stack" style={{ gap: 14 }}>
          <table className="fx-t">
            <thead>
              <tr><th style={{ width: 150 }}>{t("pages.distill.help.state")}</th><th>{t("pages.distill.help.means")}</th><th>{t("pages.distill.help.do")}</th></tr>
            </thead>
            <tbody>
              {STATES.map(([s, tone]) => (
                <tr key={s}>
                  <td><Pill tone={tone}>{t(`pages.distill.state.${s}`)}</Pill></td>
                  <td className="fx-tiny">{t(`pages.distill.help.s.${s}.means`)}</td>
                  <td className="fx-tiny">{t(`pages.distill.help.s.${s}.do`)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div>
            <h3 className="fx-h3" style={{ marginBottom: 6 }}>{t("pages.distill.help.reasons")}</h3>
            <dl className="fx-stack fx-tiny" style={{ gap: 8, margin: 0 }}>
              {REASONS.map((r) => (
                <div key={r}>
                  <dt style={{ fontWeight: 600 }}>{r === "covered" ? t("pages.distill.help.covered") : t(`pages.distill.reason.${r}`, { defaultValue: r })}</dt>
                  <dd style={{ margin: 0 }} className="fx-muted">{t(`pages.distill.reasonLong.${r}`)}</dd>
                </div>
              ))}
            </dl>
          </div>
        </div>
      </Modal>
    </>
  );
}
