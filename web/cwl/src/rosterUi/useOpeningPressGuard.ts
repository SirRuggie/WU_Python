import { useRef, type PointerEvent, type RefObject } from "react";

const onItem = (event: { target: EventTarget }) =>
  (event.target as Element).closest?.('[role="menuitem"]');

/*
 * RAC supports trigger-down → item-up selection. The press that opens a menu
 * must never choose an item that appeared beneath the pointer. Spread
 * `rootProps` on the element around the trigger and `popoverProps` on the
 * Popover; call `release` whenever the menu closes.
 */
export default function useOpeningPressGuard(
  trigger: RefObject<HTMLElement | null>,
  disabled: boolean,
  onCancel: () => void,
) {
  const openingPointer = useRef<number | null>(null);
  const release = () => {
    openingPointer.current = null;
  };
  return {
    release,
    rootProps: {
      onPointerDownCapture: (event: PointerEvent) => {
        if (
          !disabled &&
          event.button === 0 &&
          trigger.current?.contains(event.target as Node)
        )
          openingPointer.current = event.pointerId;
      },
      onPointerCancelCapture: (event: PointerEvent) => {
        if (openingPointer.current === event.pointerId) onCancel();
      },
    },
    popoverProps: {
      onPointerDownCapture: (event: PointerEvent) => {
        if (event.button === 0 && onItem(event)) release();
      },
      onPointerUpCapture: (event: PointerEvent) => {
        if (openingPointer.current !== null && onItem(event)) {
          event.preventDefault();
          event.stopPropagation();
        }
      },
      onClickCapture: (event: React.MouseEvent) => {
        const native = event.nativeEvent as MouseEvent & {
          pointerType?: string;
        };
        const pointerClick =
          event.detail > 0 ||
          ["mouse", "touch", "pen"].includes(native.pointerType || "");
        if (openingPointer.current !== null && pointerClick && onItem(event)) {
          event.preventDefault();
          event.stopPropagation();
        }
      },
    },
  };
}
