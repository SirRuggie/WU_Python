import AccountLinkHelp from './AccountLinkHelp'
import WarsWorkspace from './activity/WarsWorkspace'
import EventsWorkspace from './activity/EventsWorkspace'
import DashboardSearch from './DashboardSearch'
import DashboardIcon from './DashboardIcon'
import StaffPlayerButton from './StaffPlayerButton'
import ArrivalCheck from './ArrivalCheck'
import StaffSignupControls from './StaffSignupControls'
import StaffOverview from './StaffOverview'
import ClanManagement from './ClanManagement'
import StrikesWorkspace from './StrikesWorkspace'
import ReplacementWorkspace from './ReplacementWorkspace'
import { strikePermissions } from './strikePermissions'
import {isManagementArea, managementAreas} from './managementAreas'
import TextCommands from './TextCommands'
import AccessSettings from './AccessSettings'
import ServerManagement from './ServerManagement'
import { FilterPicker, leagueValue, matchesLeague } from './ClanFilters'
import { sortClans, clanSortOptions, type ClanSort } from './clanSort'
import { stopPushOnSignout } from './PushReminders'
import ReminderWorkspace from './ReminderWorkspace'
import SidebarNavigation, { navigationSection, visibleNavigationSections, type DashboardView } from './SidebarNavigation'
import TodoWorkspace from './TodoWorkspace'
import { memberTarget, loginPath } from './memberLinks'
import { DashboardHistory, dashboardTarget } from './dashboardHistory'
import './Welcome.css'
import DashboardHome from './DashboardHome'
import './SignupFlow.css'
import ExportWorkspace from './ExportWorkspace'
import TownHallIcon from './TownHallIcon'
import type { ReadinessFilter } from './readiness'
import './staffNavigation.css'
import './sidebar.css'
import { AccountIdentity } from './AccountIdentity'
import RosterWorkspace from './RosterWorkspace'
import PublicationWorkspace from './PublicationWorkspace'
import ParticipationWorkspace from './ParticipationWorkspace'
import BonusWorkspace from './BonusWorkspace'
import MemberAssignments from './MemberAssignments'
import { lazy, Suspense, useCallback, useEffect, useRef, useState } from 'react'
import { api, ApiError, setCsrfToken, type Account, type Clan, type Pool, type Season, type Session, type Signup } from './api'
import { accountPool, reconcileSelection, clearSubmittedDraft, selectAllAvailable, selectable, selectedForPool, submittedSummary, transferSource, type Draft, type TransferConsent } from './signup'

const ImageGallery = lazy(() => import('./CommandImageLibrary').then(module => ({default:module.ImageGallery})))
const TicketBrowser = lazy(() => import('./TicketBrowser'))
type View = DashboardView
type Notice = { kind: 'success' | 'error'; text: string }
type Completion = { seasonId: string; seasonLabel: string; pool: Pool; accounts: ReturnType<typeof submittedSummary>; moved: number; refreshWarning: boolean }
const poolName = (pool: Pool | null) => pool === 'lazy' ? 'Lazy CWL' : pool === 'main' ? 'Main Clan CWL' : 'CWL'
const message = (error: unknown) => error instanceof Error ? error.message : 'Something went wrong. Try again.'
const tagPath = (tag: string) => encodeURIComponent(tag)
const serverIconUrl = 'https://cdn.discordapp.com/icons/644963518025826315/a_8070a2dc790e4ff877d5f3df7e79b8fe.png?size=128'

