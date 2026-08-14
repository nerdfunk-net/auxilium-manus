"use client";

import { ArrowLeft, KeyRound, Loader2, RefreshCw, Trash2, Upload } from "lucide-react";
import Link from "next/link";
import { useRef, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import {
  useCertificatesMutations,
  type AddCertificateResult,
} from "@/hooks/queries/use-certificates-mutations";
import { useCertificatesQuery } from "@/hooks/queries/use-certificates-query";
import { useAuthStore } from "@/lib/auth-store";
import { hasPermission } from "@/lib/permissions";

import { AddToSystemResultDialog } from "./dialogs/add-to-system-result-dialog";
import { DeleteCertificateDialog } from "./dialogs/delete-certificate-dialog";

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const kb = bytes / 1024;
  if (kb < 1024) return `${kb.toFixed(1)} KB`;
  return `${(kb / 1024).toFixed(1)} MB`;
}

export function AddCertificatePage() {
  const user = useAuthStore((state) => state.user);
  const canWrite = hasPermission(user, "system.certificates", "write");

  const { data, isLoading, isFetching, refetch } = useCertificatesQuery();
  const { uploadCertificate, addCertificatesToSystem, deleteCertificate } =
    useCertificatesMutations();

  const fileInputRef = useRef<HTMLInputElement>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null);
  const [addResults, setAddResults] = useState<AddCertificateResult[] | null>(null);

  const certificates = data?.certificates ?? [];
  const notInstalled = certificates.filter((c) => !c.exists_in_system);

  const toggleSelected = (filename: string, checked: boolean) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (checked) {
        next.add(filename);
      } else {
        next.delete(filename);
      }
      return next;
    });
  };

  const toggleSelectAll = (checked: boolean) => {
    setSelected(checked ? new Set(notInstalled.map((c) => c.filename)) : new Set());
  };

  const handleUploadClick = () => fileInputRef.current?.click();

  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (file) {
      await uploadCertificate.mutateAsync(file);
    }
  };

  const handleAddToSystem = async () => {
    const results = await addCertificatesToSystem.mutateAsync(Array.from(selected));
    setAddResults(results);
    setSelected(new Set());
  };

  return (
    <div className="mx-auto w-full max-w-4xl space-y-6 p-8">
      <div className="flex items-center gap-3">
        <Button variant="ghost" size="icon" asChild>
          <Link href="/tools">
            <ArrowLeft className="size-4" />
          </Link>
        </Button>
        <div className="flex size-10 items-center justify-center rounded-lg bg-muted">
          <KeyRound className="size-5 text-muted-foreground" />
        </div>
        <div className="flex-1">
          <h1 className="text-xl font-semibold">Certificate Manager</h1>
          <p className="text-sm text-muted-foreground">
            Upload and install CA certificates into the system trust store.
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={() => refetch()} disabled={isFetching}>
          {isFetching ? (
            <Loader2 className="mr-2 size-4 animate-spin" />
          ) : (
            <RefreshCw className="mr-2 size-4" />
          )}
          Scan
        </Button>
        <input
          ref={fileInputRef}
          type="file"
          accept=".crt"
          className="hidden"
          onChange={handleFileChange}
        />
        <Button
          size="sm"
          disabled={!canWrite || uploadCertificate.isPending}
          onClick={handleUploadClick}
        >
          <Upload className="mr-2 size-4" />
          Upload Certificate
        </Button>
      </div>

      {data && (
        <p className="text-xs text-muted-foreground">
          Scanning <code>{data.certs_directory}</code>
        </p>
      )}

      <Card>
        <CardHeader className="flex flex-row items-center justify-between pb-3">
          <CardTitle className="text-base">Certificates</CardTitle>
          {selected.size > 0 && (
            <Button
              size="sm"
              disabled={!canWrite || addCertificatesToSystem.isPending}
              onClick={handleAddToSystem}
            >
              {addCertificatesToSystem.isPending && (
                <Loader2 className="mr-2 size-4 animate-spin" />
              )}
              Add {selected.size} to System CA
            </Button>
          )}
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <p className="text-sm text-muted-foreground">Loading certificates…</p>
          ) : certificates.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              No .crt files found. Upload one to get started.
            </p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-8">
                    <Checkbox
                      checked={notInstalled.length > 0 && selected.size === notInstalled.length}
                      onCheckedChange={(checked) => toggleSelectAll(checked === true)}
                      disabled={notInstalled.length === 0}
                    />
                  </TableHead>
                  <TableHead>Filename</TableHead>
                  <TableHead>Size</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead className="w-8" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {certificates.map((cert) => (
                  <TableRow key={cert.filename}>
                    <TableCell>
                      <Checkbox
                        checked={selected.has(cert.filename)}
                        disabled={cert.exists_in_system}
                        onCheckedChange={(checked) =>
                          toggleSelected(cert.filename, checked === true)
                        }
                      />
                    </TableCell>
                    <TableCell className="font-mono text-xs">{cert.filename}</TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {formatBytes(cert.size)}
                    </TableCell>
                    <TableCell>
                      {cert.exists_in_system ? (
                        <Badge className="bg-success-foreground hover:bg-success-foreground">In System CA</Badge>
                      ) : (
                        <Badge variant="secondary" className="text-warning-foreground">
                          Not in System
                        </Badge>
                      )}
                    </TableCell>
                    <TableCell>
                      <Button
                        variant="ghost"
                        size="icon"
                        disabled={!canWrite}
                        onClick={() => setDeleteTarget(cert.filename)}
                      >
                        <Trash2 className="size-4" />
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardContent className="pt-6 text-sm text-muted-foreground">
          Certificates must be PEM-encoded <code>.crt</code> files. Adding a certificate to the
          system CA store requires root/sudo privileges on the server — it copies the file to{" "}
          <code>/usr/local/share/ca-certificates/</code> and runs <code>update-ca-certificates</code>.
        </CardContent>
      </Card>

      <DeleteCertificateDialog
        open={deleteTarget !== null}
        filename={deleteTarget}
        isDeleting={deleteCertificate.isPending}
        onClose={() => setDeleteTarget(null)}
        onConfirm={async () => {
          if (deleteTarget) {
            await deleteCertificate.mutateAsync(deleteTarget);
            setDeleteTarget(null);
          }
        }}
      />

      <AddToSystemResultDialog
        open={addResults !== null}
        results={addResults ?? []}
        onClose={() => setAddResults(null)}
      />
    </div>
  );
}
