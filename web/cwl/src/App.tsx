import CwlPageHeader from "./CwlPageHeader"
import useConfirmDialog from "./useConfirmDialog"
import RosterMenu from "./rosterUi/Menu"
import CwlNextLink from "./CwlNextLink";
import "./MemberRefreshNote.css"
import { memberSignupsOpen } from "./memberSeason"
import DashboardStorageStatus from './DashboardStorageStatus'
import type { ClanRoute } from "./clanManagement/routes";
import SignupReviewHeading from "./SignupReviewHeading"
import AccountMenu from "./AccountMenu"
import MemberSeasonLine from "./MemberSeasonLine"
import { reviewPoolSelection } from "./signupReview"
import CwlStepStrip, { MemberStepStrip } from "./CwlStepStrip"
import MemberTour from "./memberTour/MemberTour"
import { isTourReadOnly, setTourReadOnly, type TourPage } from "./memberTour/session"
import type { PublicationDraft } from "./publication"
import { clearJourneyState } from './journeyState'
import { loadAccountDisplay, mergeAccountProgress } from './accountDisplay'
import { DashboardPermissions } from './DashboardPermissions'
import FwaSignupDialog from './FwaSignupDialog'
import {saveSignupMoves, type SignupMove} from './signupMoves'
import {withdrawInOrder, withdrawConfirmation} from './signupWithdrawal'
import SavedSignups from './SavedSignups'
import SavedSignupStatus from './SavedSignupStatus'
import AttentionSummary from './AttentionSummary'
import CwlPoolTabs from './CwlPoolTabs'
import SignupWalkthrough from './SignupWalkthrough'
import AccountLinkHelp from './AccountLinkHelp'
import DashboardIcon from './DashboardIcon'
import { strikePermissions } from './strikePermissions'
import {isManagementArea, managementAreas} from './managementAreas'
import SidebarNavigation, { navigationSection, navigationLabel, visibleNavigationSections, type DashboardView } from './SidebarNavigation'
import { loginPath } from './memberLinks'
import { DashboardHistory, dashboardTarget, seasonViews, activityContext } from './dashboardHistory'
import './Welcome.css'
import './SignupFlow.css'
import TownHallIcon from './TownHallIcon'
import type { ReadinessFilter } from './readiness'
import './staffNavigation.css'
import './sidebar.css'
import { AccountIdentity } from './AccountIdentity'
import { useMobileNavigation } from './useMobileNavigation'
import { stopPushOnSignout } from './webPush'
import RouteLoadBoundary from './RouteLoadBoundary'
import { lazy, Suspense, useMemo, useCallback, useEffect, useRef, useState } from 'react'
import OwnerPrankBoundary from './ownerPrank/OwnerPrankBoundary'
import ConfirmDialog from './ConfirmDialog'
import { api, ApiError, setCsrfToken, type Account, type Pool, type Season, type Session, type Signup } from './api'
import { unsignedAccounts, reconcileNewSignupDraft, clearSubmittedDraft, selectedEntries, submittedSummary, type Draft } from './signup'

// Each destination loads only when opened. Keep shell, auth, and signup form helpers eager.
import StaffDetailsHost from "./StaffDetailsHost"
const WeightTrial = lazy(() => import('./weightTrial/WeightTrial'))
const SeasonsPage = lazy(() => import('./SeasonsPage'))
const WarsWorkspace = lazy(() => import('./activity/WarsWorkspace'))
const EventsWorkspace = lazy(() => import('./activity/EventsWorkspace'))
const BaseBank = lazy(() => import('./BaseBank'))
const DashboardSearch = lazy(() => import('./DashboardSearch'))
const ArrivalCheck = lazy(() => import('./ArrivalCheck'))
const StaffOverview = lazy(() => import('./StaffOverview'))
const ClanManagement = lazy(() => import('./ClanManagement'))
const StrikesWorkspace = lazy(() => import('./StrikesWorkspace'))
const TextCommands = lazy(() => import('./TextCommands'))
const AccessSettings = lazy(() => import('./AccessSettings'))
const DashboardIssues = lazy(() => import('./DashboardIssues'))
const MembersPage = lazy(() => import('./members/MembersPage'))
const ServerManagement = lazy(() => import('./ServerManagement'))
const ReminderWorkspace = lazy(() => import('./ReminderWorkspace'))
const TodoWorkspace = lazy(() => import('./TodoWorkspace'))
const DashboardHome = lazy(() => import('./DashboardHome'))
const ExportWorkspace = lazy(() => import('./ExportWorkspace'))
const RosterWorkspace = lazy(() => import('./RosterWorkspace'))
const PublicationWorkspace = lazy(() => import('./PublicationWorkspace'))
const ParticipationWorkspace = lazy(() => import('./ParticipationWorkspace'))
const BonusWorkspace = lazy(() => import('./BonusWorkspace'))
const MemberAssignments = lazy(() => import('./MemberAssignments'))
const ImageGallery = lazy(() => import('./CommandImageLibrary').then(module => ({default:module.ImageGallery})))
const TicketBrowser = lazy(() => import('./TicketBrowser'))
const OwnerPrank = lazy(() => import('./ownerPrank/OwnerPrank'))
const ModerationWorkspace = lazy(() => import('./ModerationWorkspace'))
type View = DashboardView
type Notice = { kind: 'success' | 'error'; text: string }
type Completion = { seasonId: string; seasonLabel: string; pool: Pool; accounts: ReturnType<typeof submittedSummary>; refreshWarning: boolean }
const poolName = (pool: Pool | null) => pool === 'lazy' ? 'Lazy CWL' : pool === 'main' ? 'Main CWL' : 'CWL'
const message = (error: unknown) => error instanceof Error ? error.message : 'Something went wrong. Try again.'
const tagPath = (tag: string) => encodeURIComponent(tag)

