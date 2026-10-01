import { Box, Flex } from '@mantine/core'
import { SquarePen } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import SecondaryBtn from '@/components/secondaryBtn'
import PrimaryGlassBtn from '@/components/PrimaryGlassBtn'

interface RenameModalProps {
  isOpen: boolean
  onClose: () => void
  onConfirm: (newTitle: string) => void
  currentTitle: string
  isLoading?: boolean
}

const RenameModal = ({
  isOpen,
  onClose,
  onConfirm,
  currentTitle,
  isLoading = false,
}: RenameModalProps) => {
  const [title, setTitle] = useState(currentTitle)
  const [isAnimating, setIsAnimating] = useState(false)
  const [shouldRender, setShouldRender] = useState(false)
  const [prevIsOpen, setPrevIsOpen] = useState(isOpen)
  const inputRef = useRef<HTMLInputElement>(null)

  // Sync title state when modal opens during render phase (React 18+ best practice)
  if (isOpen !== prevIsOpen) {
    setPrevIsOpen(isOpen)
    if (isOpen) {
      setTitle(currentTitle)
      setShouldRender(true)
    } else {
      setIsAnimating(false)
    }
  }

  // Handle animations
  useEffect(() => {
    if (isOpen) {
      const timer = setTimeout(() => setIsAnimating(true), 10)
      return () => clearTimeout(timer)
    } else {
      const timer = setTimeout(() => setShouldRender(false), 300)
      return () => clearTimeout(timer)
    }
  }, [isOpen])

  // Handle focus and select all
  useEffect(() => {
    if (shouldRender && isOpen) {
      const timer = setTimeout(() => {
        if (inputRef.current) {
          inputRef.current.focus()
          inputRef.current.select()
        }
      }, 50)
      return () => clearTimeout(timer)
    }
  }, [shouldRender, isOpen])

  // Handle ESC and Enter key events
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onClose()
      }
    }
    if (isOpen) {
      window.addEventListener('keydown', handleKeyDown)
      document.body.style.overflow = 'hidden'
    }
    return () => {
      window.removeEventListener('keydown', handleKeyDown)
      document.body.style.overflow = 'unset'
    }
  }, [isOpen, onClose])

  const handleSubmit = (e?: React.FormEvent) => {
    e?.preventDefault()
    if (!title.trim() || isLoading) return
    onConfirm(title.trim())
  }

  if (!shouldRender) return null

  if (!shouldRender) return null

  const isSaveDisabled =
    !title.trim() || title.trim() === currentTitle || isLoading

  return createPortal(
    <div className="fixed inset-0 z-[5000] flex items-center justify-center p-4 sm:p-6">
      {/* Backdrop with elegant glassmorphism and transition */}
      <Box
        className={`absolute inset-0 bg-black/60 backdrop-blur-[2px] transition-opacity duration-300 ease-out ${
          isAnimating ? 'opacity-100' : 'opacity-0'
        }`}
        onClick={onClose}
      />

      <form
        onSubmit={handleSubmit}
        className={`bg-secondary-bg/20 light:bg-white/60! light:border-stroke-widget! text-primary-text relative w-full max-w-xl transform overflow-hidden rounded-md! border border-black/50 shadow-2xl backdrop-blur-[50px]! light:backdrop-blur-none! transition-all duration-300 ease-out sm:max-w-lg max-h-[90vh] overflow-y-auto ${
          isAnimating
            ? 'translate-y-0 scale-100 opacity-100'
            : 'translate-y-10 scale-95 opacity-0 sm:translate-y-4'
        } ${
          'fixed top-auto right-0 bottom-0 left-0 rounded-t-3xl rounded-b-none sm:static sm:rounded-lg'
        }`}
        onClick={(e) => e.stopPropagation()}
        onKeyDown={(e) => e.stopPropagation()}
      >
        <Box className="bg-primary-widget border-stroke-widget flex flex-col items-center justify-center border p-1">
          {/* Header Icon & Title */}
          <Box className="border-divider! border-b! mb-3.5 flex w-full items-center gap-3 p-3.25">
            <Box className="border-underline bg-secondary-bg text-primary-text flex h-10 w-10 items-center justify-center rounded-full border-2 shadow-inner">
              <SquarePen size={18} />
            </Box>
            <Flex direction="column" gap={1}>
              <h3 className="text-primary-text text-[16px] font-bold">
                Rename Chat
              </h3>
              <p className="text-secondary-text text-[14px]">
                Provide a new title for this conversation thread.
              </p>
            </Flex>
          </Box>

          {/* Form Input Field */}
          <Box className="border-underline/50 mb-6 w-full border-b border-dashed px-3.5 pb-3.5">
            <label
              htmlFor="thread-title-input"
              className="text-secondary-text/80 mb-2.5 block pt-2 text-[12px] font-bold tracking-wider uppercase"
            >
              New Title
            </label>
            <input
              ref={inputRef}
              id="thread-title-input"
              type="text"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="Enter chat title..."
              disabled={isLoading}
              className="border-stroke-widget bg-widget-inner-glass-bg! font-body text-primary-text focus:border-secondary-bg focus:ring-secondary-bg w-full rounded-xl border px-3 py-[11.5px] text-sm font-medium transition-all focus:ring-1 focus:outline-hidden disabled:cursor-not-allowed disabled:opacity-50"
              maxLength={100}
            />
          </Box>

          {/* Action Buttons */}
          <div className="flex w-full items-center justify-between px-4 pb-4">
            <SecondaryBtn
            radius={"xl"}
              type="button"
              onClick={onClose}
              disabled={isLoading}
            >
              Cancel
            </SecondaryBtn>
            <PrimaryGlassBtn
              disabled={isSaveDisabled}
              onClick={handleSubmit}
              loading={isLoading}
            >
              Save
            </PrimaryGlassBtn>
          </div>
        </Box>
      </form>
    </div>,
    document.body,
  )
}

export default RenameModal
