import {
  BarChart3, Briefcase, CalendarDays, ClipboardList, FileText, FolderKanban, Inbox, KanbanSquare, LayoutDashboard, Settings,
  Bell, Plug, Sparkles, UserCircle, Users, Wallet, Zap, type LucideIcon,
} from "lucide-react";

export const NAV: { label: string; href: string; icon: LucideIcon }[] = [
  { label: "Dashboard", href: "/dashboard", icon: LayoutDashboard },
  { label: "Inbox", href: "/inbox", icon: Inbox },
  { label: "Platforms", href: "/platforms", icon: Plug },
  { label: "Jobs", href: "/jobs", icon: Briefcase },
  { label: "Pipeline", href: "/pipeline", icon: KanbanSquare },
  { label: "Gigs", href: "/gigs", icon: Sparkles },
  { label: "Profiles", href: "/profiles", icon: UserCircle },
  { label: "Clients", href: "/clients", icon: Users },
  { label: "Orders", href: "/orders", icon: ClipboardList },
  { label: "Projects", href: "/projects", icon: FolderKanban },
  { label: "Finance", href: "/finance", icon: Wallet },
  { label: "Calendar", href: "/calendar", icon: CalendarDays },
  { label: "Forms", href: "/forms", icon: FileText },
  { label: "Automations", href: "/automations", icon: Zap },
  { label: "Analytics", href: "/analytics", icon: BarChart3 },
  { label: "Notifications", href: "/notifications", icon: Bell },
  { label: "Settings", href: "/settings", icon: Settings },
];
