import type { ManagementDocument } from "./serverManagement";

export default function WarriorDeskStatus({
  document,
  dirty,
}: {
  document: ManagementDocument;
  dirty: boolean;
}) {
  const status = document.desk_readiness;
  if (!status) return null;
  return (
    <section className="warrior-desk-status" aria-label="Warrior Desk status">
      <h2>
        {status.live
          ? "Panel is live"
          : status.ready
            ? "Ready to post"
            : "Complete setup"}
      </h2>
      {status.missing.length > 0 && (
        <ul>
          {status.missing.map((item) => (
            <li key={item.key || "rollout"}>
              {item.key === "main_staff_parent" ? (
                "Set the Main staff channel in Main application channels."
              ) : item.key ? (
                <a
                  href={`#manage-${item.key.replace(/[^a-z0-9]/gi, "-")}`}
                  onClick={(event) => {
                    event.preventDefault();
                    const field = window.document.getElementById(
                      `manage-${item.key.replace(/[^a-z0-9]/gi, "-")}`,
                    );
                    field?.scrollIntoView?.({ block: "center" });
                    field?.focus();
                  }}
                >
                  Select {item.label}
                </a>
              ) : (
                "Enable the ticket thread workflow"
              )}
            </li>
          ))}
        </ul>
      )}
      {dirty ? (
        <p>Save your changes before posting or repairing the panel.</p>
      ) : (
        status.ready && (
          <p>
            {status.live
              ? "Repair the existing panel if it is missing or out of date."
              : "Your settings are saved. Post the panel when you are ready."}
          </p>
        )
      )}
    </section>
  );
}
