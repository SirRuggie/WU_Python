import HelpButton from "./HelpButton";

export default function DeclarationHelp() {
  return (
    <HelpButton title="About readiness" className="declaration-help-panel">
      <h3>Ready</h3>
      <p>The clan is full, checked in the last 5 minutes.</p>
      <h3>Which clans</h3>
      <p>This check works only for Lazy hosting clans.</p>
    </HelpButton>
  );
}
