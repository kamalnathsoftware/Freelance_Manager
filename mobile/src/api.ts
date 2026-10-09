import { ApiClient, type TokenPair, type TokenStore } from "@fm/shared";
import * as SecureStore from "expo-secure-store";

const KEY = "fm.tokens";

// Tokens are kept in the OS keychain/keystore, never in plain AsyncStorage.
const store: TokenStore = {
  async get() {
    const raw = await SecureStore.getItemAsync(KEY);
    return raw ? (JSON.parse(raw) as TokenPair) : null;
  },
  async set(t) {
    if (t) await SecureStore.setItemAsync(KEY, JSON.stringify(t));
    else await SecureStore.deleteItemAsync(KEY);
  },
};

export const api = new ApiClient(process.env.EXPO_PUBLIC_API_URL ?? "http://localhost:8000", store);
export const hasSession = async () => (await store.get()) !== null;
