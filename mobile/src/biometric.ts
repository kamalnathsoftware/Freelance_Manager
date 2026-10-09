import * as LocalAuthentication from "expo-local-authentication";

/** Returns true when the device has no biometrics enrolled (nothing to enforce) or the user passes the prompt. */
export async function unlockWithBiometrics(): Promise<boolean> {
  const [hasHw, enrolled] = await Promise.all([LocalAuthentication.hasHardwareAsync(), LocalAuthentication.isEnrolledAsync()]);
  if (!hasHw || !enrolled) return true;
  const r = await LocalAuthentication.authenticateAsync({ promptMessage: "Unlock Freelance Manager" });
  return r.success;
}
