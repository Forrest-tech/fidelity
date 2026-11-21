import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Alert, Collapse, Drawer, Space, Spin, Tag, Typography, theme } from "antd";
import { api } from "../net/client";

interface Line {
  op: " " | "+" | "-" | "@";
  text: string;
}
interface FileDiff {
  path: string;
  status: "new" | "removed" | "same" | "changed";
  lines: Line[];
  added: number;
  removed: number;
  truncated: boolean;
}
export interface Comparison {
  rel: string;
  dest: string;
  key: string;
  status: "new" | "same" | "changed";
  accuracy: number | null;
  files: FileDiff[];
  added: number;
  removed: number;
  more_files: number;
}

const TONE: Record<FileDiff["status"], string> = { new: "processing", removed: "error", same: "default", changed: "warning" };

function DiffLines({ lines, truncated }: { lines: Line[]; truncated: boolean }) {
  const { t } = useTranslation();
  const { token } = theme.useToken();
  const bg = { "+": token.colorSuccessBg, "-": token.colorErrorBg, "@": token.colorFillSecondary, " ": "transparent" };
  return (
    <div
      role="region"
      aria-label={t("pages.distill.cmp.lines")}
      tabIndex={0}
      style={{
        fontFamily: "ui-monospace, SFMono-Regular, Consolas, monospace",
        fontSize: 12.5,
        lineHeight: "20px",
        maxHeight: "60vh",
        overflow: "auto",
        border: `1px solid ${token.colorBorderSecondary}`,
        borderRadius: 6,
      }}
    >
      {lines.map((l, i) => (
        <div key={i} style={{ display: "flex", background: bg[l.op], color: l.op === "@" ? token.colorTextSecondary : token.colorText }}>
          <span aria-hidden style={{ width: 22, flex: "none", textAlign: "center", userSelect: "none", color: token.colorTextSecondary }}>
            {l.op === "@" ? "" : l.op}
          </span>
          <span style={{ whiteSpace: "pre-wrap", wordBreak: "break-word", paddingRight: 8 }}>
            {l.op === "+" && <span className="sr-only">{t("pages.distill.cmp.added")}: </span>}
            {l.op === "-" && <span className="sr-only">{t("pages.distill.cmp.removedLine")}: </span>}
            {l.op === "@" ? "⋯" : l.text || " "}
          </span>
        </div>
      ))}
      {truncated && (
        <Typography.Text type="secondary" style={{ display: "block", padding: 8, fontFamily: "inherit" }}>
          {t("pages.distill.cmp.truncated")}
        </Typography.Text>
      )}
    </div>
  );
}

/** One file's new result next to the copy in the output folder, line by line. */
export function CompareDrawer({ roomId, rel, onClose }: { roomId: string; rel: string | null; onClose: () => void }) {
  const { t } = useTranslation();
  const q = useQuery({
    queryKey: ["compare", roomId, rel],
    queryFn: () => api<Comparison>(`/rooms/${roomId}/compare?rel=${encodeURIComponent(rel!)}`),
    enabled: !!rel,
    retry: false,
  });
  const c = q.data;
  const name = rel?.split("/").pop() ?? "";
  const shown = c?.files.filter((f) => f.status !== "same") ?? [];
  return (
    <Drawer open={!!rel} onClose={onClose} size="large" title={t("pages.distill.cmp.title", { name })} destroyOnHidden>
      {q.isLoading && <Spin />}
      {q.isError && <Alert type="error" showIcon title={(q.error as Error).message} />}
      {c && (
        <Space orientation="vertical" size={12} style={{ width: "100%" }}>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            {rel} → {c.dest.replace(/\/+$/, "")}/{c.key}
          </Typography.Text>
          <Alert
            type={c.status === "changed" ? "warning" : "info"}
            showIcon
            title={
              c.status === "new"
                ? t("pages.distill.cmp.new")
                : c.status === "same"
                  ? t("pages.distill.cmp.same")
                  : t("pages.distill.cmp.changed", { added: c.added, removed: c.removed })
            }
          />
          {shown.length === 1 && c.files.length === 1 ? (
            <DiffLines lines={shown[0].lines} truncated={shown[0].truncated} />
          ) : (
            shown.length > 0 && (
              <Collapse
                defaultActiveKey={shown.length <= 3 ? shown.map((f) => f.path) : [shown[0].path]}
                items={shown.map((f) => ({
                  key: f.path,
                  label: (
                    <Space size={8}>
                      <span>{f.path}</span>
                      <Tag color={TONE[f.status]}>{t(`pages.distill.cmp.file.${f.status}`)}</Tag>
                      {(f.added > 0 || f.removed > 0) && (
                        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                          +{f.added} −{f.removed}
                        </Typography.Text>
                      )}
                    </Space>
                  ),
                  children: f.lines.length ? <DiffLines lines={f.lines} truncated={f.truncated} /> : <Typography.Text type="secondary">{t("pages.distill.cmp.binary")}</Typography.Text>,
                }))}
              />
            )
          )}
          {c.files.length - shown.length > 0 && c.files.length > 1 && (
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              {t("pages.distill.cmp.sameFiles", { count: c.files.length - shown.length })}
            </Typography.Text>
          )}
          {c.more_files > 0 && (
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              {t("pages.distill.cmp.moreFiles", { count: c.more_files })}
            </Typography.Text>
          )}
        </Space>
      )}
    </Drawer>
  );
}
