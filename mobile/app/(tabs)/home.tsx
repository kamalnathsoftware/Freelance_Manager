import { useQuery } from "@tanstack/react-query";
import { RefreshControl, ScrollView, Text, View } from "react-native";
import { api } from "@/api";

const KPIS = [["Unread", "0"], ["Active orders", "0"], ["Pending bids", "0"], ["Earnings (7d)", "$0"]];

export default function Home() {
  const me = useQuery({ queryKey: ["me"], queryFn: api.me });
  return (
    <ScrollView className="flex-1 bg-zinc-50 dark:bg-zinc-950" contentContainerClassName="gap-4 p-4"
      refreshControl={<RefreshControl refreshing={me.isFetching} onRefresh={() => me.refetch()} />}>
      <Text className="text-xl font-bold text-zinc-900 dark:text-white">Hi {me.data?.full_name || "there"} 👋</Text>
      <View className="flex-row flex-wrap gap-3">
        {KPIS.map(([label, value]) => (
          <View key={label} className="w-[48%] rounded-2xl bg-white p-4 dark:bg-zinc-900">
            <Text className="text-xs text-zinc-500">{label}</Text>
            <Text className="text-2xl font-bold text-zinc-900 dark:text-white">{value}</Text>
          </View>
        ))}
      </View>
    </ScrollView>
  );
}
