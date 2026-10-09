import { type Conversation } from "@fm/shared";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { useEffect } from "react";
import { FlatList, Pressable, RefreshControl, Text, View } from "react-native";
import { Swipeable } from "react-native-gesture-handler";
import { api } from "@/api";
import { cached, flushQueue } from "@/offline";

export default function Inbox() {
  const router = useRouter();
  const qc = useQueryClient();
  const list = useQuery({ queryKey: ["conversations"], queryFn: () => cached("conversations", () => api.conversations()) });
  useEffect(() => {
    // retry queued offline replies whenever the inbox is opened
    flushQueue(async (r) => { await api.sendMessage(r.conversationId, { body: r.body, idempotency_key: r.key }); }).then((n) => { if (n) void qc.invalidateQueries({ queryKey: ["conversations"] }); });
  }, [qc]);

  const act = async (c: Conversation, kind: "archive" | "snooze") => {
    await api.patchConversation(c.id, kind === "archive" ? { status: "archived" } : { snooze_minutes: 60 });
    qc.invalidateQueries({ queryKey: ["conversations"] });
  };

  return (
    <View className="flex-1 bg-zinc-50 dark:bg-zinc-950">
      {list.data?.stale && <Text className="bg-amber-100 p-2 text-center text-xs text-amber-900">Offline - showing saved messages</Text>}
      <FlatList
        data={list.data?.data ?? []}
        keyExtractor={(c) => c.id}
        refreshControl={<RefreshControl refreshing={list.isFetching} onRefresh={() => list.refetch()} />}
        ListEmptyComponent={<Text className="p-8 text-center text-zinc-500">No conversations yet</Text>}
        renderItem={({ item: c }) => (
          <Swipeable
            renderLeftActions={() => <Pressable accessibilityRole="button" accessibilityLabel="Snooze one hour" onPress={() => act(c, "snooze")} className="justify-center bg-amber-500 px-5"><Text className="font-semibold text-white">Snooze</Text></Pressable>}
            renderRightActions={() => <Pressable accessibilityRole="button" accessibilityLabel="Archive" onPress={() => act(c, "archive")} className="justify-center bg-zinc-600 px-5"><Text className="font-semibold text-white">Archive</Text></Pressable>}
          >
            <Pressable accessibilityRole="button" onPress={() => router.push({ pathname: "/thread/[id]", params: { id: c.id } } as never)} className="border-b border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900">
              <View className="flex-row justify-between">
                <Text className={`text-base text-zinc-900 dark:text-white ${c.unread_count ? "font-bold" : ""}`}>{c.client_name || c.subject}{c.client_vip ? " ★" : ""}</Text>
                <Text className="text-xs capitalize text-zinc-500">{c.platform}</Text>
              </View>
              <Text numberOfLines={1} className="mt-1 text-sm text-zinc-500">{c.last_preview}</Text>
            </Pressable>
          </Swipeable>
        )}
      />
    </View>
  );
}
