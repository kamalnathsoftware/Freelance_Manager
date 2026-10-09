import {
  BarChart3, Briefcase, CalendarDays, ClipboardList, FileText, FolderKanban, Inbox, KanbanSquare, LayoutDashboard, Settings,
  Bell, Plug, Sparkles, UserCircle, Users, Wallet, Zap, type LucideIcon,
} from "lucide-react";

import type { Key } from "@/lib/i18n";

export const NAV: { label: string; key: Key; href: string; icon: LucideIcon }[] = [
  { label: "Dashboard", key: "nav.dashboard", href: "/dashboard", icon: LayoutDashboard },
  { label: "Inbox", key: "nav.inbox", href: "/inbox", icon: Inbox },
  { label: "Platforms", key: "nav.platforms", href: "/platforms", icon: Plug },
  { label: "Jobs", key: "nav.jobs", href: "/jobs", icon: Briefcase },
  { label: "Pipeline", key: "nav.pipeline", href: "/pipeline", icon: KanbanSquare },
  { label: "Gigs", key: "nav.gigs", href: "/gigs", icon: Sparkles },
  { label: "Profiles", key: "nav.profiles", href: "/profiles", icon: UserCircle },
  { label: "Clients", key: "nav.clients", href: "/clients", icon: Users },
  { label: "Orders", key: "nav.orders", href: "/orders", icon: ClipboardList },
  { label: "Projects", key: "nav.projects", href: "/projects", icon: FolderKanban },
  { label: "Finance", key: "nav.finance", href: "/finance", icon: Wallet },
  { label: "Calendar", key: "nav.calendar", href: "/calendar", icon: CalendarDays },
  { label: "Forms", key: "nav.forms", href: "/forms", icon: FileText },
  { label: "Automations", key: "nav.automations", href: "/automations", icon: Zap },
  { label: "Analytics", key: "nav.analytics", href: "/analytics", icon: BarChart3 },
  { label: "Notifications", key: "nav.notifications", href: "/notifications", icon: Bell },
  { label: "Settings", key: "nav.settings", href: "/settings", icon: Settings },
];
