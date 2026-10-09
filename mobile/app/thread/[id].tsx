import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useLocalSearchParams } from "expo-router";
import * as Linking from "expo-linking";
import { useState } from "react";
import { FlatList, KeyboardAvoidingView, Platform, Pressable, Text, TextInput, View } from "react-native";
import { api } from "@/api";
import { cached, enqueueReply } from "@/offline";

export default function Thread() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const qc = useQueryClient();
  const [draft, setDraft] = useState("");
  const [note, setNote] = useState("");
  const msgs = useQuery({ queryKey: ["messages", id], queryFn: () => cached(`messages:${id}`, () => api.messages(id)) });

  const send = async () => {
    const body = draft.trim();
    if (!body) return;
    setDraft("");
    try {
      const key = `m-${Date.now()}`;
      const r = await api.sendMessage(id, { body, idempotency_key: key });
      if (r.requires_manual_paste && r.reply_on_platform_url) {
        setNote("This platform needs you to paste the reply there.");
        await Linking.openURL(r.reply_on_platform_url);
      }
      qc.invalidateQueries({ queryKey: ["messages", id] });
    } catch {
      await enqueueReply({ conversationId: id, body });
      setNote("You're offline - reply saved and will send automatically.");
    }
  };

  return (
    <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : undefined} className="flex-1 bg-zinc-50 dark:bg-zinc-950">
      <FlatList
        data={msgs.data?.data ?? []}
        keyExtractor={(m) => m.id}
        contentContainerClassName="gap-2 p-4"
        renderItem={({ item: m }) => (
          <View className={`max-w-[80%] rounded-2xl px-3 py-2 ${m.direction === "out" ? "self-end bg-brand" : "self-start bg-zinc-200 dark:bg-zinc-800"}`}>
            <Text className={m.direction === "out" ? "text-white" : "text-zinc-900 dark:text-white"}>{m.body}</Text>
            {m.ai_generated && <Text className="mt-1 text-[10px] text-white/70">AI-assisted</Text>}
          </View>
        )}
      />
      {!!note && <Text className="px-4 pb-1 text-xs text-amber-600">{note}</Text>}
      <View className="flex-row items-end gap-2 border-t border-zinc-200 p-3 dark:border-zinc-800">
        <TextInput accessibilityLabel="Reply" value={draft} onChangeText={setDraft} multiline placeholder="Reply…" className="max-h-32 min-h-10 flex-1 rounded-xl border border-zinc-300 px-3 dark:border-zinc-700 dark:text-white" />
        <Pressable accessibilityRole="button" onPress={send} className="h-10 items-center justify-center rounded-xl bg-brand px-4"><Text className="font-semibold text-white">Send</Text></Pressable>
      </View>
    </KeyboardAvoidingView>
  );
}
