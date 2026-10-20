/**
 * A stand-in for `@/components/ui/select` in jsdom tests: Radix Select needs pointer-capture
 * and layout APIs jsdom lacks, so it is replaced by a native <select>. Use it as
 *
 *   vi.mock("@/components/ui/select", () => import("@/test/native-select-mock"));
 *
 * The trigger's `id` lands on the <select> (so `getByLabelText` works) and the value
 * placeholder becomes a disabled empty option. This tests what the component does with the
 * control, not Radix itself; check the real control in a browser pass.
 */
import { Children, isValidElement } from "react";
import type { ReactElement, ReactNode } from "react";

interface SelectProps {
  value?: string;
  onValueChange?: (value: string) => void;
  disabled?: boolean;
  children?: ReactNode;
}

interface TriggerProps {
  id?: string;
  children?: ReactNode;
}

// Markers only: `Select` reads their props (id, placeholder) and renders them itself.
export const SelectTrigger: (props: TriggerProps) => null = () => null;
export const SelectValue: (props: { placeholder?: string }) => null = () => null;

export function SelectContent({ children }: { children?: ReactNode }) {
  return <>{children}</>;
}

export function SelectItem({
  value,
  disabled,
  children,
}: {
  value: string;
  disabled?: boolean;
  children?: ReactNode;
}) {
  return (
    <option value={value} disabled={disabled}>
      {children}
    </option>
  );
}

function findTrigger(children: ReactNode): ReactElement<TriggerProps> | undefined {
  return Children.toArray(children).find(
    (child): child is ReactElement<TriggerProps> =>
      isValidElement(child) && child.type === SelectTrigger,
  );
}

function placeholderOf(trigger: ReactElement<TriggerProps> | undefined): string | undefined {
  const inner = Children.toArray(trigger?.props.children).find(
    (child): child is ReactElement<{ placeholder?: string }> =>
      isValidElement(child) && child.type === SelectValue,
  );
  return inner?.props.placeholder;
}

export function Select({ value, onValueChange, disabled, children }: SelectProps) {
  const trigger = findTrigger(children);
  const placeholder = placeholderOf(trigger);
  return (
    <select
      id={trigger?.props.id}
      value={value ?? ""}
      disabled={disabled}
      onChange={(event) => onValueChange?.(event.target.value)}
    >
      {placeholder !== undefined ? (
        <option value="" disabled>
          {placeholder}
        </option>
      ) : null}
      {children}
    </select>
  );
}
