import React, { useState } from "react";
import { createRoot } from "react-dom/client";
import DiscordPreview, { type PreviewPart } from "../../src/DiscordPreview";
import panels from "@warrior-panels";
function Preview() {
  const examples = panels as Record<string, PreviewPart[]>;
  const [selected, setSelected] = useState("Preview");
  return (
    <main
      style={{
        maxWidth: 1100,
        margin: "auto",
        padding: 16,
        color: "#eee",
        fontFamily: "sans-serif",
      }}
    >
      <h1>Warrior profile fixture</h1>
      <p>
        Approximate Discord rendering from the real wizard builders. These
        controls cannot rename or save anything.
      </p>
      <label>
        Example{" "}
        <select
          aria-label="Example"
          value={selected}
          onChange={(event) => setSelected(event.target.value)}
          style={{ minHeight: 44 }}
        >
          {Object.keys(examples).map((name) => (
            <option key={name}>{name}</option>
          ))}
        </select>
      </label>
      <DiscordPreview parts={examples[selected]} label={selected} />
    </main>
  );
}
createRoot(document.getElementById("root")!).render(<Preview />);
