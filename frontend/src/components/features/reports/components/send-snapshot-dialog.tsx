"use client";

import { Loader2, Send } from "lucide-react";
import { useCallback, useMemo, useState } from "react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { useReportSnapshotSendMutation } from "@/hooks/queries/use-report-snapshot-send-mutation";

import { formatRecipients, MAX_RECIPIENTS, parseRecipients } from "../utils/recipients";

interface SendSnapshotDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  snapshotId: number;
  snapshotName: string;
  /** The report's saved recipients, proposed when the dialog opens. */
  defaultRecipients: readonly string[];
}

/** Mail a stored report: recipients, optional subject and note, with or without the PDF. */
export function SendSnapshotDialog({
  open,
  onOpenChange,
  snapshotId,
  snapshotName,
  defaultRecipients,
}: SendSnapshotDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Send by email</DialogTitle>
          <DialogDescription>{snapshotName}</DialogDescription>
        </DialogHeader>
        {/* Mounted only while the dialog is open, so every opening starts from the defaults. */}
        <SendForm
          snapshotId={snapshotId}
          snapshotName={snapshotName}
          defaultRecipients={defaultRecipients}
          onClose={() => onOpenChange(false)}
        />
      </DialogContent>
    </Dialog>
  );
}

interface SendFormProps {
  snapshotId: number;
  snapshotName: string;
  defaultRecipients: readonly string[];
  onClose: () => void;
}

function SendForm({ snapshotId, snapshotName, defaultRecipients, onClose }: SendFormProps) {
  const send = useReportSnapshotSendMutation();
  const [recipients, setRecipients] = useState(() => formatRecipients(defaultRecipients));
  const [subject, setSubject] = useState("");
  const [message, setMessage] = useState("");
  const [includePdf, setIncludePdf] = useState(true);

  const parsed = useMemo(() => parseRecipients(recipients), [recipients]);
  const problem =
    parsed.invalid.length > 0
      ? `Not an email address: ${parsed.invalid.join(", ")}`
      : parsed.tooMany
        ? `At most ${MAX_RECIPIENTS} recipients`
        : null;
  const canSend = parsed.addresses.length > 0 && problem === null && !send.isPending;

  const handleSend = useCallback(() => {
    send.mutate(
      {
        snapshotId,
        input: {
          to: parsed.addresses,
          subject: subject.trim() === "" ? null : subject.trim(),
          message: message.trim() === "" ? null : message.trim(),
          include_pdf: includePdf,
        },
      },
      { onSuccess: onClose },
    );
  }, [includePdf, message, onClose, parsed.addresses, send, snapshotId, subject]);

  return (
    <>
      <div className="space-y-3">
        <div className="space-y-1.5">
          <Label htmlFor="send-recipients">Recipients</Label>
          <Textarea
            id="send-recipients"
            rows={3}
            placeholder="one address per line, or separated by commas"
            value={recipients}
            onChange={(event) => setRecipients(event.target.value)}
          />
          {problem ? <p className="text-xs text-destructive">{problem}</p> : null}
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="send-subject">Subject (optional)</Label>
          <Input
            id="send-subject"
            placeholder={snapshotName}
            value={subject}
            maxLength={200}
            onChange={(event) => setSubject(event.target.value)}
          />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="send-message">Note above the report (optional)</Label>
          <Textarea
            id="send-message"
            rows={2}
            maxLength={2000}
            value={message}
            onChange={(event) => setMessage(event.target.value)}
          />
        </div>
        <div className="flex items-center gap-2">
          <Checkbox
            id="send-pdf"
            checked={includePdf}
            onCheckedChange={(checked) => setIncludePdf(checked === true)}
          />
          <Label htmlFor="send-pdf" className="text-sm font-normal">
            Attach the report as PDF
          </Label>
        </div>
        {send.isError ? (
          <Alert variant="destructive">
            <AlertDescription>{send.error.message}</AlertDescription>
          </Alert>
        ) : null}
      </div>
      <DialogFooter>
        <Button type="button" variant="outline" onClick={onClose}>
          Cancel
        </Button>
        <Button type="button" onClick={handleSend} disabled={!canSend}>
          {send.isPending ? (
            <Loader2 className="mr-2 size-4 animate-spin" />
          ) : (
            <Send className="mr-2 size-4" />
          )}
          Send
        </Button>
      </DialogFooter>
    </>
  );
}
