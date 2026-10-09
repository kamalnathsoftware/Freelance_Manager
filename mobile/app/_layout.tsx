import "../global.css";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Stack } from "expo-router";
import { StatusBar } from "expo-status-bar";
import { GestureHandlerRootView } from "react-native-gesture-handler";
import { useState } from "react";

export default function RootLayout() {
  const [qc] = useState(() => new QueryClient());
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
