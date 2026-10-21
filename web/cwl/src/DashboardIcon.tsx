import {
  Tent, Target, LockKeyhole, House, LayoutDashboard, ListChecks, ClipboardPen, Shield, Trophy, ClipboardList, CornerUpLeft, Mail, Send, ChartNoAxesCombined, Medal, Download, Settings, Flag, ArrowLeftRight, Ticket, Wrench, Users, Swords, Terminal, Image, Plug, Bell, ChevronDown, ChevronRight, UsersRound, Clock, TriangleAlert, Paperclip,
} from 'lucide-react'
import './dashboardIcons.css'

const icons = {
  raid: Tent,
  games: Target,
  locked: LockKeyhole,
  home: House,
  overview: LayoutDashboard,
  tasks: ListChecks,
  signup: ClipboardPen,
  shield: Shield,
  trophy: Trophy,
  roster: ClipboardList,
  return: CornerUpLeft,
  mail: Mail,
  publish: Send,
  results: ChartNoAxesCombined,
  medal: Medal,
  download: Download,
  settings: Settings,
  flag: Flag,
  replace: ArrowLeftRight,
  ticket: Ticket,
  tools: Wrench,
  users: Users,
  war: Swords,
  command: Terminal,
  image: Image,
  connect: Plug,
  bell: Bell,
  chevronDown: ChevronDown,
  chevronRight: ChevronRight,
  accounts: UsersRound,
  waiting: Clock,
  warning: TriangleAlert,
  attachment: Paperclip,
} as const
export type DashboardIconName = keyof typeof icons

/** Decorative UI icons always accompany a visible text label. */
export default function DashboardIcon({ name, className = '' }: { name: DashboardIconName; className?: string }) {
  const Icon = icons[name]
  return <Icon className={`dashboard-icon ${className}`} size={18} strokeWidth={1.75} aria-hidden="true" focusable="false" />
}
