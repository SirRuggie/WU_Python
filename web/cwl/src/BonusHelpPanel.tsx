import HelpButton from "./HelpButton";

export default function BonusHelpPanel() {
  return (
    <HelpButton title="How bonuses work" className="bonus-help-panel">
      <h3>Bonus count</h3>
      <p>It comes from the CWL league, plus 1 for each war win.</p>
      <h3>Who qualifies</h3>
      <p>
        Main: the minimum attacks in the Rules step. Lazy: 4+ attacks, or 3+
        attacks and 8+ stars. One bonus per account each month.
      </p>
      <h3>Infractions (Lazy)</h3>
      <p>
        Missed sync, Lingering or Left family removes the account this month. A
        staff reason can put it back.
      </p>
      <h3>Sit-out after a win (Lazy)</h3>
      <p>
        A winner sits out for a set number of months. Each clan sets its number
        in Settings. Default 3. Example: October win, 3 months → can win again
        in February. FWA Rep accounts do not sit out.
      </p>
      <h3>Draw</h3>
      <p>
        Winners are drawn at random. FWA Rep accounts (1 per member, selected in
        Settings) have 2× the chance in Lazy.
      </p>
    </HelpButton>
  );
}