function App() {
  const [session, setSession] = useState<Session | null>(null)
  const [authState, setAuthState] = useState<'loading' | 'signed-out' | 'error' | 'ready'>('loading')
  const [authError, setAuthError] = useState(() => new URLSearchParams(window.location.search).get('signin_error') === 'discord' ? 'Discord sign-in did not finish. Try again.' : '')
  const [fixtureMode, setFixtureMode] = useState(false)
  const [entryAccount, setEntryAccount] = useState(() => new URLSearchParams(window.location.search).get("account") || new URLSearchParams(window.location.search).get("member"))
  const [entryTarget] = useState(() => dashboardTarget(window.location.search, window.location.pathname))
  const [publicationDirty, setPublicationDirty] = useState(false)
  const [publicationBusy, setPublicationBusy] = useState(false)
  const [publicationStep, setPublicationStep] = useState<'review' | 'announce'>(entryTarget.step || 'review')
  const [rosterVisit, setRosterVisit] = useState(0)
  const [flowPublication, setFlowPublication] = useState<{season: string; draft: PublicationDraft} | null>(null)
  const [rosterReadiness, setRosterReadiness] = useState<ReadinessFilter>('all')
  const [view, setView] = useState<View>(entryTarget.view)
  const [rosterBusy, setRosterBusy] = useState(false)
  const [reminderDirty, setReminderDirty] = useState(false)
  const [menuOpen, setMenuOpen] = useState(false)
  const [tourActive, setTourActive] = useState(false)
  const [prankReadyUser, setPrankReadyUser] = useState<string | null>(null)
  const [prankReplayAvailable, setPrankReplayAvailable] = useState(false)
  const [prankReplaySignal, setPrankReplaySignal] = useState(0)
  const { drawerRef, triggerRef, mobile } = useMobileNavigation(menuOpen, () => setMenuOpen(false), Boolean(session))
  const [seasons, setSeasons] = useState<Season[]>([])
  const [staffSeasonId, setSeasonId] = useState(entryTarget.season)
  const [memberSeason, setMemberSeason] = useState<{season_id: number | null; revision: number}>({season_id: null, revision: 0})
  const seasonId = seasonViews.has(view) ? staffSeasonId : String(memberSeason.season_id || '')
  const [fwaBlocked, setFwaBlocked] = useState(false)
  const [pool, setPool] = useState<Pool | null>(null)
  const [signupSearch, setSignupSearch] = useState('')
  const [signupPage, setSignupPage] = useState(0)
  useEffect(() => { setSignupPage(0) }, [signupSearch, pool, seasonId])
  const [signupPanel, setSignupPanel] = useState<'register' | 'saved'>(entryTarget.signupPanel || 'register')
  useEffect(() => {
    document.title = `${view === 'signup' && signupPanel === 'saved' ? 'My signups' : navigationLabel(view, publicationStep)} · Warriors United`
  }, [view, publicationStep, signupPanel])
  const [accounts, setAccounts] = useState<Account[]>([])
  const [accountsLoadedFor, setAccountsLoadedFor] = useState<string | null>(null)
  useEffect(() => { if (view !== "signup") setAccountsLoadedFor(null) }, [view])
  const [signups, setSignups] = useState<Signup[]>([])
  const dashboardPrefill = useRef(false)
  const signupRequest = useRef(0)
  const currentSeason = useRef('')
  currentSeason.current = seasonId
  const [signupStep, setSignupStep] = useState<1 | 2>(1)
  const [returnToReview, setReturnToReview] = useState(false)
  const [poolRemoved, setPoolRemoved] = useState<string[]>([])
  const stepHeadingRef = useRef<HTMLHeadingElement>(null)
  useEffect(() => { setReturnToReview(false); setPoolRemoved([]); setSignupStep(1); setPool(null); setReview(false); setCompletion(null); setAccounts([]); setAccountsLoadedFor(null); setSignups([]); setSavedSignupsLoaded(false); setDrafts({main: {}, lazy: {}}) }, [seasonId, session?.user.id])
  const [drafts, setDrafts] = useState<Record<Pool, Draft>>({ main: {}, lazy: {} })
  const selectionRef = useRef({ drafts })
  selectionRef.current = { drafts }
  const signupBusy = useRef(false)
  const [accountError, setAccountError] = useState('')
  const [seasonError, setSeasonError] = useState('')
  const [seasonsLoading, setSeasonsLoading] = useState(true)
  const [seasonsKnown, setSeasonsKnown] = useState(false)
  const [dataError, setDataError] = useState('')
  const [loadingData, setLoadingData] = useState(false)
  const [savedSignupsLoaded, setSavedSignupsLoaded] = useState(false)
  const [pending, setPending] = useState(false)
  const [review, setReview] = useState(false)
  const [completion, setCompletion] = useState<Completion | null>(null)
  const [jumpTarget, setJumpTarget] = useState<'selection' | 'registered' | null>(null)
  const completionHeadingRef = useRef<HTMLHeadingElement>(null)
  const selectionHeadingRef = useRef<HTMLHeadingElement>(null)
  const registeredHeadingRef = useRef<HTMLHeadingElement>(null)
  const [notice, setNotice] = useState<Notice | null>(null)
  const loadAuth = useCallback(async () => {
    setAuthState('loading')
    try {
      const me = await api<Session>('/auth/me')
      setCsrfToken(me.csrf_token)
      setSession(me)
      setMenuOpen(false)
      setNotice(null)
      setAuthState('ready')
    } catch (error) {
      setSession(null)
      if (error instanceof ApiError && error.status === 401) setAuthState('signed-out')
      else { setAuthError(message(error)); setAuthState('error') }
    }
  }, [])
  useEffect(() => { void loadAuth() }, [loadAuth])
  useEffect(() => {
    if (!session) return
    let active = true, pending = false
    const uid = session.user.id
    const refreshAccess = async () => {
      if (document.hidden || pending) return
      pending = true
      try {
        const fresh = await api<Session>('/auth/me')
        if (active && fresh.user.id === uid) setSession(current => current?.user.id === uid ? fresh : current)
      } catch (error) {
        if (active && error instanceof ApiError && error.status === 401) { setSession(null); setAuthState('signed-out') }
      } finally { pending = false }
    }
    const timer = window.setInterval(() => { void refreshAccess() }, 60000)
    window.addEventListener('focus', refreshAccess)
    window.addEventListener('dashboard-access-changed', refreshAccess)
    return () => { active = false; window.clearInterval(timer); window.removeEventListener('focus', refreshAccess); window.removeEventListener('dashboard-access-changed', refreshAccess) }
  }, [session?.user.id])
  useEffect(() => {
    if (!session) return
    const allowed = visibleNavigationSections(session.can_edit, session.is_owner, session.dashboard_permissions || []).some(section => section.items.some(item => item.view === (view === 'replacements' ? 'strikes' : view)))
    if (!allowed) { setView('home'); setCwlDirty(false); setNotice({kind:'error', text:'You do not have access to that page. Select an available page.'}) }
  }, [session, view])

  useEffect(() => { if (['localhost', '127.0.0.1', '[::1]'].includes(window.location.hostname)) void api<{ dev_fixture: boolean }>('/config').then(result => setFixtureMode(result.dev_fixture)).catch(() => setFixtureMode(false)) }, [])
  useEffect(() => {
    const close = (event: KeyboardEvent) => { if (event.key === 'Escape' && !event.defaultPrevented && !document.querySelector(".account-menu-popover")) { setMenuOpen(false); setReview(false) } }
    window.addEventListener('keydown', close)
    return () => window.removeEventListener('keydown', close)
  }, [])

  const seasonRequest = useRef(0)
  const loadSeasons = useCallback(async () => {
    const requestId = ++seasonRequest.current
    setSeasonsLoading(true)
    try {
      const result = await api<{ seasons: Season[]; member_season: {season_id: number | null; revision: number} }>('/seasons')
      if (requestId !== seasonRequest.current) return
      setSeasons(result.seasons)
      setSeasonsKnown(true)
      setMemberSeason(result.member_season)
      if (seasonViews.has(entryTarget.view) && entryTarget.season && !result.seasons.some(item => String(item.id) === entryTarget.season)) setNotice({kind:'error', text:'The season in this link is not available. Check the season shown before signing up.'})
      setSeasonId(current => result.seasons.some(season => String(season.id) === current) ? current : String(result.seasons[0]?.id || ''))
      setSeasonError('')
    } catch (error) {
      if (requestId === seasonRequest.current) {
        if (error instanceof ApiError && [401, 403].includes(error.status)) {
          setSeasons([])
          setSeasonId('')
          setMemberSeason({ season_id: null, revision: 0 })
          setSeasonsKnown(false)
        }
        setSeasonError(message(error))
      }
    }
    finally { if (requestId === seasonRequest.current) setSeasonsLoading(false) }
  }, [])
  useEffect(() => {
    if (!session) return
    let pending = false
    const refresh = async (initial = false) => {
      if (pending || (!initial && document.hidden)) return
      pending = true
      try { await loadSeasons() }
      finally { pending = false }
    }
    void refresh(true)
    const onVisible = () => { if (!document.hidden) void refresh() }
    const timer = window.setInterval(() => void refresh(), 60000)
    window.addEventListener('focus', onVisible)
    document.addEventListener('visibilitychange', onVisible)
    return () => {
      seasonRequest.current++
      clearInterval(timer)
      window.removeEventListener('focus', onVisible)
      document.removeEventListener('visibilitychange', onVisible)
    }
  }, [session?.user.id, loadSeasons])

  // Access polling replaces the session object. Only a different member should
  // restart signup reads; otherwise it interrupts the member's current draft.
  const loadSignup = useCallback(async (force = true) => {
    if (!seasonId) return
    setLoadingData(true)
    setReview(false)
    const requestId = ++signupRequest.current
    setAccountError('')
    setDataError('')
    const [accountsResult, signupsResult] = await Promise.allSettled([
      loadAccountDisplay(snapshot => { if (snapshot.total !== null || !snapshot.updating) setAccounts(previous => mergeAccountProgress(previous, snapshot)) },
        () => requestId === signupRequest.current && currentSeason.current === seasonId, force),
      api<{ signups: Signup[] }>(`/seasons/${encodeURIComponent(seasonId)}/signups`).then(result => {
        if (requestId === signupRequest.current && currentSeason.current === seasonId) {
          setSignups(result.signups)
          setSavedSignupsLoaded(true)
        }
        return result
      }, error => {
        if (requestId === signupRequest.current && currentSeason.current === seasonId) setDataError(message(error))
        throw error
      }),
    ])
    if (requestId !== signupRequest.current || currentSeason.current !== seasonId) return { all: false, signups: false }
    let freshAccounts: Account[] | null = null
    let freshSignups: Signup[] | null = null
    if (accountsResult.status === 'fulfilled') { freshAccounts = accountsResult.value.accounts; setAccounts(freshAccounts); setAccountsLoadedFor(`${session?.user.id || ""}:${seasonId}`) }
    else { setAccountsLoadedFor(null); if (accountsResult.reason instanceof ApiError && [401,403].includes(accountsResult.reason.status)) setAccounts([]); setAccountError(message(accountsResult.reason)) }
    if (signupsResult.status === 'fulfilled') { freshSignups = signupsResult.value.signups; setSignups(freshSignups) }
    else { setSignups([]); setDataError(message(signupsResult.reason)) }
    if (freshAccounts !== null && freshSignups !== null) {
      const previous = selectionRef.current
      const main = reconcileNewSignupDraft(previous.drafts.main, freshAccounts, freshSignups)
      const lazy = reconcileNewSignupDraft(previous.drafts.lazy, freshAccounts, freshSignups)
      setDrafts({ main: main, lazy: lazy })
      if (Object.keys(main).length + Object.keys(lazy).length < Object.keys(previous.drafts.main).length + Object.keys(previous.drafts.lazy).length) setNotice({kind:'error', text:'Some selections changed because account links or saved pools changed. Check your accounts before continuing.'})
    }
    setLoadingData(false)
    return { all: freshAccounts !== null && freshSignups !== null, signups: freshSignups !== null }
  }, [seasonId, session?.user.id])
  useEffect(() => {
    if (!session || !seasonId || view !== 'signup') return
    if (dashboardPrefill.current) { dashboardPrefill.current = false; return () => { signupRequest.current += 1 } }
    void loadSignup(false)
    return () => { signupRequest.current += 1 }
  }, [session?.user.id, seasonId, view, loadSignup])

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
  const accountsReady = accountsLoadedFor === `${session?.user.id || ""}:${seasonId}`
  const season = seasons.find(item => String(item.id) === seasonId)
  const draft = pool ? drafts[pool] : {}
  const visibleAccounts = unsignedAccounts(accounts, signups)
  const matchingAccounts = visibleAccounts.filter(account => [account.name, account.tag, account.current_clan_name, account.current_clan_tag].some(value => value?.toLowerCase().includes(signupSearch.trim().toLowerCase())))
  const lastSignupPage = Math.max(0, Math.ceil(matchingAccounts.length / 12) - 1)
  const currentSignupPage = Math.min(signupPage, lastSignupPage)
  const pageAccounts = matchingAccounts.slice(currentSignupPage * 12, (currentSignupPage + 1) * 12)
  const selected = pool ? selectedEntries(visibleAccounts.filter(account => pool !== 'main' || account.current_clan_type !== 'FWA'), draft) : []
  const available = pool ? matchingAccounts.filter(account => pool !== 'main' || account.current_clan_type !== 'FWA') : []
  const existing = signups
  const activeCompletion = completion?.seasonId === seasonId ? completion : null
  const setDraft = (next: Draft) => { if (!pool) return; setDrafts(current => ({ ...current, [pool]: next })); setReview(false); setNotice(null) }
  const choosePool = async (next: Pool) => {
    if (returnToReview) {
      const { retained, removed } = reviewPoolSelection(draft, next, accounts, signups);
      setPool(next);
      setDrafts({ main: {}, lazy: {}, [next]: retained });
      setPoolRemoved(removed);
      setSignupStep(2);
      setSignupPanel("register");
      setReview(Object.keys(retained).length > 0);
      setReturnToReview(false);
      return;
    }
    if (pool && next !== pool && Object.keys(draft).length && !(await confirmCwl('Change CWL pool and clear your unsubmitted selections? Saved signups stay unchanged.', 'Change CWL pool'))) return;
    setSignupStep(2);
    setPoolRemoved([]);
    if (pool === next) return;
    setSignupPanel('register'); setPool(next); setDrafts({ main: {}, lazy: {} }); setReview(false);
  };
  const changeReviewStep = (step: 1 | 2) => {
    setReturnToReview(step === 1);
    setReview(false);
    setSignupStep(step);
  };
  const [savedSignupDirty, setSavedSignupDirty] = useState(false)
  const [weightState, setWeightState] = useState({ count: 0, busy: false });
  const [weightTarget, setWeightTarget] = useState({
    player: entryTarget.weightPlayer,
    clan: entryTarget.weightClan,
  });
  const [pendingWeightLeave, setPendingWeightLeave] = useState<
    null | (() => void)
  >(null);
  const weightEditFocus = useRef<HTMLElement | null>(null);
  const [familyRoute, setFamilyRoute] = useState<ClanRoute | undefined>(entryTarget.familyClan);
  const [familyWorking, setFamilyWorking] = useState(false);
  const [familyVisit, setFamilyVisit] = useState(0);
  const [pendingClanLeave, setPendingClanLeave] = useState<null | (() => void)>(null);
  const [manageDirty, setManageDirty] = useState(false)
  const [strikeWorking, setStrikeWorking] = useState(false)
  const flowMemory = useMemo(
    () => ({ strikes: new Map<string, unknown>(), replacements: new Map<string, unknown>() }),
    [session?.user.id],
  );
  const [replacementTag, setReplacementTag] = useState(entryTarget.replacementTag || "");
  const [strikeTag, setStrikeTag] = useState(entryTarget.strikeTag || "");
  const [strikeFilterState, setStrikeFilterState] = useState(entryTarget.strikeState || "");
  const [flowFrom, setFlowFrom] = useState(entryTarget.flowFrom);
  const [replacementClan, setReplacementClan] = useState(entryTarget.replacementClan || '')
  const [pendingStrikeLeave, setPendingStrikeLeave] = useState<null | {action: () => void; working: boolean}>(null)
  useEffect(() => {
    if (!['strikes', 'replacements'].includes(view) || !strikePermissions(session?.dashboard_permissions, session?.is_owner).view) setPendingStrikeLeave(null)
  }, [view, session])
  const [cwlDirty, setCwlDirty] = useState(false)
  const [rosterDirtySummary, setRosterDirtySummary] = useState({ weightCount: 0, onlyWeights: false })
  const [pendingRosterLeave, setPendingRosterLeave] = useState<null | { action: () => void; working: boolean }>(null)
  const replayRosterHistoryTarget = useRef<number | null>(null)
  const rosterEditFocus = useRef<HTMLElement | null>(null)
  const navigation = useRef<DashboardHistory | null>(null)
  const { confirm: confirmCwl, dialog: cwlConfirmation } = useConfirmDialog(`${view}:${seasonId}:${session?.user.id}:${session?.can_edit}:${session?.dashboard_permissions?.join(",")}`)
  const deferCwlLeave = (text: string, action?: () => void) => {
    void confirmCwl(text, "Discard and continue").then(confirmed => { if (confirmed) action?.() })
    return false
  }
  const signupDirty = Object.values(drafts).some(draft => Object.keys(draft).length > 0)
  useEffect(() => {
    if (tourActive || view !== 'signup' || (!signupDirty && !pending)) return
    const protect = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = '' }
    window.addEventListener('beforeunload', protect)
    return () => window.removeEventListener('beforeunload', protect)
  }, [view, signupDirty, pending, tourActive])
  const [pendingCommandLeave, setPendingCommandLeave] = useState<null | (() => void)>(null)
  const canLeave = (action?: () => void) => {
    if (isTourReadOnly()) return true
    if (view === 'text-commands' && manageDirty) {
      setPendingCommandLeave(() => action || (() => {}))
      return false
    }
    if (view === 'clan-management' && familyWorking) return false
    if (view === 'clan-management' && manageDirty) { setPendingClanLeave(() => action || (() => {})); return false }
    if (view === 'roster') {
      if (rosterBusy) { setPendingRosterLeave({ action: () => {}, working: true }); return false }
      if (cwlDirty) { setPendingRosterLeave({ action: action || (() => {}), working: false }); return false }
    }
    if (['strikes', 'replacements'].includes(view) && (manageDirty || strikeWorking)) {
      setPendingStrikeLeave({action: action || (() => {}), working: strikeWorking}); return false
    }
    if (view === 'weight-trial') {
      if (weightState.busy) return false
      if (manageDirty) {
        setPendingWeightLeave(() => action || (() => {}))
        return false
      }
    }
    if (view === 'staff' && rosterBusy) return false
    if (view === 'staff' && cwlDirty) return deferCwlLeave('Leave Seasons? Unsaved changes will be discarded.', action)
    if (view === 'signup' && (pending || signupBusy.current)) return false
    if (view === 'signup' && (signupDirty || savedSignupDirty)) return deferCwlLeave('Leave without submitting your CWL selections? Your saved signups will stay unchanged.', action)
    if (['participation', 'bonuses'].includes(view) && cwlDirty) return deferCwlLeave('Leave this CWL workspace? Unsaved edits will be discarded. If a save is in progress, wait for it to finish first.', action)
    if (view === 'access' && cwlDirty) return window.confirm('Discard unsaved access changes?')
    if (view === 'declaration' && rosterBusy) return false
    if (view === 'declaration' && cwlDirty) return deferCwlLeave('Discard the unsaved ping channel change?', action)
    if (view === 'publication' && publicationBusy) return false
    if (view === 'publication' && publicationDirty) return deferCwlLeave('Leave without saving publication or announcement changes?', action)
    if ((isManagementArea(view) || ['member-timezones','manage','text-commands','clan-management','moderation','member-activity'].includes(view)) && manageDirty) return window.confirm('Leave without saving your changes?')
    if (view === 'reminders' && reminderDirty) return deferCwlLeave('Leave without saving your reminder changes?', action)
    return true
  }
  const allowedView = (next: View): View => {
    if (!session) return 'home'
    return visibleNavigationSections(session.can_edit, session.is_owner, session.dashboard_permissions || []).some(section => section.items.some(item => item.view === (next === "replacements" ? "strikes" : next)))
      || (next === 'manage' && session.is_owner)
      || (next === 'member-activity' && visibleNavigationSections(session.can_edit, session.is_owner, session.dashboard_permissions || []).some(section => section.items.some(item => item.view === 'moderation'))) ? next : 'home'
  }
  const canOpenPublication = (step: 'review' | 'announce') => !!session &&
    visibleNavigationSections(session.can_edit, session.is_owner, session.dashboard_permissions || [])
      .some(section => section.items.some(item => item.view === 'publication' && item.step === step))
  const acceptRoute = (next: View) => { if (next !== 'signup') { setDrafts({ main: {}, lazy: {} }) }; setView(next); setMenuOpen(false); setNotice(null) }
  const [searchQuery, setSearchQuery] = useState('')
  const [searchKind, setSearchKind] = useState<'all' | 'player' | 'clan'>('all')
  const [searchPage, setSearchPage] = useState(0)
  const [activitySearch, setActivitySearch] = useState(() => activityContext(window.history.state, entryTarget.view).activityFilter || '')
  const [activityKind, setActivityKind] = useState<'war'|'cwl'|undefined>(() => activityContext(window.history.state, entryTarget.view).activityKind)
  useEffect(() => { setSearchQuery(''); setSearchKind('all'); setSearchPage(0) }, [session?.user.id])
  const previousJourneyUser = useRef<string | null>(null)
  useEffect(() => {
    if (previousJourneyUser.current && previousJourneyUser.current !== session?.user.id) { clearJourneyState(); setActivitySearch(''); setActivityKind(undefined) }
    previousJourneyUser.current = session?.user.id || null
  }, [session?.user.id])
  const [activityVisit, setActivityVisit] = useState<number>(() => window.history.state?.wuDashboardIndex || 0)
  const changeView = (
    next: View,
    filter = "",
    kind?: "war" | "cwl",
    panel: "register" | "saved" = "register",
    weights?: { player?: string; clan?: string },
  ) => {
    if (navigation.current?.pending) return
    const proceed = () => {
      const destination = allowedView(next)
      if (destination === "clan-management" && destination !== view) {
        setFamilyRoute(undefined);
        setFamilyVisit(visit => visit + 1);
      }
      if (destination === "weight-trial")
        setWeightTarget({ player: weights?.player, clan: weights?.clan });
      if (destination !== view || (destination === "signup" && signupPanel !== panel))
        navigation.current?.write(
          {
            view: destination,
            ...(destination === "weight-trial"
              ? { weightPlayer: weights?.player, weightClan: weights?.clan }
              : {}),
            activityFilter: filter,
            activityKind: kind,
            ...(destination === "signup" ? { signupPanel: panel } : {}),
            season: seasonViews.has(destination) ? staffSeasonId : seasonId,
            ...(destination === "publication" ? { step: publicationStep } : {}),
          },
          !isTourReadOnly(),
        );
      setActivityVisit(window.history.state?.wuDashboardIndex || 0)
      if (destination !== view) { setReplacementClan(''); setReplacementTag(''); setStrikeTag(''); setStrikeFilterState(''); setFlowFrom(undefined); }
      if (destination === 'signup') setSignupPanel(panel)
      setActivitySearch(filter)
      setActivityKind(kind)
      acceptRoute(destination)
    }
    if ((next !== view || (next === 'signup' && panel !== signupPanel)) && !canLeave(proceed)) return
    proceed()
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
    if (navigation.current?.pending || !canOpenPublication(step) || (view === 'publication' && publicationStep === step)) return
    const proceed = () => {
      navigation.current?.write({view: 'publication', season: seasonId, step}, true)
      setActivityVisit(window.history.state?.wuDashboardIndex || 0)
      setPublicationStep(step)
      acceptRoute('publication')
    }
    if (!canLeave(proceed)) return
    proceed()
  }
  const navigateSidebar = (next: View) => {
    if (next !== 'roster') { changeView(next); return }
    if (navigation.current?.pending || allowedView('roster') !== 'roster') return
    const proceed = () => {
      try { sessionStorage.setItem(`wu-roster-${staffSeasonId}-mode`, JSON.stringify('assign')) } catch { /* Optional preference. */ }
      setRosterReadiness('all')
      setRosterVisit(value => value + 1)
      if (view !== 'roster') navigation.current?.write({view: 'roster', season: staffSeasonId}, true)
      setActivityVisit(window.history.state?.wuDashboardIndex || 0)
      acceptRoute('roster')
    }
    if (!canLeave(proceed)) return
    proceed()
  }
  const changeSignupPanel = (panel: 'register'|'saved', after?: () => void) => {
    if (navigation.current?.pending || pending) return false
    const proceed = () => {
      if (panel !== signupPanel) navigation.current?.write({view:'signup', season:'', signupPanel:panel}, true)
      setSignupPanel(panel); setReview(false); setCompletion(null); after?.()
    }
    if (panel !== signupPanel && !canLeave(proceed)) return false
    proceed(); return true
  }
  const tourBackPending = useRef(false);
  const navigationState = useRef({ canLeave, allowedView, currentIndex: activityVisit });
  navigationState.current = { canLeave, allowedView, currentIndex: activityVisit };
  useEffect(() => {
    const controller = new DashboardHistory(window.history);
    navigation.current = controller;
    const pop = (event: PopStateEvent) => {
      if (isTourReadOnly() && !controller.pending) {
        // Return to the tour's original history entry before restoring its URL.
        // Replacing the entry reached by Back would destroy the previous page.
        controller.restoreTourEntry(event.state);
        tourBackPending.current = controller.pending;
        if (!controller.pending) window.dispatchEvent(new Event("wu-tour-back"));
        return;
      }
      const targetIndex = (event.state as { wuDashboardIndex?: number } | null)?.wuDashboardIndex;
      const previousIndex = navigationState.current.currentIndex;
      const replay = () => {
        if (!Number.isInteger(targetIndex)) return;
        const delta = targetIndex! - previousIndex;
        const resume = () => {
          if (controller.pending) { window.setTimeout(resume, 0); return; }
          replayRosterHistoryTarget.current = targetIndex!;
          window.history.go(delta);
          window.setTimeout(() => {
            if (replayRosterHistoryTarget.current === targetIndex)
              replayRosterHistoryTarget.current = null;
          }, 2000);
        };
        resume();
      };
      if (
        !controller.pop(event.state, () => {
          if (replayRosterHistoryTarget.current === targetIndex) {
            replayRosterHistoryTarget.current = null;
            return true;
          }
          replayRosterHistoryTarget.current = null;
          return navigationState.current.canLeave(replay);
        })
      ) {
        if (tourBackPending.current && !controller.pending) {
          tourBackPending.current = false;
          window.dispatchEvent(new Event("wu-tour-back"));
        }
        return;
      }
      const route = dashboardTarget(
        window.location.search,
        window.location.pathname,
      );
      const target = { ...route, ...activityContext(event.state, route.view) };
      setFamilyRoute(target.familyClan);
      setFamilyVisit(visit => visit + 1);
      setActivityVisit(event.state?.wuDashboardIndex || 0);
      setActivitySearch(target.activityFilter || "");
      setActivityKind(target.activityKind);
      setReplacementClan(target.replacementClan || "");
      setReplacementTag(target.replacementTag || "");
      setStrikeTag(target.strikeTag || "");
      setStrikeFilterState(target.strikeState || "");
      setFlowFrom(target.flowFrom);
      setWeightTarget({ player: target.weightPlayer, clan: target.weightClan });
      const destination = navigationState.current.allowedView(target.view);
      if (target.season && seasonViews.has(destination))
        setSeasonId(target.season);
      setPublicationStep(target.step || "review");
      setSignupPanel(target.signupPanel || "register");
      setCompletion(null);
      setReview(false);
      acceptRoute(destination);
      controller.write({ ...target, view: destination }, false);
    };
    window.addEventListener("popstate", pop);
    return () => {
      window.removeEventListener("popstate", pop);
      navigation.current = null;
    };
  }, []);
  useEffect(() => {
    if (authState !== 'ready') return
    const destination = allowedView(view)
    if (destination !== view) setView(destination)
    navigation.current?.write(
      {
        view: destination,
        ...(destination === "clan-management" ? { familyClan: familyRoute } : {}),
        ...(destination === "replacements" ? {replacementClan, replacementTag, flowFrom} : destination === "strikes" ? {strikeTag, flowFrom} : {}),
        ...(destination === "weight-trial"
          ? { weightPlayer: weightTarget.player, weightClan: weightTarget.clan }
          : {}),
        ...(["strikes", "replacements"].includes(destination) ? {strikeState: strikeFilterState} : {}),
        activityFilter: activitySearch,
        activityKind,
        ...(destination === "signup" ? { signupPanel } : {}),
        season: seasonViews.has(destination) ? staffSeasonId : seasonId,
        ...(destination === "publication" ? { step: publicationStep } : {}),
      },
      false,
    );
  }, [view, signupPanel, seasonId, publicationStep, authState, session, activitySearch, activityKind, replacementClan, replacementTag, strikeTag, strikeFilterState, flowFrom, weightTarget, familyRoute])
  const run = async (action: () => Promise<unknown>, success: string, refresh: () => Promise<unknown>) => {
    setPending(true); setNotice(null)
    try { await action(); await refresh(); setNotice({ kind: 'success', text: success }) }
    catch (error) { setNotice({ kind: 'error', text: message(error) }) }
    finally { setPending(false) }
  }
  const signOut = () => {
    const proceed = () => void run(
      async () => api('/auth/logout', 'POST', { push_id: await stopPushOnSignout() }),
      'Signed out.',
      async () => {
        signupRequest.current += 1
        setAccounts([])
        setSignups([])
        setDrafts({ main: {}, lazy: {} })
        setCompletion(null)
        setSession(null)
        setPrankReadyUser(null)
        setPrankReplayAvailable(false)
        setPrankReplaySignal(0)
        setAuthState('signed-out')
      },
    )
    if (!canLeave(proceed)) return
    proceed()
  }
  const submit = async () => {
    if (isTourReadOnly()) return
    if (!seasonId || !season || !pool || !selected.length || pending || signupBusy.current || loadingData || dataError || accountError || !memberSignupsOpen(season)) return
    signupBusy.current = true
    const submittedSeason = seasonId
    const submittedPool = pool
    const submittedAccounts = selected.map(item => ({ ...item }))
    const summary: Completion = { seasonId: submittedSeason, seasonLabel: season.label, pool: submittedPool, accounts: submittedSummary(accounts, submittedAccounts), refreshWarning: false }
    setPending(true)
    setNotice(null)
    try {
      await api<{ ok: boolean; count: number }>(`/seasons/${encodeURIComponent(submittedSeason)}/signups`, 'POST', { pool: submittedPool, accounts: submittedAccounts })
    } catch (error) {
      if (message(error).includes('FWA accounts can only')) setFwaBlocked(true)
      setNotice({ kind: 'error', text: message(error) })
      signupBusy.current = false
      setPending(false)
      return
    }
    if (currentSeason.current !== submittedSeason) { signupBusy.current = false; setPending(false); return }
    setDrafts(current => clearSubmittedDraft(current, submittedPool))
    setReview(false)
    setPoolRemoved([])
    setCompletion(summary)
    selectionRef.current = { drafts: {main: {}, lazy: {}} }
    const refreshed = await loadSignup()
    if (!refreshed?.all && currentSeason.current === submittedSeason) setCompletion(current => current?.seasonId === submittedSeason ? { ...current, refreshWarning: true } : current)
    signupBusy.current = false
    setPending(false)
  }
  const tourRestore = useRef<(() => void) | null>(null);
  const tourSession = (active: boolean) => {
    if (active) {
      // Do not leave any in-flight write or unrelated dirty editor behind.
      if (
        pending ||
        signupBusy.current ||
        rosterBusy ||
        manageDirty ||
        cwlDirty ||
        publicationBusy ||
        publicationDirty ||
        reminderDirty ||
        savedSignupDirty
      )
        return false;
      const originalRoute = dashboardTarget(
        window.location.search,
        window.location.pathname,
      );
      tourRestore.current = () => {
        navigation.current?.write(originalRoute, false);
        if (view === "signup") dashboardPrefill.current = true;
        changeView(view, activitySearch, activityKind, signupPanel);
        setSeasonId(staffSeasonId);
        setPool(pool);
        setReturnToReview(returnToReview);
        setPoolRemoved(poolRemoved);
        setDrafts(drafts);
        setSignupStep(signupStep);
        setReview(review);
        setCompletion(completion);
        setSignupSearch(signupSearch);
        setSignupPage(signupPage);
        setNotice(notice);
      };
      setTourReadOnly(true);
      setReturnToReview(false);
      setPoolRemoved([]);
      setPool(null);
      setDrafts({ main: {}, lazy: {} });
      setSignupStep(1);
      setReview(false);
      setCompletion(null);
      setSignupSearch("");
      setSignupPage(0);
    } else {
      try {
        tourRestore.current?.();
      } finally {
        tourRestore.current = null;
        setTourReadOnly(false);
        setTourActive(false);
      }
    }
    setTourActive(active);
    return true;
  };
  const tourNavigate = (page: TourPage, step: number) => {
    const next = page === "register" || page === "saved" ? "signup" : page;
    if (
      next !== view ||
      (next === "signup" &&
        signupPanel !== (page === "saved" ? "saved" : "register"))
    ) {
      changeView(next, "", undefined, page === "saved" ? "saved" : "register");
    }
    if (page === "register") {
      setCompletion(null);
      if (step <= 4) {
        setSignupStep(1);
        setReview(false);
      } else if (step <= 6) {
        setSignupStep(2);
        setReview(step === 6);
      }
    }
  };
  const showSavedSignups = async () => {
    if (completion?.refreshWarning) {
      setPending(true)
      const refreshed = await loadSignup()
      setPending(false)
      if (!refreshed?.signups) return
    }
    setCompletion(null)
    changeSignupPanel('saved')
    setJumpTarget('registered')
  }
  const saveSavedSignups = async (moves: SignupMove[]): Promise<{saved: string[]; error: string | null}> => {
    if (!season || !memberSignupsOpen(season) || pending || signupBusy.current || loadingData || accountError || dataError) return {saved: [], error: 'Changes cannot be saved right now. Check signup availability and refresh accounts.'}
    signupBusy.current = true
    setPending(true)
    setNotice(null)
    try {
      const result = await saveSignupMoves(moves, (destination, rows) => api(`/seasons/${encodeURIComponent(seasonId)}/signups`, 'POST', {
        pool: destination,
        accounts: rows.map(row => ({tag: row.tag, prefer_crystal_1_or_lower: row.prefer_crystal_1_or_lower, move_from_pool: row.pool})),
      }))
      signupRequest.current += 1
      setSignups(current => current.map(row => {
        const move = moves.find(move => move.signup.tag === row.tag)
        return result.saved.includes(row.tag) && move ? {...row, pool: move.destination, has_staff_placement: false} : row
      }))
      if (result.error && message(result.error).includes('FWA accounts can only')) setFwaBlocked(true)
      const error = result.error ? `${result.saved.length} of ${moves.length} changes confirmed. ${message(result.error)} Pending changes are kept. Refresh saved signups before retrying if the result is uncertain.` : null
      setNotice(error ? null : {kind: 'success', text: 'CWL changes saved.'})
      return {saved: result.saved, error}

    } finally { signupBusy.current = false; setPending(false) }
  }
  const withdraw = async (rows: Signup[]) => {
    if (!seasonId || pending || loadingData || !rows.length) return
    if (!(await confirmCwl(withdrawConfirmation(rows), "Withdraw accounts", {danger: true}))) return
    const withdrawnSeason = seasonId
    let removed = new Set<string>()
    setPending(true)
    setNotice(null)
    try {
      // Reuse the authorized per-account operation. Stop at the first failure;
      // never silently retry an uncertain deletion or imply all accounts saved.
      const result = await withdrawInOrder(rows.map(row => row.tag), tag => api(`/seasons/${encodeURIComponent(withdrawnSeason)}/signups/${tagPath(tag)}`, 'DELETE'))
      removed = result.removed
      if (result.error) throw result.error
      setNotice({kind: 'success', text: `${removed.size} ${removed.size === 1 ? 'signup' : 'signups'} withdrawn.`})
    } catch (error) {
      setNotice({kind: 'error', text: `${removed.size} of ${rows.length} withdrawals confirmed. Stopped: ${message(error)} Refresh saved signups before trying again.`})
    } finally {
      if (currentSeason.current === withdrawnSeason) {
        signupRequest.current += 1
        setSignups(current => current.filter(signup => !removed.has(signup.tag)))
        setDrafts(current => ({main: Object.fromEntries(Object.entries(current.main).filter(([tag]) => !removed.has(tag))), lazy: Object.fromEntries(Object.entries(current.lazy).filter(([tag]) => !removed.has(tag)))}))
      }
      setPending(false)
    }
  }
  if (authState === 'loading') return <div className="center-screen"><Brand large /><p>Checking Discord sign-in…</p></div>
  const retrySignupRead = async () => {
    if (signupPanel === 'saved' && savedSignupDirty && !(await confirmCwl('Refresh CWL data and discard pending pool changes?', 'Discard and refresh'))) return
    setSavedSignupsLoaded(false)
    void loadSignup()
  }
  if (authState === 'error') return <div className="center-screen"><Brand large /><div className="card narrow"><h1>CWL is unavailable</h1><p role="alert">{authError}</p><button onClick={() => void loadAuth()}>Retry connection</button></div></div>
  if (authState === 'signed-out') return <main className="center-screen welcome-screen"><Brand large /><div className="card login-card"><p className="eyebrow">Warriors United Dashboard</p><h1>Your accounts.<br />Your clans.<br />One place.</h1><p>Check your attacks, set reminders, and sign up for CWL.</p><ul className="welcome-features"><li><DashboardIcon name="war"/><div><strong>Tasks</strong><small>See attacks and events.</small></div></li><li><DashboardIcon name="shield"/><div><strong>My accounts</strong><small>View your linked accounts.</small></div></li><li><DashboardIcon name="trophy"/><div><strong>CWL</strong><small>Sign up and see your assigned clans.</small></div></li></ul>{entryTarget.view !== 'home' && <p className="welcome-destination">After sign-in: <strong>{entryTarget.view === 'signup' && entryTarget.signupPanel === 'saved' ? 'My signups' : navigationLabel(entryTarget.view)}</strong></p>}<a className="button primary" href={loginPath(window.location.search, !!authError, window.location.pathname)}>Continue with Discord</a>{fixtureMode && <button className="fixture-button" onClick={() => void api('/dev/login', 'POST').then(loadAuth).catch(error => setAuthError(message(error)))}>Open local test session</button>}{authError && <p className="inline-reason" role="alert">{authError}</p>}</div></main>

  if (!session) return <div className="center-screen"><Brand large /><p>Checking Discord sign-in…</p></div>

  return <DashboardPermissions.Provider value={{owner: session.is_owner, permissions: session.dashboard_permissions || []}}><div className={`shell${tourActive ? ' tour-active' : ''}`}>
    {cwlConfirmation}
    {pendingStrikeLeave && (
      <ConfirmDialog
        key={pendingStrikeLeave.working ? 'working' : 'dirty'}
        heading={
          pendingStrikeLeave.working ? 'Save in progress' : 'Unsaved changes'
        }
        text={
          pendingStrikeLeave.working
            ? 'Wait for the save to finish.'
            : 'Discard your unsaved strike or replacement changes?'
        }
        confirmLabel={pendingStrikeLeave.working ? 'OK' : 'Discard'}
        cancelLabel="Keep editing"
        hideCancel={pendingStrikeLeave.working}
        onCancel={() => setPendingStrikeLeave(null)}
        onConfirm={() => {
          const pending = pendingStrikeLeave
          setPendingStrikeLeave(null)
          if (pending.working) return
          if (strikeWorking) {
            setPendingStrikeLeave({ ...pending, working: true })
            return
          }
          pending.action()
        }}
      />
    )}
    {pendingCommandLeave && <ConfirmDialog
      text="Discard unsaved command changes?"
      confirmLabel="Discard"
      cancelLabel="Keep editing"
      onCancel={() => setPendingCommandLeave(null)}
      onConfirm={() => {
        const action = pendingCommandLeave
        setPendingCommandLeave(null)
        action()
      }}
    />}
    {pendingClanLeave && <ConfirmDialog text="Discard unsaved clan changes?" confirmLabel="Discard" onCancel={() => setPendingClanLeave(null)} onConfirm={() => { const action = pendingClanLeave; setPendingClanLeave(null); action(); }} />}
    {pendingWeightLeave && (
      <ConfirmDialog
        heading="Unsaved changes"
        text={`You have ${weightState.count} unsaved weight${weightState.count === 1 ? "" : "s"}.`}
        confirmLabel="Discard"
        cancelLabel="Keep editing"
        danger
        returnFocus={() => weightEditFocus.current}
        onCancel={() => setPendingWeightLeave(null)}
        onConfirm={() => {
          const action = pendingWeightLeave;
          setPendingWeightLeave(null);
          if (!weightState.busy) action();
        }}
      />
    )}
    {pendingRosterLeave && <ConfirmDialog
      key={pendingRosterLeave.working ? 'working' : 'dirty'}
      heading={pendingRosterLeave.working ? 'Save in progress' : 'Unsaved changes'}
      text={pendingRosterLeave.working ? 'Wait for the save to finish.' : rosterDirtySummary.onlyWeights ? `You have ${rosterDirtySummary.weightCount} unsaved weight${rosterDirtySummary.weightCount === 1 ? '' : 's'}.` : 'You have unsaved roster changes.'}
      confirmLabel={pendingRosterLeave.working ? 'OK' : 'Discard'}
      cancelLabel="Keep editing"
      hideCancel={pendingRosterLeave.working}
      cancelOnBackdrop
      returnFocus={() => rosterEditFocus.current}
      danger={!pendingRosterLeave.working}
      onCancel={() => setPendingRosterLeave(null)}
      onConfirm={() => {
        const { action, working: wasWorking } = pendingRosterLeave;
        setPendingRosterLeave(null);
        if (wasWorking) return;
        if (rosterBusy) {
          setPendingRosterLeave({ action: () => {}, working: true });
          return;
        }
        action();
      }}
    />}
    <a className="skip-to-content" href="#dashboard-main" inert={mobile && menuOpen}>Skip to content</a>
    <aside ref={drawerRef} id="dashboard-navigation" className={`sidebar ${menuOpen ? 'open' : ''}`} inert={mobile && !menuOpen} role={mobile && menuOpen ? 'dialog' : undefined} aria-modal={mobile && menuOpen ? true : undefined} aria-label={mobile && menuOpen ? 'Navigation' : undefined} tabIndex={-1}>
      <div className="brand-wrap"><Brand /><button className="menu-close" onClick={() => setMenuOpen(false)} aria-label="Close menu">×</button></div>
      <SidebarNavigation tourExpanded={tourActive} key={session.user.id} userId={session.user.id} view={view} canEdit={session.can_edit} permissions={session.dashboard_permissions || []} isOwner={session.is_owner} onNavigate={navigateSidebar} publicationStep={publicationStep} onPublication={openPublication} signupPanel={signupPanel} onSignup={panel => changeView("signup", "", undefined, panel)} />
      <div className="sidebar-foot">
        <MemberTour key={session.user.id} view={view} menuOpen={menuOpen} onMenu={setMenuOpen} onActive={tourSession} onNavigate={tourNavigate}
          inviteBlocked={view === 'home' && session.is_owner && prankReadyUser !== session.user.id}
          startBlocked={pending || signupBusy.current || rosterBusy || manageDirty || cwlDirty || publicationBusy || publicationDirty || reminderDirty || savedSignupDirty}
          signupState={dataError || accountError ? 'error' : seasonsLoading || !season || loadingData ? 'loading' : !memberSignupsOpen(season) ? 'closed' : !accounts.length ? 'empty' : !visibleAccounts.length ? 'all-signed' : 'open'} />
        <AccountMenu user={session.user} onSignOut={signOut} variant="profile" disabled={pending}
          replayPrank={prankReplayAvailable ? () => setPrankReplaySignal(value => value + 1) : undefined} />
      </div>
    </aside>
    {menuOpen && <button className="scrim" tabIndex={-1} aria-hidden="true" aria-label="Close menu" onClick={() => setMenuOpen(false)} />}
    {fwaBlocked && <FwaSignupDialog onClose={() => setFwaBlocked(false)} />}
    <div className="workspace" inert={mobile && menuOpen}>
      <header className="topbar"><button ref={triggerRef} className="menu-open" aria-label="Open menu" aria-controls="dashboard-navigation" aria-expanded={menuOpen} onClick={() => setMenuOpen(true)}><span aria-hidden="true">☰</span><span>Menu</span></button><div><span className="crumb">{navigationSection(view) || 'Dashboard'}</span><strong>{view === 'member-timezones' ? 'Members' : view === 'issues' ? 'Dashboard issues' : view === 'image-gallery' ? 'Image gallery' : view === 'tickets' ? 'Tickets' : (view === 'member-activity' || view === 'moderation') ? 'Moderation' : view === 'staff-overview' ? 'Staff overview' : isManagementArea(view) ? managementAreas[view].title : view === 'weight-trial' ? 'Clan weights' : view === 'clan-management' ? 'Family clans' : (view === 'strikes' || view === 'replacements') ? 'Strikes & replacements' : view === 'text-commands' ? 'Command triggers' : view === 'manage' ? 'Server management' : view === 'home' ? 'Dashboard' : view === 'bases' ? 'Base bank' : view === 'search' ? 'Search' : view === 'wars' ? 'Wars' : view === 'events' ? 'Events' : view === 'todo' ? 'Tasks' : view === 'signup' ? signupPanel === 'saved' ? 'My signups' : 'Sign up' : view === 'assignments' ? 'My clan assignments' : view === 'declaration' ? 'Declaration check' : view === 'roster' ? 'Build roster' : view === 'reminders' ? 'Signup reminders' : view === 'publication' ? navigationLabel(view, publicationStep) : view === 'participation' ? 'Results & participation' : view === 'bonuses' ? 'Bonus medals' : view === 'staff' ? 'Seasons' : view === 'exports' ? 'Exports' : 'Staff access'}</strong></div>{mobile ? <AccountMenu user={session.user} onSignOut={signOut} variant="avatar" disabled={pending} replayPrank={prankReplayAvailable ? () => setPrankReplaySignal(value => value + 1) : undefined} /> : <AccountIdentity user={session.user} />}</header>
      <main id="dashboard-main" tabIndex={-1} aria-label={navigationLabel(view, publicationStep)}>
        {(session.is_owner || session.can_edit || !!session.dashboard_permissions?.length) && <DashboardStorageStatus />}
        {["roster", "publication", "declaration"].includes(view) && (
          <StaffDetailsHost
            key={`${view}:${seasonId}`}
            archived={season?.status === "archived"}
            initialAccount={view === entryTarget.view && seasonId === entryTarget.season ? entryAccount : null}
            onInitialConsumed={() => setEntryAccount(null)}
          />
        )}
        <RouteLoadBoundary resetKey={`${view}:${seasonId}`}>
        {seasonError && seasonsKnown && view !== 'home' && <div className="member-refresh-note" role="status"><span>Could not refresh. Showing last update.</span><button disabled={seasonsLoading} onClick={() => void loadSeasons()}>Retry</button></div>}
        {seasonError && !seasonsKnown && view !== 'signup' && view !== 'home' && <div className="notice error" role="alert">Could not load CWL seasons.<button disabled={seasonsLoading} onClick={() => void loadSeasons()}>Retry seasons</button></div>}
        {fixtureMode && <div className="fixture-banner" role="status">Local fixture data · Development only</div>}
        {(view === 'signup' || view === 'assignments') && <MemberStepStrip step={view === 'assignments' ? 'assignments' : signupPanel} onNavigate={step => step === 'assignments' ? changeView('assignments') : changeView('signup', '', undefined, step)} />}
        {session.can_edit && ['roster', 'publication'].includes(view) && <CwlStepStrip
          step={view === 'roster' ? 'build' : publicationStep}
          draft={flowPublication?.season === seasonId ? flowPublication.draft : null}
          onBuild={() => changeView('roster')}
          onFinalize={() => openPublication('review')}
          onAnnounce={() => openPublication('announce')}
        />}
        {session.can_edit && ['participation','bonuses','exports'].includes(view) &&
          (['participation','bonuses','exports'] as const).filter(target => allowedView(target) === target).length > 1 && (
          <nav className="cwl-result-nav" aria-label="Results sections">
            {([
              ['participation', 'Participation'],
              ['bonuses', 'Bonus medals'],
              ['exports', 'Exports'],
            ] as const).filter(([target]) => allowedView(target) === target).map(([target, label]) => (
              <button key={target} aria-current={view === target ? 'page' : undefined} onClick={() => changeView(target)}>{label}</button>
            ))}
          </nav>
        )}
        {notice && !(view === 'signup' && review) && <div className={`notice ${notice.kind}`} role={notice.kind === 'error' ? 'alert' : 'status'}>{notice.text}<button aria-label="Dismiss message" onClick={() => setNotice(null)}>×</button></div>}
        {view === 'staff-overview' && <StaffOverview onNavigate={(next,season)=>{if(season)setSeasonId(season);changeView(next)}} />}
        {view === 'image-gallery' && <ImageGallery onDirty={setManageDirty} />}
        {view === 'bases' && <BaseBank key={session.user.id} />}
        {view === 'tickets' && <TicketBrowser />}
        {(view === 'member-activity' || view === 'moderation') && <ModerationWorkspace onDirty={setManageDirty} />}
        {view === 'clan-management' && <ClanManagement key={familyVisit} initialRoute={familyRoute} onWorking={setFamilyWorking} onDirty={setManageDirty} onNavigate={route => {
          setFamilyRoute(route);
          navigation.current?.write({view: 'clan-management', season: '', familyClan: route}, true);
          setActivityVisit(window.history.state?.wuDashboardIndex || 0);
        }} />}
        {view === "weight-trial" && (
          <div
            onFocusCapture={(event) => {
              if (event.target instanceof HTMLInputElement)
                weightEditFocus.current = event.target;
            }}
          >
            <WeightTrial
              key={session.user.id}
              viewerId={session.user.id}
              onDirty={setManageDirty}
              onState={setWeightState}
              targetPlayer={weightTarget.player}
              targetClan={weightTarget.clan}
              seasonId={session.can_edit ? staffSeasonId : undefined}
              onRoster={() => changeView("roster")}
            />
          </div>
        )}
        {['strikes', 'replacements'].includes(view) &&
          strikePermissions(session.dashboard_permissions, session.is_owner).view && (
            <StrikesWorkspace
              onWorking={setStrikeWorking}
              memory={flowMemory.strikes}
              targetTag={view === 'replacements' ? replacementTag : strikeTag}
              activityState={strikeFilterState || (view === 'replacements' && replacementClan ? new URLSearchParams({clans:replacementClan, marked:'1'}).toString() : '')}
              markedDefault={view === 'replacements'}
              onActivityState={(state,push) => {
                if (navigation.current?.pending) return;
                navigation.current?.write({view: view as 'strikes'|'replacements', season:'', strikeState:state},push);
                setActivityVisit(window.history.state?.wuDashboardIndex || 0);
                setStrikeFilterState(state);
              }}
              onAccountRoute={(tag) => {
                if (navigation.current?.pending) return;
                const state = strikeFilterState || (view === 'replacements' ? new URLSearchParams({marked:'1', ...(replacementClan ? {clans:replacementClan} : {})}).toString() : '');
                navigation.current?.write({view:'strikes',season:'',strikeTag:tag,strikeState:state},true);
                setActivityVisit(window.history.state?.wuDashboardIndex || 0);
                setStrikeFilterState(state); setStrikeTag(tag); setReplacementTag(''); acceptRoute('strikes');
              }}
              onFindReplacement={(clan) => {
                const state = new URLSearchParams({clans:clan, marked:'1'}).toString();
                navigation.current?.write({view:'strikes',season:'',strikeState:state},true);
                setActivityVisit(window.history.state?.wuDashboardIndex || 0);
                setStrikeFilterState(state);setStrikeTag('');acceptRoute('strikes');
              }}
              onDirty={setManageDirty}
              permissions={session.dashboard_permissions || []}
              isOwner={session.is_owner}
              userId={session.user.id}
            />
          )}
        {view === 'text-commands' && <TextCommands onDirty={setManageDirty} />}
        {isManagementArea(view) && view !== 'members-settings' && <ServerManagement key={view} area={view} onDirty={setManageDirty} onNavigate={destination => changeView(destination as View)} />}
        {(view === 'members-settings' || view === 'member-timezones') && <MembersPage onDirty={setManageDirty} initialMember={entryAccount} onInitialConsumed={() => setEntryAccount(null)} />}
        {view === 'manage' && <ServerManagement onDirty={setManageDirty} onNavigate={destination => changeView(destination as View)} />}
        {view === 'reminders' && session.can_edit && <><CwlPageHeader title={<h1>Signup reminders</h1>}><RosterMenu label="Season" value={seasonId} onValueChange={async next => { if (!reminderDirty || await confirmCwl('Discard unsaved reminder edits and change season?', 'Discard and change season')) setSeasonId(next) }} options={[{value: '', label: 'Select season'}, ...seasons.map(item => ({value: String(item.id), label: item.label}))]} /></CwlPageHeader>{seasonId ? <ReminderWorkspace key={seasonId} seasonId={seasonId} archived={season?.status === 'archived'} onDirty={setReminderDirty} /> : <p>Select a season to manage its reminders.</p>}{seasonId && <CwlNextLink label="Build roster" onNext={allowedView("roster") === "roster" ? () => navigateSidebar("roster") : undefined} disabled={rosterBusy} />}</>}
        {view === 'search' && <DashboardSearch key={session.user.id} session={session} includeFamily={session.can_edit} query={searchQuery} onQuery={value => { setSearchQuery(value); setSearchPage(0) }} kind={searchKind} onKind={value => { setSearchKind(value); setSearchPage(0) }} page={searchPage} onPage={setSearchPage} onTasks={tag => changeView('todo', tag)} />}
        {view === 'todo' && <TodoWorkspace key={`${session.user.id}:${activitySearch}:${activityKind || "default"}`} userId={session.user.id} initialSearch={activitySearch} initialTab={activityKind} onWars={kind => changeView('wars', '', kind)} />}
        {view === 'wars' && <WarsWorkspace key={`${session.user.id}:${activityVisit}:${activityKind || "default"}`} userId={session.user.id} visit={activityVisit} initialType={activityKind === 'cwl' ? 'cwl' : 'regular'} canEdit={session.can_edit} onTasks={(tag,kind) => changeView('todo', tag,kind)} />}
        {view === 'events' && <EventsWorkspace key={session.user.id} canEdit={session.can_edit} onWars={() => changeView('wars', '', 'cwl')} />}
        {view === 'home' && <DashboardHome key={`${session.user.id}:${seasonId}`} session={session} seasonId={seasonId} seasons={seasons} seasonsKnown={seasonsKnown} seasonError={seasonError} onRetrySeasons={() => void loadSeasons()} onNavigate={next => { if (next === 'signup' || next === 'saved') { setSignupPanel(next === 'saved' ? 'saved' : 'register'); setSignupStep(1); setPool(null); setCompletion(null); setReview(false) }; changeView(next === 'saved' ? 'signup' : next, '', undefined, next === 'saved' ? 'saved' : 'register') }} onStart={(nextPool, tags, freshAccounts, freshSignups) => {
          dashboardPrefill.current = true
          signupRequest.current += 1
          setAccounts(freshAccounts); setAccountsLoadedFor(`${session.user.id}:${seasonId}`); setSignups(freshSignups); setSavedSignupsLoaded(true); setLoadingData(false); setAccountError(''); setDataError('')
          setDrafts({ main: {}, lazy: {}, [nextPool]: Object.fromEntries(tags.filter(tag => freshAccounts.some(account => account.tag === tag) && !freshSignups.some(signup => signup.tag === tag)).map(tag => [tag, false])) })
          setPool(nextPool); setSignupPanel('register'); setSignupStep(2); setReview(false); setCompletion(null); changeView('signup')
        }} />}
        {view === 'signup' && <>
          <CwlPageHeader className="member-signup-head" title={<h1>{signupPanel === 'saved' ? 'My signups' : 'Sign up'}</h1>} /><p className="cwl-page-description">{signupPanel === 'saved' ? 'Your saved CWL signups for this season.' : activeCompletion ? "Your season signup is saved." : season && !memberSignupsOpen(season) ? "View your saved signups and CWL clans." : "Sign up your accounts for CWL. Staff will select your CWL clans."}</p>
          {((seasonError && !seasonsKnown) || (!activeCompletion && (dataError || accountError))) && <AttentionSummary urgent items={[
            ...(seasonError && !seasonsKnown ? [{ title: 'CWL season availability could not be checked', detail: 'The season list may be out of date. Retry before choosing a season.', technicalDetail: seasonError, action: { label: 'Retry seasons', onClick: () => void loadSeasons(), disabled: seasonsLoading } }] : []),
            ...(!activeCompletion && dataError ? [{ title: accountError ? 'Signup and account data could not be checked' : 'Saved CWL signups could not be checked', detail: accountError ? 'You cannot see saved signups or linked accounts until this check works.' : 'You cannot change signups or saved accounts until this check works.', technicalDetail: [dataError, accountError].filter(Boolean).join(' · '), action: { label: 'Retry CWL data', onClick: retrySignupRead, disabled: loadingData || pending } }] : !activeCompletion && accountError ? [{ title: 'Linked accounts are unavailable', detail: 'You cannot select accounts or change pools until the dashboard checks your links.', technicalDetail: accountError, action: { label: 'Retry CWL data', onClick: retrySignupRead, disabled: loadingData || pending } }] : []),
          ]} />}
          {seasonsLoading && <p role="status">Loading seasons…</p>}
          {!seasonId && !seasonsLoading && !seasonError && <div className="card empty"><p>Staff will make the next CWL season available here.</p></div>}
          {season && <>{!activeCompletion && loadingData && signupPanel === 'register' && <p role="status">Loading linked accounts…</p>}<MemberSeasonLine season={season} hideClosedStatus={signupPanel === 'register' && !memberSignupsOpen(season)} />
            {activeCompletion ? <section className="completion-card card" aria-labelledby="completion-title"><div className="completion-mark" aria-hidden="true">✓</div><h2 id="completion-title" ref={completionHeadingRef} tabIndex={-1}>You are signed up</h2><p><strong>{activeCompletion.accounts.length} {activeCompletion.accounts.length === 1 ? 'account is' : 'accounts are'} signed up</strong> for {poolName(activeCompletion.pool)} in {activeCompletion.seasonLabel}.</p><div className="completion-accounts">{activeCompletion.accounts.map(account => <div key={account.tag}><strong>{account.name}</strong><small>{account.tag}</small></div>)}</div><p>Your accounts are signed up. Staff will assign them to clans. You can close this page, or sign up more accounts below.</p>{activeCompletion.refreshWarning && <div className="notice error" role="alert">Your signup is saved. The account list did not refresh. Check your saved signups later.</div>}<div className="completion-actions"><button className="primary" disabled={pending} onClick={() => void showSavedSignups()}>View my signups</button><button disabled={pending} onClick={() => changeView('assignments')}>My clan assignments</button><button disabled={pending} onClick={() => { setPoolRemoved([]); setCompletion(null); setSignupPanel('register'); setSignupStep(1); setPool(null); setReview(false) }}>Sign up more accounts</button></div></section> : <>
            {signupPanel === 'register' && !memberSignupsOpen(season) && <section data-tour-target="signup-closed" className="signup-guide" aria-label="Signup walkthrough"><h2>Signups closed</h2><p>View your saved signups or check your CWL clan. To make a change, ask staff for help.</p><div className="signup-action-buttons"><button onClick={() => changeSignupPanel('saved')}>My signups</button><button onClick={() => changeView('assignments')}>My clan assignments</button></div></section>}
            {signupPanel === 'register' && memberSignupsOpen(season) && <div className="signup-flow">
              {accountsReady && !loadingData && !accountError && accounts.length === 0 && <section className="card" data-tour-target="signup-missing"><h2>Link an account</h2><AccountLinkHelp busy={loadingData || pending} onRefresh={() => void loadSignup()} /></section>}
              <SignupWalkthrough stage={review ? 3 : signupStep} pool={pool}
                selectedCount={selected.length} busy={pending}
                canReview={!!pool && selected.length > 0 && !loadingData && !dataError && !accountError}
                headingRef={stepHeadingRef} onNavigate={stage => {
                  if (pending || (stage > 1 && !pool)) return
                  if (stage === 3 && (!selected.length || loadingData || dataError || accountError)) return
                  setReturnToReview(review && stage === 1)
                  setReview(stage === 3)
                  setSignupStep(stage === 1 ? 1 : 2)
                }} />
              {poolRemoved.length > 0 && <p className="notice" role="status">No longer eligible for this pool: {poolRemoved.join(", ")}. These accounts were removed from this unsaved selection.</p>}
              {signupStep === 1 && !review && <div className="pool-choice"><div className="pool-choice-grid"><button className={pool === 'main' ? 'active' : ''} aria-pressed={pool === 'main'} disabled={pending} onClick={() => choosePool('main')}><span className="pool-choice-symbol">◆</span><strong>Main CWL</strong><small>Main: play at full strength. No hero upgrades.</small><span className="pool-next">Select Main CWL →</span></button><button data-tour-target="signup-pool" className={pool === 'lazy' ? 'active' : ''} aria-pressed={pool === 'lazy'} disabled={pending} onClick={() => choosePool('lazy')}><span className="pool-choice-symbol">◇</span><strong>Lazy CWL</strong><small>Lazy: relaxed CWL. You can upgrade during the event.</small><small className="fwa-cwl-note">If you’re in FWA… it’s Lazy Way or No Way!!!</small><span className="pool-next">Select Lazy CWL →</span></button></div><p className="small">You can use different accounts for Main and Lazy CWL.</p></div>}{pool && signupStep === 2 && !review && <>
            <CwlPoolTabs value={pool} onChange={choosePool} disabled={pending || loadingData} />
            <div className="section-heading"><div><h2 ref={selectionHeadingRef} tabIndex={-1}>Select linked accounts</h2><p>{pool === 'lazy' ? 'Linked accounts from any clan can join Lazy CWL. Each account can join one CWL pool per season.' : 'Main CWL signup is separate from Lazy CWL. Each account can join one pool per season.'}</p></div><div className="count-pill">{selected.length} selected</div></div>

            {!accountError && accounts.length > 0 && <>
              {visibleAccounts.length > 0 && <><div className="selection-bar"><label className="check-label"><input type="checkbox" checked={available.length > 0 && available.every(account => Object.hasOwn(draft, account.tag))} onChange={event => { if (!pool) return; if (event.target.checked) setDraft({...draft, ...Object.fromEntries(available.map(account => [account.tag, draft[account.tag] ?? false]))}); else { const next = {...draft}; for (const account of available) delete next[account.tag]; setDraft(next) } }} disabled={!memberSignupsOpen(season) || !available.length || pending || loadingData || !!dataError || !!accountError} />Select all matching accounts ({available.length})</label><button onClick={() => void loadSignup()} disabled={loadingData || pending}>Refresh accounts</button></div>
              <label className="signup-account-search">Find a player or clan<input type="search" value={signupSearch} onChange={event => setSignupSearch(event.target.value)} placeholder="Find a player or clan" /></label></>}
              {visibleAccounts.length > 0 && matchingAccounts.length === 0 && <div className="card empty"><p>No accounts match your search.</p><button onClick={() => setSignupSearch('')}>Clear search</button></div>}
              {visibleAccounts.length === 0 && <div className="card empty"><h3>All your linked accounts are signed up.</h3><p>To change or withdraw a signup, go to My signups.</p><button disabled={pending} onClick={() => changeSignupPanel('saved')}>My signups</button></div>}
              <details className="hub-help"><summary data-tour-target="signup-missing">Link an account</summary><AccountLinkHelp busy={loadingData || pending} onRefresh={() => void loadSignup()} /></details>
              <div className="account-list">{pageAccounts.map((account, index) => {
                const chosen = Object.hasOwn(draft, account.tag) && !(pool === 'main' && account.current_clan_type === 'FWA')
                return <article data-tour-target={index === 0 ? "signup-account" : undefined} className={`account-card ${chosen ? 'chosen' : ''}`} key={account.tag}>
                  <div className="account-top"><label className="account-select"><input type="checkbox" checked={chosen} disabled={ !memberSignupsOpen(season) || pending || loadingData || !!dataError || !!accountError} onChange={event => { if (!pool) return; if (event.target.checked && pool === 'main' && account.current_clan_type === 'FWA') { setFwaBlocked(true); return }; const next = { ...draft }; if (event.target.checked) next[account.tag] = false; else delete next[account.tag]; setDraft(next) }} /><span><strong className="signed-up-name"><TownHallIcon level={account.town_hall} /><span>{account.name}</span></strong><small>{account.tag}</small></span></label></div>
                  <div className="account-meta"><span>Current clan <strong>{account.current_clan_name || 'None'}{account.current_clan_tag ? ` · ${account.current_clan_tag}` : ''}</strong></span></div>
                  {pool === 'main' && account.current_clan_type === 'FWA' && <p className="inline-reason">FWA account · Lazy CWL only. Select Lazy CWL above to sign up this account.</p>}
                </article>
              })}</div>
              {lastSignupPage > 0 && <nav className="hub-pagination" aria-label="Signup account pages"><button disabled={currentSignupPage === 0} onClick={() => setSignupPage(currentSignupPage - 1)}>Previous accounts</button><span>Page {currentSignupPage + 1} of {lastSignupPage + 1}</span><button disabled={currentSignupPage === lastSignupPage} onClick={() => setSignupPage(currentSignupPage + 1)}>Next accounts</button></nav>}
              {memberSignupsOpen(season) && visibleAccounts.length > 0 && <div className="submit-bar"><div><strong>{selected.length} {selected.length === 1 ? 'account' : 'accounts'} selected</strong><small>Selections across all pages · Not saved yet.</small></div><div className="signup-action-buttons"><button disabled={pending} onClick={() => setSignupStep(1)}>← Back</button><button className="primary" disabled={!selected.length || pending || loadingData || !!dataError || !!accountError} onClick={() => setReview(true)}>Continue →</button></div></div>}
            </>}
            </>}
            {signupStep === 2 && !review && (!accounts.length || accountError || !memberSignupsOpen(season)) && <button disabled={pending} onClick={() => setSignupStep(1)}>← Back to CWL choice</button>}
            {review && pool && <section data-tour-target="signup-review" className="signup-review card" aria-label="Review selected accounts">{notice?.kind === 'error' && <div className="notice error" role="alert">{notice.text}</div>}<SignupReviewHeading poolLabel={poolName(pool)} count={selected.length} busy={pending} onChange={changeReviewStep} /><div className="review-list">{selected.map(item => { const account = accounts.find(candidate => candidate.tag === item.tag)!; return <div className="review-row" key={item.tag}><div><strong className="signed-up-name"><TownHallIcon level={account.town_hall} /><span>{account.name}</span></strong><small>{account.tag} · TH {account.town_hall ?? '—'} · {account.current_clan_name || 'No current clan'}</small></div>{account.current_clan_type === 'FWA' && pool === 'main' && <span className="transfer-review">FWA account · Lazy CWL only.</span>}</div> })}</div><div className="signup-actions submit-bar"><button disabled={pending} onClick={() => setReview(false)}>← Back</button><button data-tour-target="signup-confirm" className="primary" disabled={!selected.length || pending || loadingData || !memberSignupsOpen(season) || !!dataError || !!accountError} onClick={submit}>{pending ? 'Saving…' : `Sign up ${selected.length} ${selected.length === 1 ? 'account' : 'accounts'}`}</button></div></section>}
            </div>}
            {signupPanel === 'saved' && <section className="registered">
              {!savedSignupsLoaded && !dataError ? <p role="status">Loading saved signups…</p> : dataError ? null : <>
                {loadingData && !existing.length && <p role="status">Checking linked accounts…</p>}
                {existing.length > 0 && <SavedSignupStatus
                  signups={existing}
                  accounts={loadingData || accountError ? null : accounts}
                  accountsLoading={loadingData}
                  accountsUnavailable={!!accountError}
                  season={season}
                  onRemaining={() => changeSignupPanel('register', () => { setSignupStep(1); setPool(null) })}
                  onAssignments={() => changeView('assignments')}
                />}
                <SavedSignups key={seasonId} signups={existing} accounts={accounts} editable={memberSignupsOpen(season)} busy={pending || loadingData} canMove={!loadingData && !accountError} headingRef={registeredHeadingRef} onDirty={setSavedSignupDirty} onSave={saveSavedSignups} onWithdraw={rows => void withdraw(rows)} onRefreshAccounts={retrySignupRead}/>
                {!existing.length && <div className="card empty"><p>No signed-up accounts for this season.</p>{memberSignupsOpen(season) && <button onClick={() => changeSignupPanel('register', () => setSignupStep(1))}>Select accounts</button>}</div>}
                <button disabled={pending || loadingData} onClick={retrySignupRead}>Refresh saved signups</button>
              </>}
            </section>}
          </>}
        </>}
        </>}
        {view === 'assignments' && !seasonsKnown && <p role="status">{seasonError ? 'CWL seasons could not be checked.' : 'Loading seasons…'}</p>}
        {view === 'assignments' && seasonsKnown && <MemberAssignments onChange={() => changeView('signup', '', undefined, 'saved')} onSignup={() => { setSignupStep(1); setPool(null); setCompletion(null); changeView('signup', '', undefined, 'register') }} seasonId={seasonId} seasons={seasons} />}
        {view === 'exports' && session.can_edit && <ExportWorkspace seasonId={seasonId} seasons={seasons} onSeasonChange={setSeasonId} />}
        {
          view === "declaration" && session.can_edit && (
            <>
              <CwlPageHeader className="declaration-page-head" title={<h1>Declaration check</h1>}>
                <RosterMenu label="Season" value={seasonId}
                  options={seasons.map(item => ({value: String(item.id), label: item.label}))}
                  onValueChange={id => {
                    const proceed = () => {
                      if (id !== seasonId) navigation.current?.write({view: "declaration", season: id}, false);
                      setSeasonId(id);
                    };
                    if (canLeave(proceed)) proceed();
                  }} />
              </CwlPageHeader>
              {seasonId && (
                <ArrivalCheck
                  key={seasonId}
                  seasonId={seasonId}
                  onFinalize={canOpenPublication("review") ? () => openPublication("review") : undefined}
                  onResults={allowedView("participation") === "participation" ? () => changeView("participation") : undefined}
                  onDirty={setCwlDirty}
                  onWorking={setRosterBusy}
                />
              )}
            </>
          )
        }
        {
          view === "publication" && session.can_edit && (
            <PublicationWorkspace
              onDeclaration={() => changeView("declaration")}
              onPublication={(draft) => setFlowPublication({ season: seasonId, draft })}
              onBusy={setPublicationBusy}
              onDirty={setPublicationDirty}
              step={publicationStep}
              onStepChange={setPublicationStep}
              onNavigateStep={openPublication}
              onFix={(filter) => {
                setRosterReadiness(filter);
                changeView("roster");
              }}
              seasonId={seasonId}
              seasons={seasons}
              onSeasonChange={async (id) => {
                if (
                  !publicationBusy &&
                  (!publicationDirty ||
                    await confirmCwl(
                      "Discard unsaved publication or announcement changes?", "Discard and change season",
                    ))
                ) {
                  if (id !== seasonId)
                    navigation.current?.write(
                      { view: "publication", season: id, step: publicationStep },
                      false,
                    );
                  setSeasonId(id);
                }
              }}
            />
          )
        }
        {view === 'participation' && session.can_edit && <ParticipationWorkspace onBonus={allowedView("bonuses") === "bonuses" ? () => changeView("bonuses") : undefined} onDirty={setCwlDirty} seasonId={seasonId} seasons={seasons} onSeasonChange={setSeasonId} />}
        {view === 'bonuses' && session.can_edit && <BonusWorkspace onDirty={setCwlDirty} seasonId={seasonId} seasons={seasons} onSeasonChange={setSeasonId} />}
        {view === "roster" && session.can_edit && (
          <RosterWorkspace
            onPublication={draft => setFlowPublication({season: seasonId, draft})}
            onClanWeights={(player, clan) =>
              changeView("weight-trial", "", undefined, "register", { player, clan })
            }
            onFamilyClans={() => changeView("clan-management")}
            onBusy={setRosterBusy}
            onDirtySummary={setRosterDirtySummary}
            onEditFocus={element => { rosterEditFocus.current = element }}
            onSeasonRefresh={loadSeasons}
            onDirty={setCwlDirty}
            key={`${seasonId}:${rosterVisit}`}
            initialReadiness={rosterReadiness}
            onReviewPublication={
              allowedView("publication") === "publication"
                ? () => {
                    setPublicationStep("review");
                    changeView("publication");
                  }
                : undefined
            }
            seasonId={seasonId}
            seasons={seasons}
            onSeasonChange={(id) => {
              if (id !== seasonId) navigation.current?.write({ view: "roster", season: id }, false)
              setSeasonId(id);
              setPool(null);
              setSignupPanel("register");
              setDrafts({ main: {}, lazy: {} });
              setReview(false);
              setCompletion(null);
            }}
          />
        )}
        {view === 'staff' && session.can_edit && <SeasonsPage
          key={session.user.id}
          seasonId={seasonId}
          seasons={seasons}
          memberSeason={memberSeason}
          onRefresh={loadSeasons}
          onBusy={setRosterBusy}
          onDirty={setCwlDirty}
          onSeasonChange={id => { const proceed = () => setSeasonId(id); if (canLeave(proceed)) proceed() }}
          onClans={allowedView('roster') === 'roster' ? () => navigateSidebar('roster') : undefined}
        />}
        {session.access_warning && <div className="notice error" role="alert">{session.access_warning}</div>}
        {view === 'issues' && session.is_owner && <DashboardIssues />}
        {view === 'access' && session.is_owner && <AccessSettings onDirty={setCwlDirty} />}
        </RouteLoadBoundary>
      </main>
    </div>

    {session.is_owner && <OwnerPrankBoundary key={session.user.id} onFailure={() => setPrankReadyUser(session.user.id)}>
      <Suspense fallback={null}><OwnerPrank view={view} blockedByTour={tourActive}
        startBlocked={pending || signupBusy.current || signupDirty || rosterBusy || manageDirty || cwlDirty || publicationBusy || publicationDirty || reminderDirty || savedSignupDirty}
        replaySignal={prankReplaySignal}
        onSettled={() => setPrankReadyUser(session.user.id)} onReplayAvailable={setPrankReplayAvailable}
        onError={text => setNotice({kind: 'error', text})} /></Suspense>
    </OwnerPrankBoundary>}
  </div></DashboardPermissions.Provider>
}
function Brand({ large = false }: { large?: boolean }) {
  const image = (
    <img
      className="emblem site-logo"
      src={large ? "/brand/wu-helmet-120.png" : "/brand/wu-helmet-39.png"}
      srcSet={
        large
          ? "/brand/wu-helmet-120.png 1x, /brand/wu-helmet-240.png 2x, /brand/wu-helmet-360.png 3x"
          : "/brand/wu-helmet-39.png 1x, /brand/wu-helmet-78.png 2x, /brand/wu-helmet-117.png 3x"
      }
      alt="Warriors United logo"
      width={large ? 99 : 32}
      height={large ? 120 : 39}
    />
  );
  return (
    <div className={`brand${large ? " brand--large" : ""}`}>
      {large ? (
        <picture>
          <source
            media="(min-width: 900px)"
            type="image/webp"
            srcSet="/brand/wu-helmet-160.webp 1x, /brand/wu-helmet-320.webp 2x, /brand/wu-helmet-480.webp 3x"
          />
          <source
            type="image/webp"
            srcSet="/brand/wu-helmet-120.webp 1x, /brand/wu-helmet-240.webp 2x, /brand/wu-helmet-360.webp 3x"
          />
          <source
            media="(min-width: 900px)"
            type="image/png"
            srcSet="/brand/wu-helmet-160.png 1x, /brand/wu-helmet-320.png 2x, /brand/wu-helmet-480.png 3x"
          />
          {image}
        </picture>
      ) : (
        image
      )}
      <span>
        <strong>WARRIORS UNITED</strong>
        <small>SERVER DASHBOARD</small>
      </span>
    </div>
  );
}
export default App
