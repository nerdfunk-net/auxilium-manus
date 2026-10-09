import { Badge } from "@/components/ui/badge";

interface FieldHeaderProps {
  name: string;
  type: string;
}

/** The monospace "field_name [type]" caption used above every step-config field. */
export function FieldHeader({ name, type }: FieldHeaderProps) {
  return (
    <div className="flex items-center gap-1.5">
      <span className="font-mono text-xs font-medium">{name}</span>
      <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
        {type}
      </Badge>
    </div>
  );
}
