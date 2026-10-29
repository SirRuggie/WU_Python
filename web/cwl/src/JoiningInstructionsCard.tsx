export default function JoiningInstructionsCard({ text }: { text: string }) {
  return (
    <section className="card">
      <h2>Joining instructions</h2>
      <p style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{text}</p>
    </section>
  );
}
