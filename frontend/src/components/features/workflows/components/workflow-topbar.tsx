"use client";

import { ChevronDown, FilePlus, FolderOpen, FolderCog, LogOut, Play, Save, SaveAll } from "lucide-react";
import { useRouter } from "next/navigation";
import { useCallback } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useAuthStore } from "@/lib/auth-store";

import { useWorkflowBuilderStore } from "../hooks/use-workflow-builder-store";

interface WorkflowTopbarProps {
  onNew: () => void;
  onOpen: () => void;
  onManage: () => void;
  onSave: () => void;
  onSaveAs: () => void;
  onRun: () => void;
}

export function WorkflowTopbar({
  onNew,
  onOpen,
  onManage,
  onSave,
  onSaveAs,
  onRun,
}: WorkflowTopbarProps) {
  const router = useRouter();
  const user = useAuthStore((state) => state.user);
  const logout = useAuthStore((state) => state.logout);
  const workflowName = useWorkflowBuilderStore((state) => state.workflowName);
  const workflowStatus = useWorkflowBuilderStore(
    (state) => state.workflowStatus,
  );
  const isDirty = useWorkflowBuilderStore((state) => state.isDirty);
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
          <h1 className="text-sm font-semibold">
            {workflowName}
            {isDirty ? <span className="ml-1 text-muted-foreground">●</span> : null}
          </h1>
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

        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="outline">
              File
              <ChevronDown className="size-4" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuItem onSelect={onNew}>
              <FilePlus className="size-4" />
              New
            </DropdownMenuItem>
            <DropdownMenuItem onSelect={onOpen}>
              <FolderOpen className="size-4" />
              Open…
            </DropdownMenuItem>
            <DropdownMenuItem onSelect={onManage}>
              <FolderCog className="size-4" />
              Manage…
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem onSelect={onSave}>
              <Save className="size-4" />
              Save
            </DropdownMenuItem>
            <DropdownMenuItem onSelect={onSaveAs}>
              <SaveAll className="size-4" />
              Save As…
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>

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
