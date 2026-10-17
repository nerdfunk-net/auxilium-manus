import { z } from "zod";

export const workflowImportSchema = z.object({
  name: z.string().min(1, "Name is required").max(255),
  description: z.string().max(2000).optional(),
  folder: z.string().max(500).optional(),
  visibility: z.enum(["public", "private"]),
});

export type WorkflowImportFormValues = z.infer<typeof workflowImportSchema>;
