import { useId } from "react";
import type { PostCopy } from "./announcementPostUpdate";
export default function AnnouncementPostCopyEditor({
  value,
  onChange,
  disabled,
}: {
  value: PostCopy;
  onChange: (value: PostCopy) => void;
  disabled: boolean;
}) {
  const id = useId();
  const buttonChange = (
    index: number,
    field: "label" | "url" | "emoji",
    text: string,
  ) =>
    onChange({
      ...value,
      buttons: value.buttons.map((button, i) =>
        i === index ? { ...button, [field]: text } : button,
      ),
    });
  return (
    <div className="announcement-post-copy">
      <label htmlFor={`${id}-title`}>Title</label>
      <input
        id={`${id}-title`}
        value={value.title}
        maxLength={4000}
        disabled={disabled}
        onChange={(e) => onChange({ ...value, title: e.target.value })}
      />
      <label htmlFor={`${id}-body`}>Message</label>
      <textarea
        id={`${id}-body`}
        rows={7}
        value={value.body}
        maxLength={4000}
        disabled={disabled}
        onChange={(e) => onChange({ ...value, body: e.target.value })}
      />
      <p>
        {(value.title.length + value.body.length).toLocaleString()} / 4,000 text
        characters. Discord formatting and existing images are preserved.
      </p>
      <fieldset disabled={disabled}>
        <legend>Link buttons ({value.buttons.length} / 5)</legend>
        {value.buttons.map((button, index) => (
          <fieldset key={index}>
            <legend>Link {index + 1}</legend>
            <label htmlFor={`${id}-${index}-label`}>Button label</label>
            <input
              id={`${id}-${index}-label`}
              value={button.label}
              maxLength={80}
              onChange={(e) => buttonChange(index, "label", e.target.value)}
            />
            <label htmlFor={`${id}-${index}-url`}>HTTPS address</label>
            <input
              id={`${id}-${index}-url`}
              type="url"
              value={button.url}
              maxLength={512}
              onChange={(e) => buttonChange(index, "url", e.target.value)}
            />
            <label htmlFor={`${id}-${index}-emoji`}>Emoji (optional)</label>
            <input
              id={`${id}-${index}-emoji`}
              value={button.emoji || ""}
              maxLength={64}
              onChange={(e) => buttonChange(index, "emoji", e.target.value)}
            />
            <button
              type="button"
              aria-label={`Remove link ${index + 1}`}
              onClick={() =>
                onChange({
                  ...value,
                  buttons: value.buttons.filter((_, i) => i !== index),
                })
              }
            >
              Remove link
            </button>
          </fieldset>
        ))}
        <button
          type="button"
          disabled={value.buttons.length >= 5}
          onClick={() =>
            onChange({
              ...value,
              buttons: [...value.buttons, { label: "", url: "" }],
            })
          }
        >
          Add link
        </button>
      </fieldset>
    </div>
  );
}
