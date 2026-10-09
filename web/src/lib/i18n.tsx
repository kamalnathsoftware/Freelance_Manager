"use client";
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

/** Minimal i18n: flat key -> string dictionaries, English fallback, `{name}` interpolation.
 *  Add a locale by adding a dictionary here (or lazy-loading JSON) - components only ever call t("key"). */
export const dictionaries = {
  en: {
    "nav.dashboard": "Dashboard", "nav.inbox": "Inbox", "nav.platforms": "Platforms", "nav.jobs": "Jobs", "nav.pipeline": "Pipeline", "nav.gigs": "Gigs",
    "nav.profiles": "Profiles", "nav.clients": "Clients", "nav.orders": "Orders", "nav.projects": "Projects", "nav.finance": "Finance", "nav.calendar": "Calendar",
    "nav.forms": "Forms", "nav.automations": "Automations", "nav.analytics": "Analytics", "nav.notifications": "Notifications", "nav.settings": "Settings",
    "common.search": "Search…", "common.logout": "Log out", "common.save": "Save", "common.cancel": "Cancel", "common.loading": "Loading…",
    "auth.welcome": "Welcome back", "auth.signin": "Sign in", "auth.signup": "Create account", "auth.email": "Email", "auth.password": "Password",
    "dash.title": "Dashboard", "dash.net": "Net earnings", "dash.winrate": "Win rate", "dash.pipeline": "Open pipeline", "dash.orders": "Active orders", "dash.today": "Today",
  },
  es: {
    "nav.dashboard": "Panel", "nav.inbox": "Bandeja", "nav.platforms": "Plataformas", "nav.jobs": "Trabajos", "nav.pipeline": "Embudo", "nav.gigs": "Servicios",
    "nav.profiles": "Perfiles", "nav.clients": "Clientes", "nav.orders": "Pedidos", "nav.projects": "Proyectos", "nav.finance": "Finanzas", "nav.calendar": "Calendario",
    "nav.forms": "Formularios", "nav.automations": "Automatizaciones", "nav.analytics": "Analítica", "nav.notifications": "Notificaciones", "nav.settings": "Ajustes",
    "common.search": "Buscar…", "common.logout": "Cerrar sesión", "common.save": "Guardar", "common.cancel": "Cancelar", "common.loading": "Cargando…",
    "auth.welcome": "Bienvenido de nuevo", "auth.signin": "Iniciar sesión", "auth.signup": "Crear cuenta", "auth.email": "Correo", "auth.password": "Contraseña",
    "dash.title": "Panel", "dash.net": "Ingresos netos", "dash.winrate": "Tasa de éxito", "dash.pipeline": "Embudo abierto", "dash.orders": "Pedidos activos", "dash.today": "Hoy",
  },
} as const;

export type Locale = keyof typeof dictionaries;
export type Key = keyof (typeof dictionaries)["en"];
export const LOCALES: { code: Locale; label: string }[] = [{ code: "en", label: "English" }, { code: "es", label: "Español" }];

export function translate(locale: Locale, key: Key, vars?: Record<string, string | number>): string {
  const dict = dictionaries[locale] as Record<string, string>;
  const raw = dict[key] ?? (dictionaries.en as Record<string, string>)[key] ?? key;
  return vars ? raw.replace(/\{(\w+)\}/g, (_, k) => String(vars[k] ?? `{${k}}`)) : raw;
}

const Ctx = createContext<{ locale: Locale; setLocale: (l: Locale) => void; t: (k: Key, v?: Record<string, string | number>) => string }>({
  locale: "en", setLocale: () => {}, t: (k) => translate("en", k),
});
export const useT = () => useContext(Ctx);

export function I18nProvider({ children }: { children: React.ReactNode }) {
  const [locale, setLoc] = useState<Locale>("en");
  useEffect(() => {
    let saved: string | null = null;
    try { saved = localStorage.getItem("fm.locale"); } catch { /* storage unavailable */ }
    const guess = (saved ?? navigator.language.slice(0, 2)) as Locale;
    if (guess in dictionaries) setLoc(guess);
  }, []);
  useEffect(() => { document.documentElement.lang = locale; }, [locale]);
  const setLocale = useCallback((l: Locale) => { setLoc(l); try { localStorage.setItem("fm.locale", l); } catch { /* ignore */ } }, []);
  const value = useMemo(() => ({ locale, setLocale, t: (k: Key, v?: Record<string, string | number>) => translate(locale, k, v) }), [locale, setLocale]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}
