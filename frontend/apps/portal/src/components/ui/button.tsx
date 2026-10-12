import { cva, type VariantProps } from "class-variance-authority";
import { Loader2 } from "lucide-react";
import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from "react";
import { cn } from "@/lib/cn";

export const buttonStyles = cva(
  "inline-flex shrink-0 items-center justify-center gap-2 whitespace-nowrap rounded-md text-label font-semibold transition-colors duration-fast ease-standard disabled:pointer-events-none focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring",
  {
    variants: {
      variant: {
        primary:
          "bg-primary text-primary-foreground hover:bg-primary-hover active:bg-primary-hover disabled:bg-primary-disabled disabled:text-muted-foreground",
        secondary:
          "bg-primary-soft text-primary-soft-foreground hover:bg-primary-soft-hover disabled:bg-muted disabled:text-muted-foreground",
        outline:
          "border-[1.5px] border-input bg-transparent text-foreground hover:bg-muted disabled:text-muted-foreground",
        ghost: "bg-transparent text-primary hover:bg-primary-soft disabled:text-muted-foreground",
        danger: "bg-destructive text-destructive-foreground hover:opacity-90 disabled:opacity-50",
      },
      size: {
        md: "h-control px-4",
        sm: "h-control-dense px-3",
        icon: "h-control w-control",
        "icon-sm": "h-control-dense w-control-dense",
      },
    },
    defaultVariants: { variant: "primary", size: "md" },
  },
);

export interface ButtonProps
  extends ButtonHTMLAttributes<HTMLButtonElement>, VariantProps<typeof buttonStyles> {
  loading?: boolean;
  leading?: ReactNode;
  trailing?: ReactNode;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, loading, leading, trailing, children, disabled, ...props }, ref) => (
    <button
      ref={ref}
      className={cn(buttonStyles({ variant, size }), className)}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      {...props}
    >
      {loading ? (
        <Loader2 className="spin h-5 w-5" aria-hidden />
      ) : (
        <>
          {leading}
          {children}
          {trailing}
        </>
      )}
    </button>
  ),
);
Button.displayName = "Button";
