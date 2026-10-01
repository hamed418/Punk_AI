import type { ReactNode } from 'react';

interface SecondaryBtnProps {
  children: ReactNode;
  className?: string;
  onClick?: () => void;
  leftSection?: ReactNode | null;
  altered?: boolean;
  disabled?: boolean;
}

const cn = (...classes: (string | undefined)[]) =>
  classes.filter(Boolean).join(' ');

const SecondaryBtn = ({
  children,
  className,
  onClick,
  leftSection = null,
  disabled = false,
}: SecondaryBtnProps) => {
  return (
    <button
      className={cn(
        "btn-secondary-professional disabled:opacity-50 disabled:cursor-not-allowed",
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

export default SecondaryBtn;