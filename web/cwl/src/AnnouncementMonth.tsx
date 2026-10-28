import { useState } from "react";
import { Button, Input } from "./rosterUi/primitives";
import { announcementMonthLabel } from "./announcementMonth";
export default function AnnouncementMonth({
  value,
  linked,
  disabled,
  onChange,
  onLoad,
}: {
  value: string;
  linked: string | null;
  disabled: boolean;
  onChange: (value: string) => void;
  onLoad: () => void;
}) {
  const [editing, setEditing] = useState(false);
  return (
    <div className="manage-cycle-fields">
      {value && (
        <div>
          CWL month: {announcementMonthLabel(value)}{" "}
          <Button disabled={disabled} onClick={() => setEditing(true)}>
            Change
          </Button>
        </div>
      )}
      {(editing || !value) && (
        <Input
          label="CWL month"
          type="month"
          value={value}
          disabled={disabled}
          onChange={(event) => onChange(event.target.value)}
        />
      )}
      {value !== linked && (
        <Button
          variant="primary"
          disabled={disabled || !/^\d{4}-(0[1-9]|1[0-2])$/.test(value)}
          onClick={onLoad}
        >
          {linked ? "Change month" : `Load ${announcementMonthLabel(value)}`}
        </Button>
      )}
    </div>
  );
}
