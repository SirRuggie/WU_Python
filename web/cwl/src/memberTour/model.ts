export const TOUR_KEY = "wu-member-tour-v1";
export const SESSION_KEY = "wu-member-tour-session-v1";
export function invitedThisSession() {
  try {
    return sessionStorage.getItem(SESSION_KEY) === "1";
  } catch {
    return false;
  }
}
export function rememberSession() {
  try {
    sessionStorage.setItem(SESSION_KEY, "1");
  } catch {
    /* Optional memory. */
  }
}
export const artAspect: Record<string, number> = {
  U33: 2818 / 2835,
  U31: 1816 / 3020,
  U24: 1791 / 1944,
  U09: 881 / 1222,
  U35: 276 / 340,
  U13: 273 / 340,
  U18: 265 / 340,
  U15: 323 / 340,
  U34: 1224 / 2051,
  U01: 3251 / 1433,
  U32: 1063 / 2083,
  king: 278 / 319,
  U14: 1814 / 3408,
};
export type Preference = { skips: number; dismissed: boolean };
export function readPreference(): Preference {
  try {
    const value = JSON.parse(localStorage.getItem(TOUR_KEY) || "null");
    if (
      value &&
      Number.isInteger(value.skips) &&
      value.skips >= 0 &&
      value.skips <= 3 &&
      typeof value.dismissed === "boolean"
    )
      return value;
  } catch {
    /* Optional browser memory. */
  }
  return { skips: 0, dismissed: false };
}
export function savePreference(value: Preference) {
  try {
    localStorage.setItem(TOUR_KEY, JSON.stringify(value));
  } catch {
    /* Private mode. */
  }
}
export function shouldInvite(value: Preference) {
  return !value.dismissed && value.skips < 3;
}
export function skipPreference(value: Preference): Preference {
  return { ...value, skips: Math.min(3, value.skips + 1) };
}

export const steps = [
  {
    number: 1,
    title: "Hey Chief! Welcome to Warriors United!",
    text: "Let's take a minute to show you around.",
    art: "U33",
    target: "",
  },
  {
    number: 2,
    title: "Home",
    text: "Tap Home — it shows what to do next: your CWL status and reminders.",
    art: "U31",
    target: "home",
  },
  {
    number: 3,
    title: "Tasks",
    text: "Tap Tasks — your attacks and events live here.",
    art: "U24",
    target: "todo",
  },
  {
    number: 4,
    title: "Sign up",
    text: "Every month, sign up for CWL right here. Tap Sign up — we will practice without saving.",
    art: "U09",
    target: "register",
  },
  {
    number: 5,
    title: "Choose a pool",
    text: "Pick Main or Lazy CWL. Tap Lazy CWL — we'll practice with Lazy.",
    art: "U35",
    target: "signup-pool",
  },
  {
    number: 5,
    title: "Choose your account",
    text: "Tap an account to select it.",
    art: "U13",
    target: "signup-account",
  },
  {
    number: 5,
    title: "Review",
    text: "Check your picks here.",
    art: "U18",
    target: "signup-review",
  },
  {
    number: 5,
    title: "Sign up",
    text: "This is the button that saves it. Tap it for real when you're ready — in the tour we stop here, so nothing is saved.",
    art: "U15",
    target: "signup-confirm",
  },
  {
    number: 5,
    title: "That's all it takes!",
    text: "Practice — nothing saved.",
    art: "U34",
    target: "",
  },
  {
    number: 5,
    title: "Don't sleep on the job!",
    text: "That was just practice. Sign up for real every month before signups close.",
    art: "U01",
    target: "",
  },
  {
    number: 6,
    title: "My signups",
    text: "Tap My signups to check which accounts you signed up.",
    art: "U32",
    target: "saved",
  },
  {
    number: 7,
    title: "My clan assignments",
    text: "Tap My clan assignments — once the roster is ready, your clan shows here with an Open clan button.",
    art: "king",
    target: "assignments",
  },
  {
    number: 8,
    title: "You're all set!",
    text: "Tap ? (bottom-left) anytime to see this again. In Discord, Check my signups works too.",
    art: "U14",
    target: "",
  },
] as const;
