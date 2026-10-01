import { AlertTriangle, X } from 'lucide-react';
import { useEffect, useState } from 'react';

interface DeleteConfirmationModalProps {
  isOpen: boolean;
  onClose: () => void;
  onConfirm: () => void;
  title?: string;
  message?: string;
  isLoading?: boolean;
}

const DeleteConfirmationModal = ({
  isOpen,
  onClose,
  onConfirm,
  title = "Delete Confirmation",
  message = "Are you sure you want to delete this item? This action cannot be undone.",
  isLoading = false,
}: DeleteConfirmationModalProps) => {
  const [isAnimating, setIsAnimating] = useState(false);
  const [shouldRender, setShouldRender] = useState(false);

  useEffect(() => {
    if (isOpen) {
      setShouldRender(true);
      // Small delay to trigger animation
      const timer = setTimeout(() => setIsAnimating(true), 10);
      return () => clearTimeout(timer);
    } else {
      setIsAnimating(false);
      // Wait for animation to finish before unmounting
      const timer = setTimeout(() => setShouldRender(false), 300);
      return () => clearTimeout(timer);
    }
  }, [isOpen]);

  useEffect(() => {
    const handleEsc = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    if (isOpen) {
      window.addEventListener('keydown', handleEsc);
      document.body.style.overflow = 'hidden';
    }
    return () => {
      window.removeEventListener('keydown', handleEsc);
      document.body.style.overflow = 'unset';
    };
  }, [isOpen, onClose]);

  if (!shouldRender) return null;

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center p-4 sm:p-6">
      {/* Backdrop */}
      <div
        className={`absolute inset-0 bg-black/60 backdrop-blur-[2px] transition-opacity duration-300 ease-out ${
          isAnimating ? 'opacity-100' : 'opacity-0'
        }`}
        onClick={onClose}
      />

      {/* Modal Container */}
      <div
        className={`relative w-full max-w-md transform overflow-hidden rounded-12 border border-border-default bg-surface-card p-6 shadow-2xl transition-all duration-300 ease-out sm:max-w-sm ${
          isAnimating
            ? 'translate-y-0 scale-100 opacity-100'
            : 'translate-y-10 scale-95 opacity-0 sm:translate-y-4'
        } ${
          // Mobile: bottom sheet style
          'fixed bottom-0 left-0 right-0 rounded-t-2xl rounded-b-none sm:relative sm:bottom-auto sm:rounded-12'
        }`}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Close Button */}
        <button
          onClick={onClose}
          className="absolute right-4 top-4 rounded-8 p-1 text-text-muted hover:bg-surface-primary hover:text-text-dark transition-colors cursor-pointer"
          aria-label="Close modal"
        >
          <X size={18} />
        </button>

        <div className="flex flex-col items-center text-center">
          {/* Warning Icon with pulse effect */}
          <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-state-danger/10 relative">
            <div
              className={`absolute inset-0 rounded-full bg-state-danger/20 animate-ping opacity-30 ${
                isLoading ? 'hidden' : 'block'
              }`}
            />
            <AlertTriangle className="h-6 w-6 text-state-danger relative z-10" />
          </div>

          <h3 className="mb-2 text-base font-bold text-text-dark">{title}</h3>
          <p className="mb-6 text-xs leading-relaxed text-text-muted">
            {message}
          </p>

          <div className="flex w-full flex-col gap-2.5 sm:flex-row sm:justify-end">
            <button
              onClick={onClose}
              disabled={isLoading}
              className="order-2 w-full rounded-8 border border-border-default bg-surface-card px-4 py-2.5 text-xs font-semibold text-text-muted transition-all hover:text-text-dark hover:bg-surface-primary active:scale-95 disabled:opacity-50 sm:order-1 sm:w-auto sm:min-w-[80px] cursor-pointer"
            >
              Cancel
            </button>
            <button
              onClick={onConfirm}
              disabled={isLoading}
              className="order-1 w-full rounded-8 bg-state-danger px-4 py-2.5 text-xs font-semibold text-white shadow-xs transition-all hover:opacity-90 active:scale-95 disabled:opacity-70 sm:order-2 sm:w-auto sm:min-w-[80px] flex items-center justify-center gap-2 cursor-pointer"
            >
              {isLoading ? (
                <>
                  <svg className="h-3.5 w-3.5 animate-spin text-white" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
                  </svg>
                  <span>Deleting...</span>
                </>
              ) : (
                'Delete'
              )}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};

export default DeleteConfirmationModal;