function App() {
  const [session, setSession] = useState<Session | null>(null)
  const [authState, setAuthState] = useState<'loading' | 'signed-out' | 'error' | 'ready'>('loading')
  const [authError, setAuthError] = useState(() => new URLSearchParams(window.location.search).get('signin_error') === 'discord' ? 'Discord sign-in did not finish. Please try again.' : '')
  const [fixtureMode, setFixtureMode] = useState(false)
  const [entryTarget] = useState(() => dashboardTarget(window.location.search))
  const [publicationDirty, setPublicationDirty] = useState(false)
  const [publicationStep, setPublicationStep] = useState<'review' | 'announce'>(entryTarget.step || 'review')
  const [rosterRefresh, setRosterRefresh] = useState(0)
  const [rosterReadiness, setRosterReadiness] = useState<ReadinessFilter>('all')
  const [view, setView] = useState<View>(entryTarget.view)
  const [reminderDirty, setReminderDirty] = useState(false)
  const [menuOpen, setMenuOpen] = useState(false)
  const [seasons, setSeasons] = useState<Season[]>([])
  const [seasonId, setSeasonId] = useState(entryTarget.season)
  const [pool, setPool] = useState<Pool | null>(null)
  const [signupSearch, setSignupSearch] = useState('')
  const [signupPage, setSignupPage] = useState(0)
  useEffect(() => { setSignupPage(0) }, [signupSearch, pool, seasonId])
  const [showSignedUp, setShowSignedUp] = useState(false)
  useEffect(() => { setShowSignedUp(false) }, [seasonId])
  const [signupPanel, setSignupPanel] = useState<'register' | 'saved'>('register')
  const [accounts, setAccounts] = useState<Account[]>([])
  const [signups, setSignups] = useState<Signup[]>([])
  const [staffSignups, setStaffSignups] = useState<Signup[]>([])
  const dashboardPrefill = useRef(false)
  const signupRequest = useRef(0)
  const staffRequest = useRef(0)
  const currentSeason = useRef('')
  currentSeason.current = seasonId
  const [signupStep, setSignupStep] = useState<1 | 2>(1)
  const stepHeadingRef = useRef<HTMLHeadingElement>(null)
  useEffect(() => { setSignupStep(1); setPool(null); setReview(false); setCompletion(null); setAccounts([]); setSignups([]); setDrafts({main: {}, lazy: {}}); setTransfers({main: {}, lazy: {}}) }, [seasonId])
  const [drafts, setDrafts] = useState<Record<Pool, Draft>>({ main: {}, lazy: {} })
  const [transfers, setTransfers] = useState<Record<Pool, TransferConsent>>({ main: {}, lazy: {} })
  const selectionRef = useRef({ drafts, transfers })
  selectionRef.current = { drafts, transfers }
  const signupBusy = useRef(false)
  const [accountError, setAccountError] = useState('')
  const [seasonError, setSeasonError] = useState('')
  const [seasonsLoading, setSeasonsLoading] = useState(true)
  const [dataError, setDataError] = useState('')
  const [loadingData, setLoadingData] = useState(false)
  const [pending, setPending] = useState(false)
  const [withdrawingTag, setWithdrawingTag] = useState<string | null>(null)
  const [review, setReview] = useState(false)
  const [completion, setCompletion] = useState<Completion | null>(null)
  const [jumpTarget, setJumpTarget] = useState<'selection' | 'registered' | null>(null)
  const completionHeadingRef = useRef<HTMLHeadingElement>(null)
  const selectionHeadingRef = useRef<HTMLHeadingElement>(null)
  const registeredHeadingRef = useRef<HTMLHeadingElement>(null)
  const [notice, setNotice] = useState<Notice | null>(null)
  const [clans, setClans] = useState<Clan[]>([])
  const [approved, setApproved] = useState<Clan[]>([])
  const [approvedCheckedAt, setApprovedCheckedAt] = useState('')
  const [approvedSource, setApprovedSource] = useState('')
  const [approvedError, setApprovedError] = useState('')
  const [staffError, setStaffError] = useState('')
  const [staffLoading, setStaffLoading] = useState(false)
  const [newSeasonLabel, setNewSeasonLabel] = useState('')
  const [newClanTag, setNewClanTag] = useState('')
  const [newClanPool, setNewClanPool] = useState<Pool | ''>('')
  const [staffSection, setStaffSection] = useState<'season' | 'hosting' | 'family' | 'signups'>('hosting')
  const [staffSearch, setStaffSearch] = useState('')
  const [clanLeagues,setClanLeagues] = useState<string[]>([])
  const [clanSort, setClanSort] = useState<ClanSort>('name')
  const [hostStatus, setHostStatus] = useState('active')
  const [staffPoolFilter, setStaffPoolFilter] = useState('all')
  const [staffPage, setStaffPage] = useState(0)
  useEffect(() => { setStaffPage(0) }, [staffSearch, hostStatus, staffPoolFilter, staffSection, seasonId, clanSort, clanLeagues])


  const loadAuth = useCallback(async () => {
    setAuthState('loading')
    try {
      const me = await api<Session>('/auth/me')
      setCsrfToken(me.csrf_token)
      setSession(me)
      setAuthState('ready')
    } catch (error) {
      setSession(null)
      if (error instanceof ApiError && error.status === 401) setAuthState('signed-out')
      else { setAuthError(message(error)); setAuthState('error') }
    }
  }, [])
  useEffect(() => { void loadAuth() }, [loadAuth])
  useEffect(() => { if (['localhost', '127.0.0.1', '[::1]'].includes(window.location.hostname)) void api<{ dev_fixture: boolean }>('/config').then(result => setFixtureMode(result.dev_fixture)).catch(() => setFixtureMode(false)) }, [])
  useEffect(() => {
    const close = (event: KeyboardEvent) => { if (event.key === 'Escape') { setMenuOpen(false); setReview(false) } }
    window.addEventListener('keydown', close)
    return () => window.removeEventListener('keydown', close)
  }, [])

  const loadSeasons = useCallback(async () => {
    setSeasonsLoading(true)
    try {
      const result = await api<{ seasons: Season[] }>('/seasons')
      setSeasons(result.seasons)
      if (entryTarget.season && !result.seasons.some(item => String(item.id) === entryTarget.season)) setNotice({kind:'error', text:'The season in this link is not available. Check the season shown before signing up.'})
      setSeasonId(current => result.seasons.some(season => String(season.id) === current) ? current : String(result.seasons[0]?.id || ''))
      setSeasonError('')
    } catch (error) { setSeasonError(message(error)) }
    finally { setSeasonsLoading(false) }
  }, [])
  useEffect(() => { if (session) void loadSeasons() }, [session, loadSeasons])

  const loadSignup = useCallback(async () => {
    if (!seasonId) return
    setLoadingData(true)
    setReview(false)
    const requestId = ++signupRequest.current
    setAccountError('')
    setDataError('')
    const [accountsResult, signupsResult] = await Promise.allSettled([
      api<{ accounts: Account[]; link_instruction?: string | null }>('/linked-accounts'),
      api<{ signups: Signup[] }>(`/seasons/${encodeURIComponent(seasonId)}/signups`),
    ])
    if (requestId !== signupRequest.current || currentSeason.current !== seasonId) return { all: false, signups: false }
    let freshAccounts: Account[] | null = null
    let freshSignups: Signup[] | null = null
    if (accountsResult.status === 'fulfilled') { freshAccounts = accountsResult.value.accounts; setAccounts(freshAccounts) }
    else { setAccounts([]); setAccountError(message(accountsResult.reason)) }
    if (signupsResult.status === 'fulfilled') { freshSignups = signupsResult.value.signups; setSignups(freshSignups) }
    else { setSignups([]); setDataError(message(signupsResult.reason)) }
    if (freshAccounts !== null && freshSignups !== null) {
      const previous = selectionRef.current
      const main = reconcileSelection(previous.drafts.main, previous.transfers.main, freshAccounts, freshSignups, 'main')
      const lazy = reconcileSelection(previous.drafts.lazy, previous.transfers.lazy, freshAccounts, freshSignups, 'lazy')
      setDrafts({ main: main.draft, lazy: lazy.draft })
      setTransfers({ main: main.transfers, lazy: lazy.transfers })
      if (Object.keys(main.draft).length + Object.keys(lazy.draft).length < Object.keys(previous.drafts.main).length + Object.keys(previous.drafts.lazy).length) setNotice({kind:'error', text:'Some selections changed because account links or saved pools changed. Check your accounts before continuing.'})
    }
    setLoadingData(false)
    return { all: freshAccounts !== null && freshSignups !== null, signups: freshSignups !== null }
  }, [seasonId])
  useEffect(() => {
    if (!session || !seasonId || view !== 'signup') return
    if (dashboardPrefill.current) { dashboardPrefill.current = false; return () => { signupRequest.current += 1 } }
    void loadSignup()
    return () => { signupRequest.current += 1 }
  }, [session, seasonId, view, loadSignup])

  const loadStaff = useCallback(async () => {
    if (!session?.can_edit) return
    const requestId = ++staffRequest.current
    setStaffLoading(true)
    const requests = await Promise.allSettled([
      api<{ clans: Clan[] }>('/clans'),
      api<{ source: string; status: string; checked_at: string; clans: Clan[] }>('/approved-clans'),
      seasonId ? api<{ signups: Signup[] }>(`/seasons/${encodeURIComponent(seasonId)}/signups?all=1`) : Promise.resolve({ signups: [] }),
    ])
    if (requestId !== staffRequest.current || currentSeason.current !== seasonId) return
    if (requests[0].status === 'fulfilled') setClans(requests[0].value.clans)
    if (requests[1].status === 'fulfilled') {
      setApproved(requests[1].value.clans)
      setApprovedSource(requests[1].value.source)
      setApprovedCheckedAt(requests[1].value.checked_at)
      setApprovedError('')
    } else {
      setApproved([])
      setApprovedSource('')
      setApprovedCheckedAt('')
      setApprovedError(message(requests[1].reason))
    }
    if (requests[2].status === 'fulfilled') setStaffSignups(requests[2].value.signups)
    const otherFailure = [requests[0], requests[2]].find(result => result.status === 'rejected') as PromiseRejectedResult | undefined
    setStaffError(otherFailure ? message(otherFailure.reason) : '')
    setStaffLoading(false)
  }, [session?.can_edit, seasonId])
  useEffect(() => { if (view === 'staff') void loadStaff() }, [view, loadStaff])


  useEffect(() => {
    if (view !== 'signup' || signupPanel !== 'register' || completion) return
    stepHeadingRef.current?.focus({ preventScroll: true })
    stepHeadingRef.current?.scrollIntoView({ behavior: 'instant', block: 'start' })
  }, [signupStep, review, signupPanel, seasonId, view, completion])
  useEffect(() => {
    if (!completion || view !== 'signup' || completion.seasonId !== seasonId) return
    window.scrollTo({ top: 0, behavior: 'instant' })
    completionHeadingRef.current?.focus()
  }, [completion?.seasonId, seasonId, view])
  useEffect(() => {
    if (!jumpTarget || completion) return
    const target = jumpTarget === 'registered' ? registeredHeadingRef.current : selectionHeadingRef.current
    target?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    target?.focus({ preventScroll: true })
    setJumpTarget(null)
  }, [jumpTarget, completion])
  const season = seasons.find(item => String(item.id) === seasonId)
  const draft = pool ? drafts[pool] : {}
  const transferConsent = pool ? transfers[pool] : {}
  const visibleAccounts = accounts.filter(account => showSignedUp || !accountPool(signups, account.tag))
  const matchingAccounts = visibleAccounts.filter(account => [account.name, account.tag, account.current_clan_name, account.current_clan_tag].some(value => value?.toLowerCase().includes(signupSearch.trim().toLowerCase())))
  const lastSignupPage = Math.max(0, Math.ceil(matchingAccounts.length / 12) - 1)
  const currentSignupPage = Math.min(signupPage, lastSignupPage)
  const pageAccounts = matchingAccounts.slice(currentSignupPage * 12, (currentSignupPage + 1) * 12)
  const selected = pool ? selectedForPool(accounts, draft, signups, pool, transferConsent) : []
  const available = pool ? matchingAccounts.filter(account => selectable(account, pool, signups)) : []
  const existing = signups
  const activeCompletion = completion?.seasonId === seasonId ? completion : null
  const setDraft = (next: Draft) => { if (!pool) return; setDrafts(current => ({ ...current, [pool]: next })); setReview(false); setNotice(null) }
  const choosePool = (next: Pool) => { if (pool && next !== pool && Object.keys(draft).length && !window.confirm('Change CWL pool and clear your unsubmitted selections? Saved signups stay unchanged.')) return; setSignupStep(2); if (pool === next) return; setSignupPanel('register'); setPool(next); setDrafts({ main: {}, lazy: {} }); setTransfers({ main: {}, lazy: {} }); setReview(false) }
  const [manageDirty, setManageDirty] = useState(false)
  const [cwlDirty, setCwlDirty] = useState(false)
  const navigation = useRef<DashboardHistory | null>(null)
  const signupDirty = Object.values(drafts).some(draft => Object.keys(draft).length > 0)
  useEffect(() => {
    if (view !== 'signup' || (!signupDirty && !pending)) return
    const protect = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = '' }
    window.addEventListener('beforeunload', protect)
    return () => window.removeEventListener('beforeunload', protect)
  }, [view, signupDirty, pending])
  const canLeave = () => {
    if (view === 'signup' && (pending || signupBusy.current)) return false
    if (view === 'signup' && signupDirty && !window.confirm('Leave without submitting your CWL selections? Your saved signups will stay unchanged.')) return false
    if (['roster', 'participation', 'bonuses'].includes(view) && cwlDirty) return window.confirm('Leave this CWL workspace? Unsaved edits will be discarded. If a save is in progress, wait for it to finish first.')
    if (view === 'publication' && publicationDirty) return window.confirm('Leave without saving announcement changes?')
    if ((isManagementArea(view) || ['manage','text-commands','clan-management'].includes(view)) && manageDirty) return window.confirm('Leave without saving your changes?')
    if (view === 'reminders' && reminderDirty) return window.confirm('Leave without saving your reminder changes?')
    return true
  }
  const allowedView = (next: View): View => {
    if (!session) return 'home'
    return visibleNavigationSections(session.can_edit, session.is_owner, session.dashboard_permissions || []).some(section => section.items.some(item => item.view === next))
      || (next === 'manage' && session.is_owner) ? next : 'home'
  }
  const acceptRoute = (next: View) => { if (next !== 'signup') { setDrafts({ main: {}, lazy: {} }); setTransfers({ main: {}, lazy: {} }) }; setView(next); setMenuOpen(false); setNotice(null) }
  const [searchQuery, setSearchQuery] = useState('')
  const [searchKind, setSearchKind] = useState<'all' | 'player' | 'clan'>('all')
  const [searchPage, setSearchPage] = useState(0)
  const [activitySearch, setActivitySearch] = useState('')
  const [activityKind, setActivityKind] = useState<'war'|'cwl'|undefined>()
  useEffect(() => { setSearchQuery(''); setSearchKind('all'); setSearchPage(0); setActivitySearch('') }, [session?.user.id])
  const changeView = (next: View, filter = '', kind?: 'war'|'cwl') => {
    if (navigation.current?.pending || (next !== view && !canLeave())) return
    const destination = allowedView(next)
    if (destination !== view) navigation.current?.write({ view: destination, season: seasonId, ...(destination === 'publication' ? {step: publicationStep} : {}) }, true)
    setActivitySearch(filter)
    setActivityKind(kind)
    acceptRoute(destination)
  }
  useEffect(() => {
    const shortcut = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k' && !event.altKey && !event.repeat && !event.isComposing && session) {
        event.preventDefault()
        changeView('search')
        if (view === 'search') document.getElementById('dashboard-search')?.focus()
      }
    }
    window.addEventListener('keydown', shortcut)
    return () => window.removeEventListener('keydown', shortcut)
  })
  const openPublication = (step: 'review' | 'announce') => {
    if (navigation.current?.pending || (view === 'publication' && publicationStep === step)) return
    if (!canLeave()) return
    navigation.current?.write({view: 'publication', season: seasonId, step}, true)
    setPublicationStep(step)
    acceptRoute('publication')
  }
  const navigationState = useRef({ canLeave, allowedView })
  navigationState.current = { canLeave, allowedView }
  useEffect(() => {
    const controller = new DashboardHistory(window.history)
    navigation.current = controller
    const pop = (event: PopStateEvent) => {
      if (!controller.pop(event.state, () => navigationState.current.canLeave())) return
      const target = dashboardTarget(window.location.search)
      const destination = navigationState.current.allowedView(target.view)
      setSeasonId(target.season)
      setPublicationStep(target.step || 'review')
      acceptRoute(destination)
      controller.write({ ...target, view: destination }, false)
    }
    window.addEventListener('popstate', pop)
    return () => { window.removeEventListener('popstate', pop); navigation.current = null }
  }, [])
  useEffect(() => {
    if (authState !== 'ready') return
    const destination = allowedView(view)
    if (destination !== view) setView(destination)
    navigation.current?.write({ view: destination, season: seasonId, ...(destination === 'publication' ? {step: publicationStep} : {}) }, false)
  }, [view, seasonId, publicationStep, authState, session])
  const run = async (action: () => Promise<unknown>, success: string, refresh: () => Promise<unknown>) => {
    setPending(true); setNotice(null)
    try { await action(); await refresh(); setNotice({ kind: 'success', text: success }) }
    catch (error) { setNotice({ kind: 'error', text: message(error) }) }
    finally { setPending(false) }
  }
  const submit = async () => {
    if (!seasonId || !season || !pool || !selected.length || pending || signupBusy.current || loadingData || dataError || accountError || !season.signup_open || season.status !== 'draft') return
    signupBusy.current = true
    const submittedSeason = seasonId
    const submittedPool = pool
    const submittedAccounts = selected.map(item => ({ ...item }))
    const summary: Completion = { seasonId: submittedSeason, seasonLabel: season.label, pool: submittedPool, accounts: submittedSummary(accounts, submittedAccounts), moved: 0, refreshWarning: false }
    setPending(true)
    setNotice(null)
    try {
      const result = await api<{ ok: boolean; count: number; moved: number }>(`/seasons/${encodeURIComponent(submittedSeason)}/signups`, 'POST', { pool: submittedPool, accounts: submittedAccounts })
      summary.moved = result.moved || 0
    } catch (error) {
      setNotice({ kind: 'error', text: message(error) })
      signupBusy.current = false
      setPending(false)
      return
    }
    if (currentSeason.current !== submittedSeason) { signupBusy.current = false; setPending(false); return }
    setDrafts(current => clearSubmittedDraft(current, submittedPool))
    setTransfers(current => ({ ...current, [submittedPool]: {} }))
    setReview(false)
    setShowSignedUp(false)
    setCompletion(summary)
    selectionRef.current = { drafts: {main: {}, lazy: {}}, transfers: {main: {}, lazy: {}} }
    const refreshed = await loadSignup()
    if (!refreshed?.all && currentSeason.current === submittedSeason) setCompletion(current => current?.seasonId === submittedSeason ? { ...current, refreshWarning: true } : current)
    signupBusy.current = false
    setPending(false)
  }
  const showSavedSignups = async () => {
    if (completion?.refreshWarning) {
      setPending(true)
      const refreshed = await loadSignup()
      setPending(false)
      if (!refreshed?.signups) return
    }
    setCompletion(null)
    setSignupPanel('saved')
    setJumpTarget('registered')
  }
  const withdraw = async (tag: string) => {
    if (!seasonId || pending || loadingData || !window.confirm(`Withdraw ${tag} from this season's CWL signup?`)) return
    const withdrawnSeason = seasonId
    setPending(true)
    setWithdrawingTag(tag)
    setNotice(null)
    try {
      await api(`/seasons/${encodeURIComponent(withdrawnSeason)}/signups/${tagPath(tag)}`, 'DELETE')
      if (currentSeason.current !== withdrawnSeason) return
      // Update only the confirmed deletion; linked-account lookup is unnecessary.
      // Older reads must not restore a signup that has just been withdrawn.
      signupRequest.current += 1
      setLoadingData(false)
      setSignups(current => current.filter(signup => signup.tag !== tag))
      setDrafts(current => ({ main: Object.fromEntries(Object.entries(current.main).filter(([key]) => key !== tag)), lazy: Object.fromEntries(Object.entries(current.lazy).filter(([key]) => key !== tag)) }))
      setTransfers(current => ({ main: Object.fromEntries(Object.entries(current.main).filter(([key]) => key !== tag)), lazy: Object.fromEntries(Object.entries(current.lazy).filter(([key]) => key !== tag)) }))
      setNotice({ kind: 'success', text: 'Signup withdrawn. Your other signups are unchanged.' })
    } catch (error) {
      if (currentSeason.current === withdrawnSeason) setNotice({ kind: 'error', text: message(error) })
    } finally {
      setPending(false)
      setWithdrawingTag(null)
    }
  }
  const staffAction = (action: () => Promise<unknown>, success: string) => void run(action, success, async () => { await Promise.all([loadStaff(), loadSeasons()]) })

  if (authState === 'loading') return <div className="center-screen"><Brand /><p>Checking Discord sign-in…</p></div>
  const staffMatches = (...values: (string | undefined | null)[]) => values.some(value => value?.toLowerCase().includes(staffSearch.trim().toLowerCase()))
  const visibleHosts = sortClans(clans.filter(clan => (hostStatus === 'all' || clan.archived === (hostStatus === 'archived')) && staffMatches(clan.name, clan.tag) && matchesLeague(clan.cwl_league,clanLeagues)), clanSort)
  const visibleFamily = sortClans(approved.filter(clan => staffMatches(clan.name, clan.tag) && matchesLeague(clan.cwl_league,clanLeagues)), clanSort)
  const visibleStaffSignups = staffSignups.filter(item => (staffPoolFilter === 'all' || item.pool === staffPoolFilter) && staffMatches(item.player_name, item.tag, item.user_id, item.signup_clan_name))
  const staffCount = staffSection === 'hosting' ? visibleHosts.length : staffSection === 'family' ? visibleFamily.length : staffSection === 'signups' ? visibleStaffSignups.length : 0
  const staffLastPage = Math.max(0, Math.ceil(staffCount / 8) - 1)
  const currentStaffPage = Math.min(staffPage, staffLastPage)
  const staffPageSlice = <T,>(items: T[]) => items.slice(currentStaffPage * 8, (currentStaffPage + 1) * 8)
  if (authState === 'error') return <div className="center-screen"><Brand /><div className="card narrow"><h1>CWL is unavailable</h1><p role="alert">{authError}</p><button onClick={() => void loadAuth()}>Retry connection</button></div></div>
  if (authState === 'signed-out') return <main className="center-screen welcome-screen"><Brand /><div className="card login-card"><p className="eyebrow">Warriors United Dashboard</p><h1>Your accounts.<br />Your clans.<br />One place.</h1><p>Check your attacks, set reminders, and sign up for CWL.</p><ul className="welcome-features"><li><DashboardIcon name="war"/><div><strong>Tasks</strong><small>See attacks and events.</small></div></li><li><DashboardIcon name="shield"/><div><strong>My accounts</strong><small>View your linked accounts.</small></div></li><li><DashboardIcon name="trophy"/><div><strong>CWL</strong><small>Sign up and see your assigned clans.</small></div></li></ul>{memberTarget(window.location.search).view !== 'home' && <p className="welcome-destination">After sign-in: <strong>{entryTarget.view === 'signup' ? 'CWL signups' : entryTarget.view === 'assignments' ? 'My clan assignments' : entryTarget.view === 'search' ? 'Search' : entryTarget.view === 'wars' ? 'Wars' : entryTarget.view === 'events' ? 'Events' : 'Tasks'}</strong></p>}<a className="button primary" href={loginPath(window.location.search, !!authError)}>Continue with Discord</a>{fixtureMode && <button className="fixture-button" onClick={() => void api('/dev/login', 'POST').then(loadAuth).catch(error => setAuthError(message(error)))}>Open local test session</button>}{authError && <p className="inline-reason" role="alert">{authError}</p>}<p className="small">Staff tools appear when you have access.</p></div></main>

  if (!session) return <div className="center-screen"><Brand /><p>Checking Discord sign-in…</p></div>

  return <div className="shell">
    <aside className={`sidebar ${menuOpen ? 'open' : ''}`}>
      <div className="brand-wrap"><Brand /><button className="menu-close" onClick={() => setMenuOpen(false)} aria-label="Close menu">×</button></div>
      <div className="community"><img className="community-icon discord-server-icon" src={serverIconUrl} alt="Warriors United server icon" width={38} height={38} /><span><strong>Warriors United</strong><small>Member dashboard</small></span></div>
      <SidebarNavigation key={session.user.id} userId={session.user.id} view={view} canEdit={session.can_edit} permissions={session.dashboard_permissions || []} isOwner={session.is_owner} onNavigate={changeView} />
      <div className="sidebar-foot"><strong>{session.user.display_name || session.user.username}</strong><small>Discord · {session.user.id}</small><button onClick={() => { if (!canLeave()) return; void run(async () => { const pushId = await stopPushOnSignout(); return api('/auth/logout', 'POST', { push_id: pushId }) }, 'Signed out.', async () => { signupRequest.current += 1; setAccounts([]); setSignups([]); setDrafts({main: {}, lazy: {}}); setTransfers({main: {}, lazy: {}}); setCompletion(null); setSession(null); setAuthState('signed-out') }) }}>Sign out</button></div>
    </aside>
    {menuOpen && <button className="scrim" aria-label="Close menu" onClick={() => setMenuOpen(false)} />}
    <div className="workspace">
      <header className="topbar"><button className="menu-open" aria-label="Open menu" aria-expanded={menuOpen} onClick={() => setMenuOpen(true)}>☰</button><div><span className="crumb">Warriors United{navigationSection(view) ? ` / ${navigationSection(view)}` : ''}</span><strong>{view === 'image-gallery' ? 'Image Gallery' : view === 'tickets' ? 'Tickets' : view === 'staff-overview' ? 'Staff overview' : isManagementArea(view) ? managementAreas[view].title : view === 'clan-management' ? 'Family clans' : view === 'strikes' ? 'Strikes' : view === 'replacements' ? 'Replacements' : view === 'text-commands' ? 'Command triggers' : view === 'manage' ? 'Server management' : view === 'home' ? 'Dashboard' : view === 'search' ? 'Search' : view === 'wars' ? 'Wars' : view === 'events' ? 'Events' : view === 'todo' ? 'Tasks' : view === 'signup' ? 'CWL signups' : view === 'assignments' ? 'My clan assignments' : view === 'declaration' ? 'Declaration readiness check' : view === 'roster' ? 'CWL roster' : view === 'reminders' ? 'Messages & reminders' : view === 'publication' ? 'CWL roster' : view === 'participation' ? 'Results & participation' : view === 'bonuses' ? 'Bonus review' : view === 'staff' ? 'Seasons & clans' : view === 'exports' ? 'Export season' : 'Staff access'}</strong></div><AccountIdentity user={session.user} /></header>
      <main>
        {seasonError && <div className="notice error" role="alert">Could not load CWL seasons: {seasonError}<button disabled={seasonsLoading} onClick={() => void loadSeasons()}>Retry seasons</button></div>}
        {fixtureMode && <div className="fixture-banner" role="status">Local fixture data · Development only</div>}
        {(view === 'signup' || view === 'assignments') && <div className="member-nav-tabs" role="group" aria-label="Member sections"><button className={view === 'signup' ? 'active' : ''} aria-pressed={view === 'signup'} onClick={() => changeView('signup')}>My signups</button><button className={view === 'assignments' ? 'active' : ''} aria-pressed={view === 'assignments'} onClick={() => changeView('assignments')}>My clan assignments</button></div>}
        {session.can_edit && ['roster','publication'].includes(view) && <div className="cwl-workspace-nav"><nav className="cwl-roster-tabs" aria-label="Roster sections"><button className={view === 'roster' ? 'active' : ''} aria-current={view === 'roster' ? 'page' : undefined} onClick={() => changeView('roster')}>Build roster</button><button className={view === 'publication' && publicationStep === 'review' ? 'active' : ''} aria-current={view === 'publication' && publicationStep === 'review' ? 'page' : undefined} onClick={() => openPublication('review')}>Finalize roster</button><button className={view === 'publication' && publicationStep === 'announce' ? 'active' : ''} aria-current={view === 'publication' && publicationStep === 'announce' ? 'page' : undefined} onClick={() => openPublication('announce')}>Announcements</button></nav><details className="cwl-more"><summary>More</summary><button onClick={() => changeView('exports')}>Export season</button><button onClick={() => changeView('staff')}>CWL settings</button></details></div>}
        {session.can_edit && ['participation','bonuses','exports'].includes(view) && <div className="cwl-result-nav"><button aria-current={view === 'participation' ? 'page' : undefined} onClick={() => changeView('participation')}>Participation</button><button aria-current={view === 'bonuses' ? 'page' : undefined} onClick={() => changeView('bonuses')}>Bonus medals</button><button aria-current={view === 'exports' ? 'page' : undefined} onClick={() => changeView('exports')}>Export season</button></div>}
        {notice && !(view === 'signup' && review) && <div className={`notice ${notice.kind}`} role="status">{notice.text}<button aria-label="Dismiss message" onClick={() => setNotice(null)}>×</button></div>}
        {session.can_edit && season && ['roster','staff','signup'].includes(view) && <StaffSignupControls key={seasonId} season={season} onChanged={async added=>{await loadSeasons();if(added){setRosterRefresh(n=>n+1);if(view==='staff')await loadStaff();if(view==='signup')await loadSignup()}}} />}
        {view === 'staff-overview' && <StaffOverview onNavigate={(next,season)=>{if(season)setSeasonId(season);changeView(next)}} />}
        {view === 'image-gallery' && <Suspense fallback={<p role="status">Loading images…</p>}><ImageGallery /></Suspense>}
        {view === 'tickets' && <Suspense fallback={<p role="status">Loading tickets…</p>}><TicketBrowser /></Suspense>}
        {view === 'clan-management' && <ClanManagement onDirty={setManageDirty} />}
        {view === 'strikes' && strikePermissions(session.dashboard_permissions, session.is_owner).view && <StrikesWorkspace permissions={session.dashboard_permissions || []} isOwner={session.is_owner} userId={session.user.id} />}
        {view === 'replacements' && strikePermissions(session.dashboard_permissions, session.is_owner).view && <ReplacementWorkspace permissions={session.dashboard_permissions || []} isOwner={session.is_owner} />}
        {view === 'text-commands' && <TextCommands onDirty={setManageDirty} />}
        {isManagementArea(view) && <ServerManagement key={view} area={view} onDirty={setManageDirty} onNavigate={destination => changeView(destination as View)} />}
        {view === 'manage' && <ServerManagement onDirty={setManageDirty} onNavigate={destination => changeView(destination as View)} />}
        {view === 'reminders' && session.can_edit && <><div className="page-head"><div><p className="eyebrow">CWL management</p><h1>Messages &amp; reminders</h1></div><label className="season-choice">Season<select value={seasonId} onChange={event => { if (!reminderDirty || window.confirm('Discard unsaved reminder edits and change season?')) setSeasonId(event.target.value) }}><option value="">Select season</option>{seasons.map(item => <option key={item.id} value={item.id}>{item.label}</option>)}</select></label></div>{seasonId ? <ReminderWorkspace key={seasonId} seasonId={seasonId} archived={season?.status === 'archived'} onDirty={setReminderDirty} /> : <p>Choose a season to manage its reminders.</p>}</>}
        {view === 'search' && <DashboardSearch key={session.user.id} includeFamily={session.can_edit} query={searchQuery} onQuery={value => { setSearchQuery(value); setSearchPage(0) }} kind={searchKind} onKind={value => { setSearchKind(value); setSearchPage(0) }} page={searchPage} onPage={setSearchPage} onTasks={tag => changeView('todo', tag)} />}
        {view === 'todo' && <TodoWorkspace key={`${session.user.id}:${activitySearch}`} userId={session.user.id} initialSearch={activitySearch} initialTab={activityKind} />}
        {view === 'wars' && <WarsWorkspace key={session.user.id} initialType={activityKind === 'cwl' ? 'cwl' : 'regular'} canEdit={session.can_edit} onTasks={(tag,kind) => changeView('todo', tag,kind)} />}
        {view === 'events' && <EventsWorkspace key={session.user.id} canEdit={session.can_edit} onWars={() => changeView('wars', '', 'cwl')} />}
        {view === 'home' && <DashboardHome key={`${session.user.id}:${seasonId}`} session={session} seasonId={seasonId} seasons={seasons} onSeasonChange={setSeasonId} onNavigate={next => { if (next === 'signup' || next === 'saved') { setSignupPanel(next === 'saved' ? 'saved' : 'register'); setSignupStep(1); setPool(null); setCompletion(null); setReview(false) }; changeView(next === 'saved' ? 'signup' : next) }} onStart={(nextPool, tags, freshAccounts, freshSignups) => {
          dashboardPrefill.current = true
          signupRequest.current += 1
          setAccounts(freshAccounts); setSignups(freshSignups); setLoadingData(false); setAccountError(''); setDataError('')
          setDrafts({ main: {}, lazy: {}, [nextPool]: Object.fromEntries(tags.filter(tag => freshAccounts.some(account => account.tag === tag) && !freshSignups.some(signup => signup.tag === tag)).map(tag => [tag, false])) })
          setTransfers({ main: {}, lazy: {} }); setShowSignedUp(false); setPool(nextPool); setSignupPanel('register'); setSignupStep(2); setReview(false); setCompletion(null); changeView('signup')
        }} />}
        {view === 'signup' && <>
          <div className="page-head"><div><p className="eyebrow">Member signup</p><h1>CWL signups</h1><p>{activeCompletion ? "Your season signup is saved." : season && !season.signup_open ? "View your saved signups and CWL clans." : "Sign up your accounts for CWL. Staff will choose their CWL clans."}</p></div><label className="season-choice">Season<select value={seasonId} disabled={pending} onChange={event => { if (!canLeave()) return; setAccounts([]); setSignups([]); setSeasonId(event.target.value); setPool(null); setSignupPanel('register'); setDrafts({ main: {}, lazy: {} }); setTransfers({ main: {}, lazy: {} }); setReview(false); setCompletion(null) }}><option value="">Select a season</option>{seasons.map(item => <option key={item.id} value={String(item.id)}>{item.label}</option>)}</select></label></div>
          {dataError && !activeCompletion && <div className="notice error" role="alert">{dataError}<button disabled={loadingData || pending} onClick={() => void loadSignup()}>Retry</button></div>}
          {seasonsLoading && <p role="status">Loading seasons…</p>}
          {!seasonId && seasons.length > 0 && <div className="card empty"><p>Select a season to view or manage your signups.</p></div>}
          {!seasonsLoading && !seasons.length && !seasonError && <div className="card empty"><h2>No season yet</h2><p>Staff will open a CWL season before members can sign up.</p></div>}
          {season && <>{!activeCompletion && loadingData && <p role="status">Loading linked accounts and saved signups…</p>}<div className="season-banner"><div><span className={`status-dot ${season.signup_open ? 'active' : ''}`} /> <strong>{season.label}</strong><span className="badge">{season.signup_open ? 'Signups open' : 'Signups closed'}</span></div><span>{season.status}</span></div>
            {activeCompletion ? <section className="completion-card card" aria-labelledby="completion-title"><div className="completion-mark" aria-hidden="true">✓</div><p className="eyebrow">Signup complete</p><h2 id="completion-title" ref={completionHeadingRef} tabIndex={-1}>You're signed up</h2><p><strong>{activeCompletion.accounts.length} {activeCompletion.accounts.length === 1 ? 'account is' : 'accounts are'} signed up</strong> for {poolName(activeCompletion.pool)} in {activeCompletion.seasonLabel}.{activeCompletion.moved > 0 && <span> {activeCompletion.moved} {activeCompletion.moved === 1 ? 'account moved' : 'accounts moved'} from the other pool.</span>}</p><div className="completion-accounts">{activeCompletion.accounts.map(account => <div key={account.tag}><strong>{account.name}</strong><small>{account.tag}</small>{account.move_from_pool && <small>Moved from {poolName(account.move_from_pool)} to {poolName(activeCompletion.pool)}</small>}</div>)}</div><p>Your accounts are signed up. Staff will assign your accounts to clans. You can close this page, or sign up more accounts below.</p>{activeCompletion.refreshWarning && <div className="notice error" role="alert">Signup saved, but the latest account list could not be refreshed. You can check your saved signups later.</div>}<div className="completion-actions"><button className="primary" disabled={pending} onClick={() => void showSavedSignups()}>View my signups</button><button disabled={pending} onClick={() => changeView('assignments')}>My clan assignments</button><button disabled={pending} onClick={() => { setCompletion(null); setSignupPanel('register'); setSignupStep(1); setPool(null); setReview(false) }}>Sign up more accounts</button></div></section> : <><div className="signup-panel-tabs" role="group" aria-label="Signup sections"><button className={signupPanel === 'register' ? 'active' : ''} aria-pressed={signupPanel === 'register'} disabled={pending} onClick={() => setSignupPanel('register')}>{season.signup_open ? 'Sign up' : 'Signup guide'}</button><button className={signupPanel === 'saved' ? 'active' : ''} aria-pressed={signupPanel === 'saved'} disabled={pending} onClick={() => { setReview(false); setSignupPanel('saved') }}>My signups <span className="count-pill">{existing.length}</span></button></div>
            {signupPanel === 'register' && !season.signup_open && <section className="signup-guide" aria-label="Signup walkthrough"><p className="eyebrow">CWL signup guide</p><h2>Signups are closed</h2><p>View your saved signups or check your CWL clan. To make a change, ask staff for help.</p><div className="signup-action-buttons"><button onClick={() => setSignupPanel('saved')}>My signups</button><button onClick={() => changeView('assignments')}>My CWL clans</button></div></section>}
            {signupPanel === 'register' && season.signup_open && <div className="signup-flow">
              <section className="signup-guide" aria-label="Signup walkthrough">
                <p className="eyebrow">Signup guide · Step {review ? 3 : signupStep} of 3</p>
                <h2 ref={stepHeadingRef} tabIndex={-1}>{review ? 'Check and sign up' : signupStep === 1 ? 'Choose your CWL' : 'Select your accounts'}</h2>
                <ol>{['Choose CWL', 'Select accounts', 'Check and sign up'].map((label, index) => <li key={label} aria-current={index + 1 === (review ? 3 : signupStep) ? 'step' : undefined}><span>{index + 1}</span>{label}{index < 2 && <b aria-hidden="true">→</b>}</li>)}</ol>
                <p>{review ? 'Check your accounts. Select Sign up to finish.' : signupStep === 1 ? 'Choose Main or Lazy CWL. You can choose a different option for each account.' : `Select the accounts you want to sign up for ${poolName(pool)}.`}</p>
              </section>
              {signupStep === 1 && !review && <div className="pool-choice"><div className="pool-choice-grid"><button className={pool === 'main' ? 'active' : ''} aria-pressed={pool === 'main'} disabled={pending} onClick={() => choosePool('main')}><span className="pool-choice-symbol">◆</span><strong>Main Clan CWL</strong><small>Choose accounts for the Main Clan roster.</small><span className="pool-next">Choose Main CWL →</span></button><button className={pool === 'lazy' ? 'active' : ''} aria-pressed={pool === 'lazy'} disabled={pending} onClick={() => choosePool('lazy')}><span className="pool-choice-symbol">◇</span><strong>Lazy CWL</strong><small>Choose accounts for the Lazy CWL roster.</small><span className="pool-next">Choose Lazy CWL →</span></button></div><p className="small">You can use different accounts for Main and Lazy CWL.</p></div>}{pool && signupStep === 2 && !review && <>
            <div className="section-heading"><div><p className="eyebrow">{poolName(pool)}</p><h2 ref={selectionHeadingRef} tabIndex={-1}>Select linked accounts</h2><p>{pool === 'lazy' ? 'Linked accounts from any clan can join Lazy CWL. Each account can join one CWL pool per season.' : 'Main Clan CWL signup is separate from Lazy CWL. Each account can join one pool per season.'}</p></div><div className="count-pill">{selected.length} selected</div></div>
            {accountError && <div className="notice error" role="alert">{accountError}<button disabled={loadingData || pending} onClick={() => void loadSignup()}>Retry accounts</button></div>}
            {!accountError && !loadingData && accounts.length === 0 && <div className="card empty"><h3>No linked accounts found</h3><AccountLinkHelp busy={loadingData || pending} onRefresh={() => void loadSignup()} /></div>}
            {!accountError && accounts.length > 0 && <>
              <div className="selection-bar"><label className="check-label"><input type="checkbox" checked={showSignedUp} disabled={pending || loadingData} onChange={event => { setShowSignedUp(event.target.checked); setSignupPage(0) }} />Show signed-up accounts ({signups.length})</label><label className="check-label"><input type="checkbox" checked={available.length > 0 && available.every(account => Object.hasOwn(draft, account.tag))} onChange={event => { if (!pool) return; if (event.target.checked) setDraft({...draft, ...selectAllAvailable(matchingAccounts, pool, signups, draft, transferConsent)}); else { const next = {...draft}; for (const account of available) delete next[account.tag]; setDraft(next) } }} disabled={!season.signup_open || season.status !== 'draft' || !available.length || pending || loadingData || !!dataError || !!accountError} />Select all matching accounts ({available.length})</label><button onClick={() => void loadSignup()} disabled={loadingData || pending}>Refresh accounts</button></div>
              <label className="signup-account-search">Find an account or clan<input type="search" value={signupSearch} onChange={event => setSignupSearch(event.target.value)} placeholder="Name, player tag or clan" /></label>
              {visibleAccounts.length > 0 && matchingAccounts.length === 0 && <div className="card empty"><p>No accounts match your search.</p><button onClick={() => setSignupSearch('')}>Clear search</button></div>}
              {visibleAccounts.length === 0 && <div className="card empty"><h3>All linked accounts are signed up</h3><p>Turn on “Show signed-up accounts” to change pools or edit a signup.</p></div>}
              <details className="hub-help"><summary>Missing an account?</summary><AccountLinkHelp busy={loadingData || pending} onRefresh={() => void loadSignup()} /></details>
              <div className="account-list">{pageAccounts.map(account => {
                const signedPool = accountPool(signups, account.tag)
                const movingFrom = transferSource(signups, account.tag, pool!)
                const stagedMove = movingFrom && transferConsent[account.tag] === movingFrom
                const chosen = Object.hasOwn(draft, account.tag)
                const reason = movingFrom ? stagedMove ? `Move to ${poolName(pool)} is pending. Your ${poolName(movingFrom)} signup stays saved until you submit.` : `Already signed up for ${poolName(movingFrom)}. Select to confirm a move to ${poolName(pool)}.` : ''
                return <article className={`account-card ${chosen ? 'chosen' : ''}`} key={account.tag}>
                  <div className="account-top"><label className="account-select"><input type="checkbox" checked={chosen} disabled={!season.signup_open || season.status !== 'draft' || pending || loadingData || !!dataError || !!accountError} onChange={event => { if (!pool) return; const source = transferSource(signups, account.tag, pool); if (event.target.checked && source && !window.confirm(`This account is already signed up for ${poolName(source)}. Do you want to sign up for ${poolName(pool)} instead?`)) return; const next = { ...draft }; if (event.target.checked) next[account.tag] = signups.find(signup => signup.tag === account.tag && signup.pool === pool)?.prefer_crystal_1_or_lower ?? false; else delete next[account.tag]; setTransfers(current => { const updated = { ...current[pool] }; if (event.target.checked && source) updated[account.tag] = source; else delete updated[account.tag]; return { ...current, [pool]: updated } }); setDraft(next) }} /><span><strong className="signed-up-name"><TownHallIcon level={account.town_hall} /><span>{account.name}</span></strong><small>{account.tag}</small></span></label></div>
                  <div className="account-meta"><span>Current clan <strong>{account.current_clan_name || 'None'}{account.current_clan_tag ? ` · ${account.current_clan_tag}` : ''}</strong></span>{signedPool && <span>Signed Up <strong>{poolName(signedPool)}</strong></span>}</div>
                  {reason && <p className="inline-reason">{reason}</p>}
                </article>
              })}</div>
              {lastSignupPage > 0 && <nav className="hub-pagination" aria-label="Signup account pages"><button disabled={currentSignupPage === 0} onClick={() => setSignupPage(currentSignupPage - 1)}>Previous accounts</button><span>Page {currentSignupPage + 1} of {lastSignupPage + 1}</span><button disabled={currentSignupPage === lastSignupPage} onClick={() => setSignupPage(currentSignupPage + 1)}>Next accounts</button></nav>}
              {season.signup_open && <div className="submit-bar"><div><strong>{selected.length} {selected.length === 1 ? 'account' : 'accounts'} selected</strong><small>Selections across all pages · Not saved yet.</small></div><div className="signup-action-buttons"><button disabled={pending} onClick={() => setSignupStep(1)}>← Back</button><button className="primary" disabled={!selected.length || pending || loadingData || !!dataError || !!accountError} onClick={() => setReview(true)}>Continue →</button></div></div>}
            </>}
            </>}
            {signupStep === 2 && !review && (!accounts.length || accountError || !season.signup_open) && <button disabled={pending} onClick={() => setSignupStep(1)}>← Back to CWL choice</button>}
            {review && pool && <section className="signup-review card" aria-label="Review selected accounts">{notice?.kind === 'error' && <div className="notice error" role="alert">{notice.text}</div>}<h3>{poolName(pool)} · {season.label}</h3><p>{selected.length} {selected.length === 1 ? 'account' : 'accounts'} selected. Staff will assign your hosting clans.</p><div className="review-list">{selected.map(item => { const account = accounts.find(candidate => candidate.tag === item.tag)!; return <div className="review-row" key={item.tag}><div><strong className="signed-up-name"><TownHallIcon level={account.town_hall} /><span>{account.name}</span></strong><small>{account.tag} · TH {account.town_hall ?? '—'} · {account.current_clan_name || 'No current clan'}</small></div>{item.move_from_pool && <span className="transfer-review">Moving from {poolName(item.move_from_pool)} to {poolName(pool)}</span>}</div> })}</div><div className="signup-actions submit-bar"><button disabled={pending} onClick={() => setReview(false)}>← Back</button><button className="primary" disabled={!selected.length || pending || loadingData || !season.signup_open || !!dataError || !!accountError} onClick={submit}>{pending ? 'Saving…' : `Sign up ${selected.length} ${selected.length === 1 ? 'account' : 'accounts'}`}</button></div></section>}
            </div>}
            {signupPanel === 'saved' && <section className="registered"><div className="section-heading"><div><p className="eyebrow">Saved this season</p><h2 ref={registeredHeadingRef} tabIndex={-1}>Signed Up accounts</h2></div></div>{loadingData ? <p role="status">Loading saved signups…</p> : dataError ? <p>Your saved signups could not be checked. Retry above.</p> : existing.length ? <div className="registered-grid">{existing.map(signup => <div className="card registered-card" key={signup.tag}><div><strong className="signed-up-name"><TownHallIcon level={accounts.find(account => account.tag === signup.tag)?.town_hall ?? signup.town_hall} /><span>{signup.player_name || accounts.find(account => account.tag === signup.tag)?.name || signup.tag}</span></strong><small>{signup.tag} · {poolName(signup.pool)}</small><small>Clan at signup: {signup.signup_clan_name || signup.signup_clan_tag || 'Not available'}</small></div>{season.signup_open && <div className="registered-actions"><button disabled={pending || loadingData || !!accountError || !accounts.some(account => account.tag === signup.tag)} onClick={() => { if (signupDirty && !window.confirm('Review this pool change and clear your other unsubmitted selections?')) return; const destination = signup.pool === 'main' ? 'lazy' : 'main'; setDrafts({main: {}, lazy: {}, [destination]: {[signup.tag]: signup.prefer_crystal_1_or_lower}}); setTransfers({main: {}, lazy: {}, [destination]: {[signup.tag]: signup.pool}}); setPool(destination); setShowSignedUp(true); setSignupPanel('register'); setSignupStep(2); setReview(true); setNotice(null) }}>Change CWL pool</button><button className="withdraw-button" disabled={pending || loadingData} onClick={() => void withdraw(signup.tag)}>{withdrawingTag === signup.tag ? 'Withdrawing…' : 'Withdraw signup'}</button></div>}</div>)}</div> : <div className="card empty"><p>No signed-up accounts for this season.</p>{season.signup_open && <button onClick={() => { setSignupPanel('register'); setSignupStep(1) }}>Choose accounts</button>}</div>}</section>}
          </>}
        </>}
        </>}
        {view === 'assignments' && <MemberAssignments onSignup={() => { setSignupPanel('register'); changeView('signup') }} seasonId={seasonId} seasons={seasons} onSeasonChange={setSeasonId} />}
        {view === 'exports' && session.can_edit && <ExportWorkspace seasonId={seasonId} seasons={seasons} onSeasonChange={setSeasonId} />}
        {view === 'declaration' && session.can_edit && <><div className="page-head"><div><p className="eyebrow">CWL</p><h1>Declaration readiness check</h1></div><label>Season<select value={seasonId} onChange={e=>setSeasonId(e.target.value)}>{seasons.map(item=><option key={item.id} value={item.id}>{item.label}</option>)}</select></label></div>{seasonId && <ArrivalCheck key={seasonId} seasonId={seasonId}/>}</>}
        {view === 'publication' && session.can_edit && <PublicationWorkspace onDirty={setPublicationDirty} step={publicationStep} onStepChange={setPublicationStep} onFix={filter => { setRosterReadiness(filter); changeView('roster') }} seasonId={seasonId} seasons={seasons} onSeasonChange={id => { if (!publicationDirty || window.confirm('Discard unsaved announcement changes?')) setSeasonId(id) }} />}
        {view === 'participation' && session.can_edit && <ParticipationWorkspace onDirty={setCwlDirty} seasonId={seasonId} seasons={seasons} onSeasonChange={setSeasonId} />}
        {view === 'bonuses' && session.can_edit && <BonusWorkspace onDirty={setCwlDirty} seasonId={seasonId} seasons={seasons} onSeasonChange={setSeasonId} />}
        {view === 'roster' && session.can_edit && <RosterWorkspace onDirty={setCwlDirty} key={`${seasonId}-${rosterRefresh}`} initialReadiness={rosterReadiness} onReviewPublication={() => { setPublicationStep('review'); changeView('publication') }} seasonId={seasonId} seasons={seasons} onSeasonChange={id => { setSeasonId(id); setPool(null); setSignupPanel('register'); setDrafts({ main: {}, lazy: {} }); setTransfers({ main: {}, lazy: {} }); setReview(false); setCompletion(null) }} />}
        {view === 'staff' && session.can_edit && <div className="staff-workspace"><div className="page-head"><div><p className="eyebrow">Staff tools</p><h1>Seasons & clans</h1><p>Choose a section to manage this season or its clans.</p></div><label className="season-choice">Season<select value={seasonId} onChange={event => { if (!canLeave()) return; setAccounts([]); setSignups([]); setSeasonId(event.target.value); setPool(null); setSignupPanel('register'); setDrafts({ main: {}, lazy: {} }); setTransfers({ main: {}, lazy: {} }); setReview(false); setCompletion(null) }}><option value="">Select season</option>{seasons.map(item => <option key={item.id} value={String(item.id)}>{item.label}</option>)}</select></label></div>{staffError && <div className="notice error" role="alert">{staffError}<button onClick={() => void loadStaff()}>Retry</button></div>}{staffLoading && <p>Loading clan directory…</p>}
          <div className="staff-section-menu" role="group" aria-label="Seasons and clans sections">
            {([['hosting', 'Hosting clans', clans.filter(clan => !clan.archived).length], ['season', 'Season settings', null], ['family', 'Family clans', approved.length], ['signups', 'Signup pools', staffSignups.length]] as const).map(([key, label, count]) => <button key={key} aria-pressed={staffSection === key} onClick={() => { setStaffSection(key); setStaffSearch(''); setStaffPage(0) }}>{label}{count !== null && <span>{count}</span>}</button>)}
          </div>
          {staffSection !== 'season' && <div className="staff-section-tools"><label>Search {staffSection === 'signups' ? 'accounts' : 'clans'}<input value={staffSearch} onChange={event => setStaffSearch(event.target.value)} placeholder={staffSection === 'signups' ? 'Name, player tag, or Discord ID' : 'Clan name or tag'} /></label>{(staffSection === 'hosting' || staffSection === 'family') && <label>Sort clans<select value={clanSort} onChange={event=>setClanSort(event.target.value as ClanSort)}>{clanSortOptions.map(option=><option key={option.value} value={option.value}>{option.label}</option>)}</select></label>}{staffSection === 'hosting' && <label>Show<select value={hostStatus} onChange={event => setHostStatus(event.target.value)}><option value="active">Active clans</option><option value="archived">Archived clans</option><option value="all">All clans</option></select></label>}{staffSection === 'signups' && <label>Signup pool<select value={staffPoolFilter} onChange={event => setStaffPoolFilter(event.target.value)}><option value="all">Both pools</option><option value="main">Main Clan CWL</option><option value="lazy">Lazy CWL</option></select></label>}</div>}
          {(staffSection==='hosting'||staffSection==='family')&&<div className="clan-filter-bar"><FilterPicker label="CWL leagues" options={[...new Set(sortClans(staffSection==='hosting'?clans:approved,'league_desc').map(clan=>leagueValue(clan.cwl_league)))]} selected={clanLeagues} onChange={setClanLeagues}/><button onClick={()=>{setClanLeagues([]);setStaffSearch('');setHostStatus('active')}}>Clear filters</button><small>{staffCount} clans match</small></div>}
          <div className="staff-section-content"><section className="card" hidden={staffSection !== 'season'}><h2>Season settings</h2>{season && <div className="staff-row"><div><strong>{season.label}</strong><small>{season.signup_open ? 'Members can sign up' : 'Signups closed'}</small></div><button disabled={pending} onClick={() => staffAction(() => api(`/seasons/${encodeURIComponent(season.id)}`, 'PATCH', { signup_open: !season.signup_open }), season.signup_open ? 'Signups closed.' : 'Signups opened.')}>{season.signup_open ? 'Close signups' : 'Open signups'}</button></div>}<details className="staff-create-season"><summary>Create another season</summary><form onSubmit={event => { event.preventDefault(); if (!newSeasonLabel.trim()) return; staffAction(() => api('/seasons', 'POST', { label: newSeasonLabel.trim(), signup_open: false }), 'Season created.'); setNewSeasonLabel('') }}><label>New season label<input value={newSeasonLabel} onChange={event => setNewSeasonLabel(event.target.value)} placeholder="November 2026" required /></label><button className="primary" disabled={pending}>Create season</button></form></details></section>
          <section className="card" hidden={staffSection !== 'family'}><div className="card-heading"><h2>Family clans</h2><button disabled={staffLoading} onClick={() => void loadStaff()}>Refresh</button></div><p className="small">Accounts outside these family clans are marked for staff review. They can still sign up.</p>{approvedError ? <div className="notice error" role="alert">{approvedError}</div> : <p className="small">{approvedSource === 'bot_mongo' ? 'Synced with Discord' : approvedSource === 'fixture' ? 'Demo data' : 'Loading source…'}{approvedCheckedAt ? ` · Checked ${new Date(approvedCheckedAt).toLocaleString()}` : ''}</p>}{!approvedError && approved.length === 0 && !staffLoading && <p className="small">No family clans found.</p>}{staffPageSlice(visibleFamily).map(clan => <div className="staff-row" key={clan.tag}><div><strong>{clan.name}</strong><small>CWL: {clan.cwl_league || 'League unavailable'}{clan.cwl_league_stale && clan.cwl_league ? ' · last known' : ''}</small><small>{clan.tag}</small></div></div>)}</section>
          <section className="card" hidden={staffSection !== 'hosting'}><h2>Hosting clan directory</h2><p className="small">Add a clan and choose its default: Main or Lazy. Season settings can differ. Set weight ranges and capacity in Roster builder → Edit clan ranges. Archiving stops new placements and keeps history.</p><form className="inline-form" onSubmit={event => { event.preventDefault(); if (!newClanTag.trim() || !newClanPool) return; staffAction(() => api('/clans', 'POST', { tag: newClanTag.trim(), pool: newClanPool }), 'Hosting clan added.'); setNewClanTag('') }}><label>Clan tag<input value={newClanTag} onChange={event => setNewClanTag(event.target.value)} placeholder="#CLANTAG" required /></label><label>CWL pool<select required value={newClanPool} onChange={event => setNewClanPool(event.target.value as Pool)}><option value="">Choose Main or Lazy</option><option value="main">Main Clan CWL</option><option value="lazy">Lazy CWL</option></select></label><button className="primary" disabled={pending}>Add clan</button></form>{staffPageSlice(visibleHosts).map(clan => <div className="staff-row" key={clan.tag}><div><strong>{clan.name}</strong><small>CWL: {clan.cwl_league || 'League unavailable'}{clan.cwl_league_stale && clan.cwl_league ? ' · last known' : ''}</small><small>{clan.tag} · {clan.archived ? 'Archived' : 'Active'}</small></div><label>Default CWL pool<select aria-label={`Default CWL pool for ${clan.name}`} value={clan.pool || ''} disabled={pending} onChange={event => staffAction(() => api(`/clans/${tagPath(clan.tag)}`, 'PATCH', { pool: event.target.value }), 'Hosting clan pool saved. Existing season overrides are preserved.')}><option value="" disabled>Not set</option><option value="main">Main Clan CWL</option><option value="lazy">Lazy CWL</option></select></label><button disabled={pending} onClick={() => staffAction(() => api(`/clans/${tagPath(clan.tag)}`, 'PATCH', { archived: !clan.archived }), clan.archived ? 'Clan restored.' : 'Clan archived.')}>{clan.archived ? 'Restore' : 'Archive'}</button></div>)}</section>

          <section className="card staff-pool" hidden={staffSection !== 'signups'}><h2>Signup pools</h2><p className="small">Browse signups here. Use Roster builder to assign accounts to hosting clans.</p>{staffSignups.length ? <div className="pool-columns">{(['main', 'lazy'] as Pool[]).filter(group => staffPageSlice(visibleStaffSignups).some(item => item.pool === group)).map(group => <div key={group}><h3>{poolName(group)} · {staffSignups.filter(item => item.pool === group).length}</h3>{staffPageSlice(visibleStaffSignups).filter(item => item.pool === group).map(item => <div className="staff-row" key={`${item.user_id}-${item.tag}`}><div><StaffPlayerButton seasonId={seasonId} tag={item.tag} onChanged={loadStaff}>{item.player_name || item.tag}</StaffPlayerButton><small>{item.tag} · {item.user_id ? `Discord ${item.user_id}` : 'No Discord account'} · TH {item.town_hall ?? '—'}</small><small>Signup clan: {item.signup_clan_name || item.signup_clan_tag || 'Unavailable'}</small>{item.family_clan_status === 'outside' && <small className="outside-flag">Not in an approved family clan</small>}{item.family_clan_status === 'unknown' && <small className="unknown-flag">Family clan status unavailable</small>}</div></div>)}</div>)}</div> : <p>No account signups for this season.</p>}</section></div>
{staffSection !== 'season' && <div className="staff-page-controls"><p role="status">{staffCount ? `${currentStaffPage * 8 + 1}–${Math.min((currentStaffPage + 1) * 8, staffCount)} of ${staffCount}` : 'No matching results.'}</p>{staffCount > 8 && <div><button disabled={currentStaffPage === 0} onClick={() => setStaffPage(currentStaffPage - 1)}>Previous</button><span>Page {currentStaffPage + 1} of {staffLastPage + 1}</span><button disabled={currentStaffPage >= staffLastPage} onClick={() => setStaffPage(currentStaffPage + 1)}>Next</button></div>}</div>}
        </div>}
        {view === 'access' && session.is_owner && <AccessSettings />}
      </main>
    </div>

  </div>
}
function Brand() { return <div className="brand"><img className="emblem discord-server-icon" src={serverIconUrl} alt="Warriors United server icon" width={39} height={39} /><span><strong>WARRIORS UNITED</strong><small>SERVER DASHBOARD</small></span></div> }
export default App
