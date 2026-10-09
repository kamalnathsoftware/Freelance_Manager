import { Redirect } from "expo-router";
import { useEffect, useState } from "react";
import { hasSession } from "@/api";
import { unlockWithBiometrics } from "@/biometric";

export default function Index() {
  const [dest, setDest] = useState<string | null>(null);
  useEffect(() => {
    (async () => {
      if (!(await hasSession())) return setDest("/login");
      setDest((await unlockWithBiometrics()) ? "/(tabs)/home" : "/login");
    })();
  }, []);
  return dest ? <Redirect href={dest as never} /> : null;
}
