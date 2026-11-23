import { cn } from "@/lib/utils";

export function Skeleton({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("animate-pulse rounded-md bg-muted", className)} {...props} />;
}

export function Alert({
  variant = "default",
  className,
  children,
}: {
  variant?: "default" | "destructive" | "success";
  className?: string;
  children: React.ReactNode;
}) {
  const styles =
    variant === "destructive"
      ? "border-red-200 bg-red-50 text-red-800"
      : variant === "success"
        ? "border-emerald-200 bg-emerald-50 text-emerald-800"
        : "border-border bg-muted/60 text-foreground";
  return (
    <div role="alert" className={cn("rounded-lg border px-4 py-3 text-sm", styles, className)}>
      {children}
    </div>
  );
}
