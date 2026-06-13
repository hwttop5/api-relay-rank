"use client";

import { ChevronDown, Check } from "lucide-react";
import { useEffect, useId, useMemo, useRef, useState, type KeyboardEvent } from "react";

export type SelectControlOption<T extends string | number = string> = {
  label: string;
  value: T;
};

type SelectControlProps<T extends string | number> = {
  ariaLabel: string;
  className?: string;
  disabled?: boolean;
  name?: string;
  onChange: (value: T) => void;
  options: ReadonlyArray<SelectControlOption<T>>;
  value: T;
};

export function SelectControl<T extends string | number>({
  ariaLabel,
  className,
  disabled = false,
  name,
  onChange,
  options,
  value,
}: SelectControlProps<T>) {
  const generatedId = useId();
  const rootRef = useRef<HTMLDivElement | null>(null);
  const buttonRef = useRef<HTMLButtonElement | null>(null);
  const optionRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const [open, setOpen] = useState(false);
  const selectedIndex = options.findIndex((option) => option.value === value);
  const selectedOption = selectedIndex >= 0 ? options[selectedIndex] : options[0];
  const listboxId = `${generatedId}-listbox`;
  const selectedOptionId = selectedIndex >= 0 ? `${generatedId}-option-${selectedIndex}` : undefined;

  const hiddenValue = useMemo(() => String(value), [value]);

  useEffect(() => {
    if (!open) {
      return;
    }

    function onPointerDown(event: PointerEvent) {
      if (!rootRef.current?.contains(event.target as Node)) {
        setOpen(false);
      }
    }

    document.addEventListener("pointerdown", onPointerDown);
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, [open]);

  useEffect(() => {
    if (!open) {
      return;
    }

    const focusIndex = selectedIndex >= 0 ? selectedIndex : 0;
    window.requestAnimationFrame(() => {
      optionRefs.current[focusIndex]?.focus();
    });
  }, [open, selectedIndex]);

  function commitOption(index: number) {
    const option = options[index];
    if (!option) {
      return;
    }
    onChange(option.value);
    setOpen(false);
    window.requestAnimationFrame(() => buttonRef.current?.focus());
  }

  function focusOption(index: number) {
    const nextIndex = (index + options.length) % options.length;
    optionRefs.current[nextIndex]?.focus();
  }

  function currentFocusedIndex() {
    return optionRefs.current.findIndex((option) => option === document.activeElement);
  }

  function onButtonKeyDown(event: KeyboardEvent<HTMLButtonElement>) {
    if (disabled) {
      return;
    }
    if (event.key === "Escape" && open) {
      event.preventDefault();
      setOpen(false);
      return;
    }
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setOpen(true);
      window.requestAnimationFrame(() => focusOption((selectedIndex >= 0 ? selectedIndex : 0) + 1));
      return;
    }
    if (event.key === "ArrowUp") {
      event.preventDefault();
      setOpen(true);
      window.requestAnimationFrame(() => focusOption((selectedIndex >= 0 ? selectedIndex : 0) - 1));
      return;
    }
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      setOpen((current) => !current);
    }
  }

  function onOptionKeyDown(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      focusOption(index + 1);
      return;
    }
    if (event.key === "ArrowUp") {
      event.preventDefault();
      focusOption(index - 1);
      return;
    }
    if (event.key === "Home") {
      event.preventDefault();
      focusOption(0);
      return;
    }
    if (event.key === "End") {
      event.preventDefault();
      focusOption(options.length - 1);
      return;
    }
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      commitOption(index);
      return;
    }
    if (event.key === "Escape") {
      event.preventDefault();
      setOpen(false);
      buttonRef.current?.focus();
      return;
    }
    if (event.key === "Tab") {
      setOpen(false);
    }
  }

  return (
    <div ref={rootRef} className={["select-control", className].filter(Boolean).join(" ")} data-open={open ? "true" : undefined}>
      {name ? <input type="hidden" name={name} value={hiddenValue} disabled={disabled} /> : null}
      <button
        ref={buttonRef}
        type="button"
        className="select-control-trigger"
        aria-label={ariaLabel}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={listboxId}
        aria-activedescendant={open ? selectedOptionId : undefined}
        disabled={disabled}
        onClick={() => {
          if (!disabled) {
            setOpen((current) => !current);
          }
        }}
        onKeyDown={onButtonKeyDown}
      >
        <span>{selectedOption?.label ?? ""}</span>
        <ChevronDown size={15} aria-hidden="true" />
      </button>
      {open ? (
        <div className="select-control-menu" id={listboxId} role="listbox" aria-label={ariaLabel}>
          {options.map((option, index) => {
            const selected = option.value === value;
            return (
              <button
                key={String(option.value)}
                ref={(node) => {
                  optionRefs.current[index] = node;
                }}
                type="button"
                id={`${generatedId}-option-${index}`}
                className="select-control-option"
                role="option"
                aria-selected={selected}
                data-selected={selected ? "true" : undefined}
                tabIndex={-1}
                onClick={() => commitOption(index)}
                onFocus={() => {
                  if (currentFocusedIndex() < 0) {
                    optionRefs.current[index]?.focus();
                  }
                }}
                onKeyDown={(event) => onOptionKeyDown(event, index)}
              >
                <span>{option.label}</span>
                {selected ? <Check size={14} aria-hidden="true" /> : null}
              </button>
            );
          })}
        </div>
      ) : null}
    </div>
  );
}
