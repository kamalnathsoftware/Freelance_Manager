import "../global.css";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StatusBar } from "expo-status-bar";
import { GestureHandlerRootView } from "react-native-gesture-handler";
import * as Notifications from "expo-notifications";
import { Stack, useRouter } from "expo-router";
import { useEffect, useState } from "react";
import { hasSession } from "@/api";
import { registerForPush } from "@/push";

export default function RootLayout() {
  const [qc] = useState(() => new QueryClient());
  const router = useRouter();
  useEffect(() => {
    void hasSession().then((ok) => { if (ok) void registerForPush(); });
    // deep link: tapping a push opens the inbox thread / page carried in data.url (e.g. /inbox?c=<id>)
    const sub = Notifications.addNotificationResponseReceivedListener((r) => {
      const url = String((r.notification.request.content.data as { url?: string })?.url ?? "");
      const m = url.match(/^\/inbox\?c=([\w-]+)/);
      router.push((m ? `/thread/${m[1]}` : "/(tabs)/home") as never);
    });
    return () => sub.remove();
  }, [router]);
  return (
    <GestureHandlerRootView style={{ flex: 1 }}>
      <QueryClientProvider client={qc}>
        <StatusBar style="auto" />
        <Stack screenOptions={{ headerShown: false }}>
          <Stack.Screen name="thread/[id]" options={{ headerShown: true, title: "Conversation" }} />
        </Stack>
      </QueryClientProvider>
    </GestureHandlerRootView>
  );
}
