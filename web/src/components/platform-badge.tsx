import { platformColors } from "@fm/shared";

export function PlatformBadge({ platform }: { platform: string }) {
  const color = platformColors[platform.toLowerCase()] ?? "#6b7280";
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-border px-2 py-0.5 text-xs font-medium capitalize">
      <span className="h-2 w-2 rounded-full" style={{ background: color }} aria-hidden />
      {platform}
    </span>
  );
}
