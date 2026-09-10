import {
  CheckCircle2,
  CircleDot,
  Clock,
  Loader2,
  ThumbsUp,
  XCircle,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";

import type { ChangeRequestStatus } from "../types/change-request";

const STATUS_META: Record<
  ChangeRequestStatus,
  { label: string; className: string; Icon: typeof CheckCircle2; spin?: boolean }
> = {
  staged: { label: "Staged", className: "text-warning-foreground", Icon: CircleDot },
  approved: { label: "Approved", className: "text-step", Icon: ThumbsUp },
  deploying: { label: "Deploying", className: "text-step", Icon: Loader2, spin: true },
  deployed: { label: "Deployed", className: "text-success-foreground", Icon: CheckCircle2 },
  failed: { label: "Failed", className: "text-destructive", Icon: XCircle },
  rejected: { label: "Rejected", className: "text-muted-foreground", Icon: XCircle },
  expired: { label: "Expired", className: "text-muted-foreground", Icon: Clock },
};

export function ChangeRequestStatusBadge({ status }: { status: ChangeRequestStatus }) {
  const meta = STATUS_META[status];
  return (
    <Badge variant="outline" className="gap-1.5">
      <meta.Icon
        className={`size-3.5 ${meta.className} ${meta.spin ? "animate-spin" : ""}`}
        aria-hidden
      />
      {meta.label}
    </Badge>
  );
}
