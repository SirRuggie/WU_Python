import HelpButton from "./HelpButton";

export default function RosterHelp() {
  return (
    <HelpButton title="How Auto-place works">
      <h3>Auto-place</h3>
      <p>
        Auto-place puts unassigned accounts in a hosting clan. It does not move
        assigned accounts.
      </p>
      <p>Locked accounts do not move. Assign locks an account.</p>
      <h3>One member, many accounts</h3>
      <p>
        Auto-place keeps a member's accounts in the same clan when it can. Main
        and Lazy stay separate.
      </p>
      <p>
        If the member already has accounts in a clan, new accounts go there.
        Locked accounts decide the clan first.
      </p>
      <p>Clan size and weight rules come first.</p>
      <p>
        If the accounts do not fit, Auto-place uses as few clans as possible.
        The preview marks each split account.
      </p>
      <h3>Order</h3>
      <p>
        Heaviest accounts go first, to the clan with the fewest accounts, then
        the lowest total weight.
      </p>
      <p>Accounts with no weight stay unplaced.</p>
      <h3>Balance</h3>
      <p>
        Balance moves only the accounts you select. It does not keep a member's
        accounts together.
      </p>
    </HelpButton>
  );
}
