import { createRoot } from "react-dom/client";
import BaseBank from "../../src/BaseBank";
import "../../src/style.css";
const query = new URLSearchParams(location.search);
const link =
  "https://link.clashofclans.com/en?action=OpenLayout&id=isolated-fixture";
let details = 0;
Object.assign(window, { detailReads: () => details });
window.fetch = async (input, options) => {
  const url = new URL(String(input), location.origin);
  if (
    url.origin !== location.origin ||
    (options?.method && options.method !== "GET") ||
    url.pathname !== "/api/cwl/bases"
  )
    throw new Error("Disconnected Base bank fixture");
  if (query.has("failure")) return new Response("Unavailable", { status: 503 });
  if (query.has("denied")) return new Response("Sign in", { status: 403 });
  const level = url.searchParams.get("level");
  if (level) {
    details++;
    return Response.json({
      key: level,
      base_information:
        "Sample only. Keep the war base layout intact.\n<img src=x> is plain text here.",
      base_upgrade_notes: "Use the non-merged option when upgrading defenses.",
    });
  }
  return Response.json({
    bases: query.has("empty")
      ? []
      : [
          {
            key: "th18",
            town_hall: 18,
            variant: "merged",
            link,
            war_base_image: "/sample-war-base.svg",
            has_details: true,
          },
          {
            key: "th18_new",
            town_hall: 18,
            variant: "non-merged",
            link: query.has("missing") ? null : link,
            war_base_image: query.has("missing")
              ? null
              : "/sample-war-base.svg",
            has_details: true,
          },
          {
            key: "th17",
            town_hall: 17,
            variant: "merged",
            link,
            war_base_image: "/sample-war-base.svg",
            has_details: false,
          },
          {
            key: "th16",
            town_hall: 16,
            variant: "merged",
            link,
            war_base_image: null,
            has_details: false,
          },
        ],
  });
};
createRoot(document.getElementById("root")!).render(
  <main style={{ padding: "16px", maxWidth: "1240px", margin: "auto" }}>
    <p style={{ color: "#b4b7bf", fontSize: "12px" }}>
      Isolated sample layouts · Copy links are disconnected fixtures
    </p>
    <BaseBank townHalls={query.has("linked17") ? [17] : [18]} />
  </main>,
);
