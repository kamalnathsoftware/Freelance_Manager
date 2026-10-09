import { useQuery, useQueryClient } from "@tanstack/react-query";
import { FlatList, Pressable, RefreshControl, Text, View } from "react-native";
import { api } from "@/api";

export default function Projects() {
  const qc = useQueryClient();
  const projects = useQuery({ queryKey: ["projects"], queryFn: api.projects });
  const running = useQuery({ queryKey: ["running"], queryFn: api.runningTimer, refetchInterval: 15000 });
  const refresh = () => { qc.invalidateQueries({ queryKey: ["running"] }); qc.invalidateQueries({ queryKey: ["projects"] }); };

  return (
    <View className="flex-1 bg-zinc-50 dark:bg-zinc-950">
      {running.data && (
        <Pressable accessibilityRole="button" accessibilityLabel="Stop timer" onPress={async () => { await api.stopTimer(); refresh(); }} className="m-3 flex-row items-center justify-between rounded-2xl bg-brand p-4">
          <Text className="font-semibold text-white">Timer running</Text><Text className="text-white">Tap to stop</Text>
        </Pressable>
      )}
      <FlatList
        data={projects.data ?? []}
        keyExtractor={(p) => p.id}
        refreshControl={<RefreshControl refreshing={projects.isFetching} onRefresh={refresh} />}
        ListEmptyComponent={<Text className="p-8 text-center text-zinc-500">No projects yet - create one on the web app</Text>}
        renderItem={({ item: p }) => (
          <View className="mx-3 mb-2 flex-row items-center justify-between rounded-2xl bg-white p-4 dark:bg-zinc-900">
            <View>
              <Text className="text-base font-semibold text-zinc-900 dark:text-white">{p.name}</Text>
              <Text className="text-xs text-zinc-500">{p.hours_tracked}h · {p.tasks_done}/{p.tasks_total} tasks</Text>
            </View>
            <Pressable accessibilityRole="button" accessibilityLabel={`Start timer for ${p.name}`} onPress={async () => { await api.startTimer({ project_id: p.id }); refresh(); }} className="rounded-xl bg-zinc-900 px-4 py-2 dark:bg-white">
              <Text className="font-semibold text-white dark:text-zinc-900">Start</Text>
            </Pressable>
          </View>
        )}
      />
    </View>
  );
}
