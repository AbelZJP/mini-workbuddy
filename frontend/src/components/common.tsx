import React, { useEffect, useRef, useState } from "react";

export function ThemeSelect({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string;
  options: { value: string; label: string }[];
  onChange: (value: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const selectRef = useRef<HTMLDivElement | null>(null);
  const selected = options.find((option) => option.value === value);

  useEffect(() => {
    const close = (event: MouseEvent) => {
      if (
        selectRef.current &&
        !selectRef.current.contains(event.target as Node)
      )
        setOpen(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);

  useEffect(() => {
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("keydown", closeOnEscape);
    return () => document.removeEventListener("keydown", closeOnEscape);
  }, []);

  return (
    <div className={`theme-select ${open ? "open" : ""}`} ref={selectRef}>
      <button
        type="button"
        className="theme-select-trigger"
        onClick={() => setOpen((current) => !current)}
        aria-expanded={open}
      >
        <span className="theme-select-label">{label}</span>
        <span className="theme-select-value">{selected?.label || value}</span>
        <span className="theme-select-chevron">⌄</span>
      </button>
      {open && (
        <div className="theme-select-menu" role="listbox">
          {options.map((option) => (
            <button
              type="button"
              role="option"
              aria-selected={option.value === value}
              className={`theme-select-option ${option.value === value ? "selected" : ""}`}
              key={option.value}
              onClick={() => {
                onChange(option.value);
                setOpen(false);
              }}
            >
              <span>{option.label}</span>
              {option.value === value && <span>✓</span>}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

export function ManagementShell({
  eyebrow,
  title,
  subtitle,
  action,
  onAction,
  children,
}: {
  eyebrow: string;
  title: string;
  subtitle: string;
  action: string;
  onAction: () => void;
  children: React.ReactNode;
}) {
  return (
    <section className="management">
      <header className="topbar">
        <div>
          <span className="eyebrow">{eyebrow}</span>
          <h1>{title}</h1>
          <p>{subtitle}</p>
        </div>
        <div className="top-actions">
          <button className="primary-button" onClick={onAction}>
            ＋ {action}
          </button>
        </div>
      </header>
      {children}
    </section>
  );
}
export function EmptyCard({ text }: { text: string }) {
  return <div className="empty-card">{text}</div>;
}
export function DetailModal({
  title,
  content,
  onClose,
}: {
  title: string;
  content: string;
  onClose: () => void;
}) {
  return (
    <div className="modal-backdrop">
      <div className="modal wide">
        <div className="modal-head">
          <h2>{title}</h2>
          <button onClick={onClose}>×</button>
        </div>
        <pre className="detail-content">{content}</pre>
      </div>
    </div>
  );
}
