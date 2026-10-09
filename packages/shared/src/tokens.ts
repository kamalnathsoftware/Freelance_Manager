/** Design tokens shared by web (Tailwind) and mobile (NativeWind). 8-pt spacing scale. */
export const spacing = { 1: 4, 2: 8, 3: 12, 4: 16, 6: 24, 8: 32, 12: 48 } as const;

export const colors = {
  brand: "#4f46e5",
  brandFg: "#ffffff",
  success: "#16a34a",
  warning: "#d97706",
  danger: "#dc2626",
} as const;

/** Brand colours used for platform badges. */
export const platformColors: Record<string, string> = {
  fiverr: "#1dbf73",
  upwork: "#14a800",
  freelancer: "#29b2fe",
  peopleperhour: "#fc9d13",
  toptal: "#204ecf",
  guru: "#e0782c",
  linkedin: "#0a66c2",
  contra: "#111827",
  direct: "#6b7280",
};
