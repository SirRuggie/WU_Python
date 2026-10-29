export type Branch = "yes" | "no" | null;

export type PrankState = {
  card: number;
  branch: Branch;
  completed_at: string | null;
  run: number;
  signup_count: number;
  can_replay: boolean;
};

export type PrankEvent =
  | "prank_opened"
  | "prank_bait_yes"
  | "prank_bait_no"
  | "prank_card_seen"
  | "prank_jumpscare_seen"
  | "prank_rickroll_seen"
  | "prank_encore_1"
  | "prank_encore_2"
  | "prank_encore_3"
  | "prank_encore_4"
  | "prank_completed"
  | "prank_closed_early"
  | "prank_replay";

export type Card = {
  title: string;
  body: string;
  buttons: string[];
  art?: string;
};

const asset = (name: string) => `/api/cwl/prank/assets/${name}.webp`;

export function cardFor(number: number, branch: Branch, count: number): Card {
  switch (number) {
    case 1:
      return {
        title: "Remove all signups?",
        body: "This will remove every CWL signup for November 2026.",
        buttons: ["Yes", "No"],
      };
    case 2:
      return {
        title: "Working...",
        body: `Deleted ${count}/${count} signups`,
        buttons: [],
      };
    case 3:
      return branch === "yes"
        ? {
            title: "HEY!! WHAT ARE YOU DOING?!",
            body: "Chief, you really hit Yes with full confidence. Bold. Terrifying. Very owner behavior.",
            buttons: ["Uh oh"],
            art: asset("78096"),
          }
        : {
            title: "HEY!! WHAT ARE YOU DOING?!",
            body: 'You pressed No and STILL looked guilty. That\'s elite "trust me" button energy.',
            buttons: ["I pressed No?!"],
            art: asset("78096"),
          };
    case 4:
      return {
        title: "Buttons Fear You",
        body: "Are you REALLY sure you should be allowed near admin buttons without supervision?",
        buttons: ["I can explain", "Rude"],
        art: asset("97730"),
      };
    case 5:
      return {
        title: "Trust Me, He Says",
        body: '"I know what I\'m doing." The famous last words before someone has to rebuild the entire base.',
        buttons: ["Fair point", "Keep going"],
        art: asset("102860"),
      };
    case 6:
      return {
        title: "Relax, Nothing Broke",
        body: `Got you. Nothing was deleted. All ${count} signups are safe. Your judgment, however, remains under review.`,
        buttons: ["Seriously?", "I knew that"],
        art: asset("97711"),
      };
    case 7:
      return {
        title: "We've Got Your Back",
        body: "We roast your decisions, Chief, but we'd still defend your Clan Castle with our last troop.",
        buttons: ["Go on"],
        art: asset("160053"),
      };
    case 8:
      return {
        title: "A Promise From Your Troops",
        body: "No abandoning your base. No disappearing mid-war. No pretending we don't know you when things go wrong.",
        buttons: ["That's touching"],
        art: asset("97730"),
      };
    case 9:
      return {
        title: "Sound Familiar Yet?",
        body: "We'd stand beside you through every bad attack, awkward decision, and suspicious button click. Forever loyal, Chief.",
        buttons: ["Wait a second"],
        art: asset("97730"),
      };
    case 10:
      return {
        title: "YOU'VE BEEN RICKROLLED!",
        body: "HA! Ruggie sends his regards. Your signups survived. Your dignity wasn't so fortunate.",
        buttons: ["Dismiss"],
        art: asset("102809"),
      };
    case 11:
      return {
        title: "LOL. You Thought.",
        body: "Did you REALLY think one little dismiss button was going to save you from Ruggie?",
        buttons: ["Let me out"],
        art: asset("102809"),
      };
    case 12:
      return {
        title: "A Message From Your Troops",
        body: "The Minion would like to formally invite you to kiss his royal purple butt. Respectfully, of course.",
        buttons: ["That's enough"],
        art: asset("102888"),
      };
    case 13:
      return {
        title: "Am I Annoying You Yet?",
        body: "Because personally, I feel like we're making excellent progress. Your patience is almost completely upgraded.",
        buttons: ["PLEASE STOP"],
        art: asset("102845"),
      };
    case 14:
      return {
        title: "One Last Thing, Chief...",
        body: "Next time you see a big scary admin button, maybe ask Ruggie to supervise you. Just a thought.",
        buttons: ["I'm begging"],
        art: asset("102845"),
      };
    case 15:
      return {
        title: "Well, Look Who Survived.",
        body: "Thanks for your trouble, Big Poppa. See you soon. 😉 Now go run your server before Ruggie finds another button.",
        buttons: ["Finally Free"],
        art: asset("final-aq"),
      };
    default:
      throw new Error("Invalid prank card");
  }
}

export const rickrollUrl =
  "https://media.tenor.com/x8v1oNUOmg4AAAAM/rickroll-roll.gif";

export function milestone(number: number): PrankEvent | null {
  if (number === 3) return "prank_jumpscare_seen";
  if (number === 10) return "prank_rickroll_seen";
  if (number >= 11 && number <= 14)
    return `prank_encore_${number - 10}` as PrankEvent;
  return null;
}
