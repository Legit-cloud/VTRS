import { AlertCircle } from "lucide-react";
import {
  forwardRef,
  useId,
  type InputHTMLAttributes,
  type ReactNode,
  type SelectHTMLAttributes,
  type TextareaHTMLAttributes,
} from "react";
import { cn } from "@/lib/cn";

const control =
  "w-full rounded-md border-[1.5px] border-input bg-input-fill px-3 text-body text-foreground placeholder:text-muted-foreground focus-visible:border-primary focus-visible:shadow-focus focus-visible:outline-none disabled:cursor-not-allowed disabled:opacity-60 aria-[invalid=true]:border-destructive";

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(
  ({ className, ...props }, ref) => (
    <input ref={ref} className={cn(control, "h-control", className)} {...props} />
  ),
);
Input.displayName = "Input";

export const Textarea = forwardRef<
  HTMLTextAreaElement,
  TextareaHTMLAttributes<HTMLTextAreaElement>
>(({ className, ...props }, ref) => (
  <textarea ref={ref} className={cn(control, "min-h-24 py-2", className)} {...props} />
));
Textarea.displayName = "Textarea";

export const Select = forwardRef<HTMLSelectElement, SelectHTMLAttributes<HTMLSelectElement>>(
  ({ className, children, ...props }, ref) => (
    <select ref={ref} className={cn(control, "h-control pr-8", className)} {...props}>
      {children}
    </select>
  ),
);
Select.displayName = "Select";

interface FieldProps {
  label: string;
  hint?: string;
  error?: string | null;
  children: (props: {
    id: string;
    "aria-invalid"?: boolean;
    "aria-describedby"?: string;
  }) => ReactNode;
  className?: string;
}

/** Label above, helper below, error with an icon and a fix. */
export function Field({ label, hint, error, children, className }: FieldProps) {
  const id = useId();
  const describedBy = error ? `${id}-error` : hint ? `${id}-hint` : undefined;
  return (
    <div className={cn("flex flex-col gap-1", className)}>
      <label htmlFor={id} className="text-label text-strong-foreground">
        {label}
      </label>
      {children({
        id,
        "aria-invalid": error ? true : undefined,
        "aria-describedby": describedBy,
      })}
      {error ? (
        <p id={`${id}-error`} className="flex items-center gap-1 text-caption text-signal-red-text">
          <AlertCircle className="h-4 w-4 shrink-0" aria-hidden />
          {error}
        </p>
      ) : hint ? (
        <p id={`${id}-hint`} className="text-caption text-subtle-foreground">
          {hint}
        </p>
      ) : null}
    </div>
  );
}
