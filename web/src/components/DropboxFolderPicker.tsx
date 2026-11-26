import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Alert, Breadcrumb, Button, Divider, Empty, Input, Modal, Spin } from "antd";
import { FolderOutlined, RightOutlined } from "@ant-design/icons";
import { api } from "../net/client";

interface LinkInfo {
  link: string;
  name: string;
  in_account: boolean;
  path: string | null;
  files: number;
  supported: number;
  size_mb: number;
  complete: boolean;
}

/** The server answers "code: message"; a known code is shown in the person's language. */
const LINK_ERRORS = ["not_link", "file_link", "no_rlkey", "not_connected", "gone", "list_failed"];
function linkError(t: (k: string) => string, msg: string) {
  const code = msg.split(":")[0].trim();
  return LINK_ERRORS.includes(code) ? t(`pages.distill.link.err.${code}`) : msg;
}

/** A shared link from someone else's Dropbox: checked (read-only) before it is used as the input. */
function SharedLink({ initial, onPick }: { initial: string; onPick: (link: string) => void }) {
  const { t } = useTranslation();
  const [url, setUrl] = useState(initial.startsWith("http") ? initial : "");
  const [asked, setAsked] = useState("");
  const check = useQuery({
    queryKey: ["shared-link", asked],
    queryFn: () => api<LinkInfo>(`/folders/link?url=${encodeURIComponent(asked)}`),
    enabled: !!asked,
    retry: false,
  });
  const info = check.data;
  return (
    <div className="fx-stack" style={{ gap: 6 }}>
      <label className="fx-tiny fx-muted" htmlFor="shared-link">{t("pages.distill.link.hint")}</label>
      <Input.Search
        id="shared-link"
        value={url}
        onChange={(e) => setUrl(e.target.value)}
        onSearch={(v) => setAsked(v.trim())}
        enterButton={t("pages.distill.link.check")}
        placeholder="https://www.dropbox.com/scl/fo/…"
        loading={check.isFetching}
        allowClear
      />
      {check.isFetching && <div className="fx-tiny fx-muted">{t("pages.distill.link.counting")}</div>}
      {check.isError && <Alert type="error" showIcon title={linkError(t, (check.error as Error).message)} />}
      {info && !check.isFetching && (
        <Alert
          type="success"
          showIcon
          title={t("pages.distill.link.found", { name: info.name })}
          description={
            <>
              <div>{t(info.complete ? "pages.distill.link.counts" : "pages.distill.link.countsAtLeast", { files: info.files, supported: info.supported, mb: info.size_mb })}</div>
              <div className="fx-tiny fx-muted">{info.in_account ? t("pages.distill.link.inAccount", { path: info.path }) : t("pages.distill.link.external")}</div>
              <Button type="primary" size="small" style={{ marginTop: 6 }} onClick={() => onPick(info.link)}>{t("pages.distill.link.use")}</Button>
            </>
          }
        />
      )}
    </div>
  );
}

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
  allowLink,
  allowNew,
  onPick,
  onClose,
}: {
  open: boolean;
  title: string;
  value: string;
  /** a reason the folder shown cannot be chosen, if any */
  warn?: (path: string) => string | null;
  /** the input may also be a shared link from another Dropbox account (the output never: it must be writable) */
  allowLink?: boolean;
  /** the output may be a new folder: it is made by the first publish */
  allowNew?: boolean;
  onPick: (path: string) => void;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const [path, setPath] = useState(startAt(value));
  const [newName, setNewName] = useState("");
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
      {allowLink && (
        <>
          <SharedLink initial={value} onPick={onPick} />
          <Divider plain style={{ margin: "12px 0" }}>{t("pages.distill.link.orBrowse")}</Divider>
        </>
      )}
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
      {allowNew && list.data && (
        <div style={{ marginTop: 10 }}>
          <label className="fx-tiny fx-muted" htmlFor="new-folder">{t("pages.distill.newFolder.label", { where: shown })}</label>
          <Input.Search
            id="new-folder"
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            enterButton={t("pages.distill.newFolder.use")}
            placeholder={t("pages.distill.newFolder.placeholder")}
            onSearch={(v) => {
              const name = v.trim().replace(/[\/]+/g, " ");
              if (name) onPick((shown === "/" ? "" : shown) + "/" + name);
            }}
          />
        </div>
      )}
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
