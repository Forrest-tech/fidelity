import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { api, json } from "../net/client";
import { useAuth } from "../auth/AuthProvider";
import { Alert, Button, Card, Col, Row, Space, Typography } from "antd";
import { FolderOpenOutlined, UploadOutlined } from "@ant-design/icons";
import { EmptyState, ErrorState, Loading, PageHeader } from "../components/ui";
import { DropboxSync } from "../components/DropboxSync";

interface SourceRow {
  id: string;
  name: string;
  src_root: string;
  /** false when the folder does not exist on the server */
  available?: boolean;
  md_root: string;
  enabled?: boolean;
}

function SourceCard({ s, canEdit }: { s: SourceRow; canEdit: boolean }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const file = useRef<HTMLInputElement>(null);
  const [msg, setMsg] = useState("");
  const batch = useMutation({
    mutationFn: () => api<{ files: number }>("/distill/batch", json({ sid: s.id })),
    onSuccess: (r) => {
      setMsg(t("pages.sources.started", { count: r.files }));
      void qc.invalidateQueries({ queryKey: ["jobs"] });
    },
    onError: (e: Error) => setMsg(e.message),
  });
  const upload = useMutation({
    mutationFn: async (f: File) => {
      const fd = new FormData();
      fd.append("file", f);
      return api<{ rel: string }>(`/ingest/upload?sid=${encodeURIComponent(s.id)}&distill=true`, { method: "POST", body: fd });
    },
    onSuccess: (r) => {
      setMsg(t("pages.sources.uploaded", { name: r.rel }));
      void qc.invalidateQueries({ queryKey: ["jobs"] });
    },
    onError: (e: Error) => setMsg(e.message),
  });
  return (
    <Card size="small" title={<Space><FolderOpenOutlined />{s.name}</Space>}>
      <Space orientation="vertical" size={8} style={{ width: "100%" }}>
        <Typography.Text type="secondary" style={{ wordBreak: "break-all" }}>{s.src_root}</Typography.Text>
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>{t("pages.sources.readOnly")}</Typography.Text>
        {s.available === false && <Alert type="warning" showIcon title={t("pages.sources.missing")} />}
        {canEdit && s.available !== false && (
          <Space wrap>
            <Button type="primary" onClick={() => batch.mutate()} loading={batch.isPending}>
              {t("pages.sources.distillAll")}
            </Button>
            <Button icon={<UploadOutlined />} onClick={() => file.current?.click()} disabled={upload.isPending}>
              {t("pages.sources.upload")}
            </Button>
            <input
              ref={file}
              type="file"
              accept="application/pdf,.pdf"
              hidden
              aria-label={t("pages.sources.upload")}
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) upload.mutate(f);
                e.target.value = "";
              }}
            />
          </Space>
        )}
        {msg && <p role="status">{msg}</p>}
      </Space>
    </Card>
  );
}

export function SourcesPage() {
  const { t } = useTranslation();
  const { me } = useAuth();
  const q = useQuery({ queryKey: ["sources"], queryFn: () => api<SourceRow[]>("/sources") });
  const canEdit = me?.role === "reviewer" || me?.role === "admin";
  return (
    <>
      <PageHeader title={t("pages.sources.title")} />
      <DropboxSync canEdit={canEdit} isAdmin={me?.role === "admin"} />
      <Typography.Title level={4}>{t("pages.sources.local")}</Typography.Title>
      {q.isLoading && <Loading />}
      {q.isError && <ErrorState message={(q.error as Error).message} onRetry={() => void q.refetch()} />}
      {q.data && q.data.length === 0 && <EmptyState title={t("pages.sources.empty")} hint={t("pages.sources.emptyHint")} />}
      {q.data && q.data.length > 0 && (
        <Row gutter={[16, 16]}>
          {q.data.map((s) => (
            <Col key={s.id} xs={24} md={12}>
              <SourceCard s={s} canEdit={canEdit} />
            </Col>
          ))}
        </Row>
      )}
    </>
  );
}
