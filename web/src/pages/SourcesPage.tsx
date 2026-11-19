import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { api, json } from "../net/client";
import { useAuth } from "../auth/AuthProvider";
import { Button, Card, EmptyState, ErrorState, Loading, PageHeader } from "../components/ui";
import { DropboxSync } from "../components/DropboxSync";

interface SourceRow {
  id: string;
  name: string;
  src_root: string;
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
    <Card className="flex flex-col gap-2">
      <p className="font-medium">{s.name}</p>
      <p className="break-all text-sm text-fg-muted">{s.src_root}</p>
      <p className="text-xs text-fg-muted">{t("pages.sources.readOnly")}</p>
      {canEdit && (
        <div className="flex flex-wrap gap-2">
          <Button onClick={() => batch.mutate()} disabled={batch.isPending}>
            {t("pages.sources.distillAll")}
          </Button>
          <Button variant="ghost" onClick={() => file.current?.click()} disabled={upload.isPending}>
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
        </div>
      )}
      {msg && (
        <p role="status" className="text-sm">
          {msg}
        </p>
      )}
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
      <h2 className="mb-2 font-medium">{t("pages.sources.local")}</h2>
      {q.isLoading && <Loading />}
      {q.isError && <ErrorState message={(q.error as Error).message} onRetry={() => void q.refetch()} />}
      {q.data && q.data.length === 0 && <EmptyState title={t("pages.sources.empty")} hint={t("pages.sources.emptyHint")} />}
      {q.data && q.data.length > 0 && (
        <ul className="grid gap-3 md:grid-cols-2">
          {q.data.map((s) => (
            <li key={s.id}>
              <SourceCard s={s} canEdit={canEdit} />
            </li>
          ))}
        </ul>
      )}
    </>
  );
}
