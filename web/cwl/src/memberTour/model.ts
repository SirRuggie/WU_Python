export const TOUR_KEY = "wu-member-tour-v1";
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
    text: "Start here — Home shows what to do next: your CWL status and reminders.",
    art: "U31",
    target: "home",
  },
  {
    number: 3,
    title: "Tasks",
    text: "Never miss a hit — your attacks and events live here.",
    art: "U24",
    target: "todo",
  },
  {
    number: 4,
    title: "Sign up",
    text: "Every month, sign up for CWL right here. Let's practice with a pretend account.",
    art: "U09",
    target: "register",
  },
  {
    number: 5,
    title: "Choose your account",
    text: "Tap the account you want to sign up.",
    art: "U10",
    target: "demo-account",
  },
  {
    number: 5,
    title: "Choose a pool",
    text: "Pick Main or Lazy CWL. We'll pick Lazy.",
    art: "U10",
    target: "demo-pool",
  },
  {
    number: 5,
    title: "Review",
    text: "Check it and confirm.",
    art: "U10",
    target: "demo-review",
  },
  {
    number: 5,
    title: "Confirm",
    text: "Check it and confirm.",
    art: "U10",
    target: "demo-confirm",
  },
  {
    number: 5,
    title: "You're in!",
    text: "You're in! (practice — nothing saved)",
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
    text: "Going crazy wondering if you signed up? Check here!",
    art: "U32",
    target: "saved",
  },
  {
    number: 7,
    title: "My clan assignments",
    text: "Don't be like the King — once the roster is ready, your clan shows right here with an Open clan button.",
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

export const policyUrl = "https://supercell.com/en/fan-content-policy/";
export const policyNotice =
  "This material is unofficial and is not endorsed by Supercell. For more information see Supercell's Fan Content Policy:";
