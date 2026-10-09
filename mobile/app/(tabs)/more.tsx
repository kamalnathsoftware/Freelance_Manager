import { useRouter } from "expo-router";
import { Pressable, Text, View } from "react-native";
import { api } from "@/api";

export default function More() {
  const router = useRouter();
  return (
    <View className="flex-1 gap-3 bg-zinc-50 p-4 dark:bg-zinc-950">
      <Pressable accessibilityRole="button" className="rounded-xl bg-white p-4 dark:bg-zinc-900"
        onPress={async () => { await api.logout(); router.replace("/login"); }}>
        <Text className="text-red-600">Log out</Text>
      </Pressable>
    </View>
  );
}
