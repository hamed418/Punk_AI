import { Box, Text } from '@mantine/core'
import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import SecondaryBtn from './secondaryBtn'
import PrimaryBtn from './PrimaryBtn'

interface DeleteConfirmationModalProps {
  isOpen: boolean
  onClose: () => void
  onConfirm: () => void
  title?: string
  message?: string
  isLoading?: boolean
}

const DeleteConfirmationModal = ({
  isOpen,
  onClose,
  onConfirm,
  title = 'Delete Confirmation',
  message = 'Are you sure you want to delete this item? This action cannot be undone.',
  isLoading = false,
}: DeleteConfirmationModalProps) => {
  const [isAnimating, setIsAnimating] = useState(false)
  const [shouldRender, setShouldRender] = useState(false)

  useEffect(() => {
    if (isOpen) {
      setTimeout(() => {
        setShouldRender(true)
      }, 0)
      // Small delay to trigger animation
      const timer = setTimeout(() => setIsAnimating(true), 10)
      return () => clearTimeout(timer)
    } else {
      setTimeout(() => {
        setIsAnimating(false)
      }, 0)
      // Wait for animation to finish before unmounting
      const timer = setTimeout(() => setShouldRender(false), 300)
      return () => clearTimeout(timer)
    }
  }, [isOpen])

  useEffect(() => {
    const handleEsc = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    if (isOpen) {
      window.addEventListener('keydown', handleEsc)
      document.body.style.overflow = 'hidden'
    }
    return () => {
      window.removeEventListener('keydown', handleEsc)
      document.body.style.overflow = 'unset'
    }
  }, [isOpen, onClose])

  if (!shouldRender) return null

  return createPortal(
    <div className="fixed inset-0 z-[5000] flex items-center justify-center p-4 sm:p-6">
      {/* Backdrop */}
      <div
        role="button"
        tabIndex={0}
        className={`absolute inset-0 bg-black/60 backdrop-blur-[2px] transition-opacity duration-300 ease-out ${isAnimating ? 'opacity-100' : 'opacity-0'
          }`}
        onClick={onClose}
        onKeyDown={(e) => e.key === 'Enter' && onClose()}
        aria-label="Close modal"
      />

      {/* Modal Container */}
      <div
        className={`bg-secondary-bg/20 light:bg-white/60! light:border-stroke-widget! text-primary-text relative w-full max-w-md transform overflow-hidden rounded-xl border p-1 shadow-2xl backdrop-blur-[50px]! light:backdrop-blur-none! border-black/50  transition-all duration-300 ease-out ${isAnimating
            ? 'translate-y-0 scale-100 opacity-100'
            : 'translate-y-10 scale-95 opacity-0'
          }`}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex flex-col items-center text-center">
          {/* Warning Icon with pulse effect */}
          <Box className="border-stroke-widget! shadow-[0px_2px_6px_0px_#00000033] bg-widget-inner-glass-bg! flex h-55.75 w-full flex-col items-center justify-center gap-6 rounded-xl border">
            <Box className="bg-secondary-widget! rounded-full px-[24.98px] py-[26.11px]">
              <img src="/delete_icon.svg" alt="delete" />
            </Box>
            <Box>
              <Text fz={16} fw={600} className="text-primary-text">
                {title}
              </Text>
              <Text fz={14} className="text-secondary-text w-[320px]">
                {message}
              </Text>
            </Box>
          </Box>

          <div className="flex w-full justify-between p-3.5">
            <SecondaryBtn
              type="button"
              onClick={onClose}
              disabled={isLoading}
              className="text-secondary-text hover:text-secondary-text cursor-pointer text-[12px] rounded-full! duration-200 hover:underline"
            >
              Cancel
            </SecondaryBtn>
            <PrimaryBtn
              type="button"
              onClick={onConfirm}
              disabled={isLoading}
              className="cursor-pointer! bg-[#DA1338]! text-white hover:bg-[#C11030]!"
              radius="xl"
              size="sm"
              style={{
                borderTop: '1px solid rgba(255, 255, 255, 0.16)',
                boxShadow:
                  '0px 2px 6px 0px #00000033, 0px 8px 32px 0px #00000059, 0px 1.5px 0px 0px rgba(255, 255, 255, 0.25) inset',
              }}
            >
              {isLoading ? (
                <>
                  <svg
                    className="h-4 w-4 animate-spin text-white"
                    viewBox="0 0 24 24"
                    aria-hidden="true"
                  >
                    <circle
                      className="opacity-25"
                      cx="12"
                      cy="12"
                      r="10"
                      stroke="currentColor"
                      strokeWidth="4"
                      fill="none"
                    />
                    <path
                      className="opacity-75"
                      fill="currentColor"
                      d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
                    />
                  </svg>
                  <span className="ml-1">Deleting...</span>
                </>
              ) : (
                'Delete'
              )}
            </PrimaryBtn>
          </div>
        </div>
      </div>
    </div>,
    document.body
  );
};

export default DeleteConfirmationModal;
