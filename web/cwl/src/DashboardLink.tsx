import type { AnchorHTMLAttributes, MouseEvent } from "react";

type Props = Omit<AnchorHTMLAttributes<HTMLAnchorElement>, "href"> & {
  href: string;
  /** The in-app navigation the matching button used to call. */
  onNavigate: () => void;
  disabled?: boolean;
};

/**
 * Internal dashboard link. While disabled it has no href, so no click
 * (including middle-click) can navigate. A plain primary click uses the in-app router;
 * modified and non-primary clicks keep the browser's own link behavior.
 */
export default function DashboardLink({
  href,
  onNavigate,
  disabled = false,
  onClick,
  ...rest
}: Props) {
  const click = (event: MouseEvent<HTMLAnchorElement>) => {
    onClick?.(event);
    if (disabled) {
      event.preventDefault();
      return;
    }
    if (
      event.defaultPrevented ||
      event.button !== 0 ||
      event.ctrlKey ||
      event.metaKey ||
      event.shiftKey ||
      event.altKey
    )
      return;
    event.preventDefault();
    onNavigate();
  };
  return (
    <a
      {...rest}
      href={disabled ? undefined : href}
      role={disabled ? "link" : undefined}
      aria-disabled={disabled || undefined}
      onClick={click}
    />
  );
}
