"use client";

import { LogOut, Play, Save } from "lucide-react";
import { useRouter } from "next/navigation";
import { useCallback } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useAuthStore } from "@/lib/auth-store";

import { useWorkflowBuilderStore } from "../hooks/use-workflow-builder-store";

interface WorkflowTopbarProps {
  onSave: () => void;
  onRun: () => void;
}

export function WorkflowTopbar({ onSave, onRun }: WorkflowTopbarProps) {
  const router = useRouter();
  const user = useAuthStore((state) => state.user);
  const logout = useAuthStore((state) => state.logout);
  const workflowName = useWorkflowBuilderStore((state) => state.workflowName);
  const workflowStatus = useWorkflowBuilderStore(
    (state) => state.workflowStatus,
  );
  const mode = useWorkflowBuilderStore((state) => state.mode);
  const setMode = useWorkflowBuilderStore((state) => state.setMode);
  const handleLogout = useCallback(async () => {
    await logout();
    router.replace("/login");
    router.refresh();
  }, [logout, router]);

  return (
    <header className="flex h-16 items-center justify-between border-b bg-card px-5">
      <div className="flex items-center gap-4">
        <div>
          <h1 className="text-sm font-semibold">{workflowName}</h1>
          <p className="text-xs text-muted-foreground">
            Select devices, run commands, and store artifacts.
          </p>
        </div>
        <Badge
          variant={
            workflowStatus === "Error"
              ? "destructive"
              : workflowStatus === "Running"
                ? "default"
                : "outline"
          }
        >
          {workflowStatus}
        </Badge>
      </div>

      <div className="flex items-center gap-3">
        {user ? (
          <span className="text-xs text-muted-foreground">{user.username}</span>
        ) : null}
        <Tabs value={mode} onValueChange={(value) => setMode(value as typeof mode)}>
          <TabsList>
            <TabsTrigger value="editor">Editor</TabsTrigger>
            <TabsTrigger value="executions">Executions</TabsTrigger>
          </TabsList>
        </Tabs>
        <Button variant="outline" onClick={onSave}>
          <Save className="size-4" />
          Save
        </Button>
        <Button onClick={onRun}>
          <Play className="size-4" />
          Run
        </Button>
        <Button
          aria-label="Sign out"
          onClick={handleLogout}
          size="icon"
          variant="ghost"
        >
          <LogOut className="size-4" />
        </Button>
      </div>
    </header>
  );
}
