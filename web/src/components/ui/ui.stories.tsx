import type { Meta, StoryObj } from "@storybook/react";
import { Button, Card, EmptyState, ErrorState, Loading, PageHeader } from "./index";
import { StatusBadge } from "../../pages/JobsPage";

const meta: Meta = { title: "Design system/Components" };
export default meta;
type S = StoryObj;

export const Buttons: S = {
  render: () => (
    <div className="flex flex-wrap gap-3">
      <Button>Primary</Button>
      <Button variant="ghost">Ghost</Button>
      <Button variant="danger">Danger</Button>
      <Button disabled>Disabled</Button>
    </div>
  ),
};

export const StatusBadges: S = {
  render: () => (
    <div className="flex flex-wrap gap-2">
      {["queued", "running", "done", "error", "PASS", "FAIL", "SKIP", "METADATA"].map((s) => (
        <StatusBadge key={s} status={s} />
      ))}
    </div>
  ),
};

export const CardWithHeader: S = {
  render: () => (
    <Card>
      <PageHeader title="Page title" />
      <p className="text-sm text-fg-muted">Card content in the muted text colour.</p>
    </Card>
  ),
};

export const LoadingState: S = { render: () => <Loading /> };

export const EmptyStateWithHint: S = {
  render: () => <EmptyState title="No sources configured." hint="A source is a folder of original documents (read-only)." />,
};

export const EmptyStateWithAction: S = {
  render: () => <EmptyState title="No jobs have run yet." action={<Button>Start a job</Button>} />,
};

export const ErrorStateWithRetry: S = {
  render: () => <ErrorState message="The server did not respond." onRetry={() => undefined} />,
};
