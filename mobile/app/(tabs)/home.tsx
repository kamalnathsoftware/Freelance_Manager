import { useQuery } from "@tanstack/react-query";
import { RefreshControl, ScrollView, Text, View } from "react-native";
import { api } from "@/api";

const money = (n: number, c: string) => `${c} ${Math.round(n).toLocaleString()}`;

export default function Home() {
  const me = useQuery({ queryKey: ["me"], queryFn: api.me });
  const ov = useQuery({ queryKey: ["analytics", 30], queryFn: () => api.analytics(30) });
  const brief = useQuery({ queryKey: ["briefing"], queryFn: () => api.briefing(false) });
  const unread = useQuery({ queryKey: ["unread"], queryFn: api.unreadCounts });
  const k = ov.data?.kpis;
  const cards: [string, string][] = [
    ["Unread", String(unread.data?.total ?? 0)],
    ["Active orders", String(k?.active_orders ?? 0)],
    ["Win rate", k ? `${Math.round(k.win_rate * 100)}%` : "-"],
    ["Net (30d)", k ? money(k.net_earnings, ov.data!.currency) : "-"],
  ];
  const refreshing = me.isFetching || ov.isFetching || brief.isFetching;
  const refetch = () => { me.refetch(); ov.refetch(); brief.refetch(); unread.refetch(); };
  return (
    <ScrollView className="flex-1 bg-zinc-50 dark:bg-zinc-950" contentContainerClassName="gap-4 p-4" refreshControl={<RefreshControl refreshing={refreshing} onRefresh={refetch} />}>
      <Text accessibilityRole="header" className="text-xl font-bold text-zinc-900 dark:text-white">Hi {me.data?.full_name || "there"} 👋</Text>
      {brief.data && <Text className="text-sm text-zinc-600 dark:text-zinc-300">{brief.data.headline}</Text>}
      <View className="flex-row flex-wrap gap-3">
        {cards.map(([label, value]) => (
          <View key={label} accessible accessibilityLabel={`${label}: ${value}`} className="w-[48%] rounded-2xl bg-white p-4 dark:bg-zinc-900">
            <Text className="text-xs text-zinc-500">{label}</Text>
            <Text className="text-2xl font-bold text-zinc-900 dark:text-white">{value}</Text>
          </View>
        ))}
      </View>
      {!!ov.data?.upcoming_deadlines.length && (
        <View className="rounded-2xl bg-white p-4 dark:bg-zinc-900">
          <Text className="mb-2 font-semibold text-zinc-900 dark:text-white">Upcoming deadlines</Text>
          {ov.data.upcoming_deadlines.slice(0, 4).map((d) => <Text key={d.title + d.at} className="text-sm text-zinc-600 dark:text-zinc-300">• {d.title}</Text>)}
        </View>
      )}
    </ScrollView>
  );
}
