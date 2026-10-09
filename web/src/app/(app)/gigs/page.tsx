import { EmptyState } from "@/components/ui/card";

export default function Page() {
  return (
    <div className="mx-auto max-w-5xl space-y-4">
      <h1 className="text-2xl font-bold">Gigs</h1>
      <EmptyState title="Coming in a later phase" hint="This module is scaffolded in the navigation and will be built in an upcoming phase." />
    </div>
  );
}
