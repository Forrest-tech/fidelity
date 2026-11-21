import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Alert, Breadcrumb, Button, Empty, Modal, Spin } from "antd";
import { FolderOutlined, RightOutlined } from "@ant-design/icons";
import { api } from "../net/client";

interface Listing {
  path: string;
  folders: { name: string; path: string }[];
}

/** The folder a typed value points into, when it is a path in the account (links are browsed from the top). */
const startAt = (v: string) => (v.trim().startsWith("/") ? v.trim().replace(/\/+$/, "") || "/" : "/");

/** Browse the connected Dropbox account one level at a time and pick a folder. */
export function DropboxFolderPicker({
  open,
  title,
  value,
  warn,
  onPick,
  onClose,
}: {
  open: boolean;
  title: string;
  value: string;
  /** a reason the folder shown cannot be chosen, if any */
  warn?: (path: string) => string | null;
  onPick: (path: string) => void;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const [path, setPath] = useState(startAt(value));
  useEffect(() => {
    if (open) setPath(startAt(value));
  }, [open]); // eslint-disable-line react-hooks/exhaustive-deps
  const list = useQuery({
    queryKey: ["folders", path],
    queryFn: () => api<Listing>(`/folders?path=${encodeURIComponent(path)}`),
    enabled: open,
    retry: false,
  });
  // a typed folder that does not exist: start from the top instead of showing an error
  useEffect(() => {
    if (list.isError && path !== "/" && path === startAt(value)) setPath("/");
  }, [list.isError]); // eslint-disable-line react-hooks/exhaustive-deps

  const shown = list.data?.path ?? path;
  const parts = shown.split("/").filter(Boolean);
  const problem = shown !== "/" && warn ? warn(shown) : null;
  return (
    <Modal
      open={open}
      title={title}
      onCancel={onClose}
      destroyOnHidden
      footer={[
        <Button key="c" onClick={onClose}>{t("pages.distill.cancel")}</Button>,
        <Button key="ok" type="primary" disabled={shown === "/" || !!problem || !list.data} onClick={() => onPick(shown)}>
          {t("pages.distill.pickThis")}
        </Button>,
      ]}
    >
      <Breadcrumb
        style={{ marginBottom: 8 }}
        items={[
          { title: <a onClick={() => setPath("/")}>Dropbox</a> },
          ...parts.map((p, i) => ({
            title: i === parts.length - 1 ? <strong>{p}</strong> : <a onClick={() => setPath("/" + parts.slice(0, i + 1).join("/"))}>{p}</a>,
          })),
        ]}
      />
      {problem && <Alert type="warning" showIcon title={problem} style={{ marginBottom: 8 }} />}
      {list.isError && <Alert type="error" showIcon title={(list.error as Error).message} />}
      <div style={{ height: 320, overflow: "auto", border: "1px solid var(--ant-color-border-secondary)", borderRadius: 6 }}>
        {list.isLoading ? (
          <div style={{ padding: 24, textAlign: "center" }}>
            <Spin />
          </div>
        ) : list.data && !list.data.folders.length ? (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={t("pages.distill.noSubfolders")} />
        ) : (
          <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
            {(list.data?.folders ?? []).map((f) => (
              <li key={f.path} style={{ borderBottom: "1px solid var(--ant-color-border-secondary)" }}>
                <Button
                  type="text"
                  block
                  style={{ justifyContent: "flex-start", height: 36 }}
                  icon={<FolderOutlined />}
                  onClick={() => setPath(f.path)}
                >
                  <span style={{ flex: 1, textAlign: "start", overflow: "hidden", textOverflow: "ellipsis" }}>{f.name}</span>
                  <RightOutlined style={{ fontSize: 10, opacity: 0.5 }} />
                </Button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </Modal>
  );
}

/** Is `a` the same folder as `b` or inside it (Dropbox paths ignore case)? */
export function isUnder(a: string, b: string): boolean {
  const n = (p: string) => "/" + p.trim().toLowerCase().replace(/^\/+|\/+$/g, "");
  const x = n(a);
  const y = n(b);
  return y === "/" || x === y || x.startsWith(y + "/");
}
