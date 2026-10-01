import type { ReactNode } from "react";

interface PrimaryBtnProps {
  children: ReactNode;
  className?: string;
  onClick?: () => void;
  leftSection?: ReactNode | null;
  altered?: boolean;
  disabled?: boolean;
}

const cn = (...classes: (string | undefined)[]) =>
  classes.filter(Boolean).join(" ");

const PrimaryBtn = ({
  children,
  className,
  onClick,
  leftSection = null,
  disabled = false,
}: PrimaryBtnProps) => {
  return (
    <button
      className={cn(
        "btn-professional disabled:opacity-50 disabled:cursor-not-allowed",
        className,
      )}
      onClick={onClick}
      disabled={disabled}
    >
      {leftSection && <span>{leftSection}</span>}
      {children}
    </button>
  );
};

export default PrimaryBtn;
