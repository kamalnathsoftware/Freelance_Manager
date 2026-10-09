import { ApiError } from "@fm/shared";
import { useRouter } from "expo-router";
import { useState } from "react";
import { Pressable, Text, TextInput, View } from "react-native";
import { api } from "@/api";

export default function Login() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [mfa, setMfa] = useState<string | null>(null);
  const [code, setCode] = useState("");
  const [error, setError] = useState("");

  const submit = async () => {
    setError("");
    try {
      if (mfa) { await api.login2fa(mfa, code); router.replace("/(tabs)/home"); return; }
      const r = await api.login({ email, password });
      if (r.mfa_required) setMfa(r.mfa_token); else router.replace("/(tabs)/home");
    } catch (e) { setError(e instanceof ApiError ? e.message : "Something went wrong"); }
  };

  return (
    <View className="flex-1 justify-center gap-4 bg-white p-6 dark:bg-zinc-950">
      <Text className="text-2xl font-bold text-zinc-900 dark:text-white">Freelance Manager</Text>
      {mfa ? (
        <TextInput accessibilityLabel="Verification code" placeholder="6-digit code" keyboardType="number-pad" value={code} onChangeText={setCode}
          className="h-12 rounded-xl border border-zinc-300 px-3 dark:border-zinc-700 dark:text-white" />
      ) : (
        <>
          <TextInput accessibilityLabel="Email" placeholder="Email" autoCapitalize="none" keyboardType="email-address" value={email} onChangeText={setEmail}
            className="h-12 rounded-xl border border-zinc-300 px-3 dark:border-zinc-700 dark:text-white" />
          <TextInput accessibilityLabel="Password" placeholder="Password" secureTextEntry value={password} onChangeText={setPassword}
            className="h-12 rounded-xl border border-zinc-300 px-3 dark:border-zinc-700 dark:text-white" />
        </>
      )}
      {!!error && <Text className="text-red-600">{error}</Text>}
      <Pressable accessibilityRole="button" onPress={submit} className="h-12 items-center justify-center rounded-xl bg-brand">
        <Text className="font-semibold text-white">{mfa ? "Verify" : "Sign in"}</Text>
      </Pressable>
    </View>
  );
}
