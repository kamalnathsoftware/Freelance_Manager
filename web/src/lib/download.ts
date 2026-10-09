import { api } from "./api";

export async function download(path: string, filename: string) {
  const blob = await api.blob(path);
  const url = URL.createObjectURL(blob);
  Object.assign(document.createElement("a"), { href: url, download: filename }).click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
