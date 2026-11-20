import type { ComponentProps } from "react";
import { SlidersHorizontal } from "lucide-react";
import { Button } from "./primitives";

type Props = Omit<ComponentProps<typeof Button>, "children" | "icon"> & {
  count: number;
  open: boolean;
};

/** The page owns the ActionPanel and passes its current expanded state. */
export default function FiltersTrigger({ count, open, ...props }: Props) {
  return (
    <Button {...props} icon={SlidersHorizontal} aria-expanded={open}>
      Filters{count ? ` · ${count}` : ""}
    </Button>
  );
}
