import { cn } from "@/lib/utils";

/**
 * Skeleton placeholder component for loading states.
 *
 * Renders a pulsing grey block that can stand in for text, images, or other
 * content while data is being fetched.
 *
 * @example
 * // Product card loading state
 * <Skeleton className="h-48 w-full rounded-lg" />
 * <Skeleton className="mt-2 h-4 w-3/4" />
 * <Skeleton className="mt-1 h-4 w-1/2" />
 */
function Skeleton({
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn("animate-pulse rounded-md bg-muted", className)}
      aria-hidden="true"
      {...props}
    />
  );
}

export { Skeleton };
