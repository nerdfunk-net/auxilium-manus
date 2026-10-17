"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

import { useToast } from "@/hooks/use-toast";

import { useTemplateMutations } from "../hooks/use-template-mutations";
import { useTemplateQuery } from "../hooks/use-template-query";
import { REPORT_CATEGORY, REPORT_TEMPLATE_STARTER } from "./constants";

/** State and save logic of the report template editor (`/templates/report-editor[?id=]`). */
export function useReportTemplateEditor() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { toast } = useToast();
  const idParam = searchParams.get("id");
  const initialId = idParam ? Number(idParam) : null;
  const [templateId, setTemplateId] = useState<number | null>(initialId);
  const isEditMode = templateId !== null;

  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [content, setContent] = useState(initialId === null ? REPORT_TEMPLATE_STARTER : "");

  const query = useTemplateQuery({ templateId, enabled: isEditMode });
  const loadedRef = useRef(false);
  const fetched = query.data;
  const loaded = fetched?.category === REPORT_CATEGORY ? fetched : undefined;
  useEffect(() => {
    if (!isEditMode || loadedRef.current || !loaded) return;
    loadedRef.current = true;
    setName(loaded.name);
    setDescription(loaded.description ?? "");
    setContent(loaded.content);
  }, [isEditMode, loaded]);

  // Saving a device template here would turn it into a report template.
  const deviceTemplateId = fetched && fetched.category !== REPORT_CATEGORY ? fetched.id : null;
  useEffect(() => {
    if (deviceTemplateId !== null) {
      router.replace(`/templates/editor?id=${deviceTemplateId}`);
    }
  }, [deviceTemplateId, router]);

  const { createTemplate, updateTemplate } = useTemplateMutations();
  const isSaving = createTemplate.isPending || updateTemplate.isPending;

  const save = useCallback(() => {
    if (!name.trim()) {
      toast({ title: "Name required", description: "Give the template a name.", variant: "destructive" });
      return;
    }
    const payload = {
      name: name.trim(),
      description: description.trim() === "" ? null : description.trim(),
      template_type: "jinja2",
      category: REPORT_CATEGORY,
      content,
      variables: {},
      pre_run_commands: [],
      pre_run_use_textfsm: false,
      nautobot_attributes: [],
    };
    if (templateId !== null) {
      updateTemplate.mutate({ templateId, payload });
    } else {
      createTemplate.mutate(payload, {
        // Stay on the page after the first save, now editing the stored template.
        onSuccess: (created) => {
          loadedRef.current = true;
          setTemplateId(created.id);
          router.replace(`/templates/report-editor?id=${created.id}`);
        },
      });
    }
  }, [content, createTemplate, description, name, router, templateId, toast, updateTemplate]);

  return {
    router,
    templateId,
    isEditMode,
    isLoading: isEditMode && query.isLoading,
    loadError: query.isError ? query.error.message : null,
    isSaving,
    name,
    setName,
    description,
    setDescription,
    content,
    setContent,
    save,
  };
}
