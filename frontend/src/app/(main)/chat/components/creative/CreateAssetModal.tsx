"use client";
import { Sparkles, X, PlayCircle } from "lucide-react";
import { useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import PrimaryGlassBtn from "@/components/PrimaryGlassBtn";
import SecondaryBtn from "@/components/secondaryBtn";
import { useMantineColorScheme } from "@mantine/core";

interface CreateAssetModalProps {
  open: boolean;
  onClose: () => void;
  onCreateAd: (type: "image" | "video") => void;
}

export default function CreateAssetModal({ open, onClose, onCreateAd }: CreateAssetModalProps) {
  const [selected, setSelected] = useState<"image" | "video" | null>(null);
  const { colorScheme } = useMantineColorScheme();

  return (
    <AnimatePresence>
      {open && (
        <div className="absolute inset-0 z-50 flex items-center justify-center p-4">
          {/* Backdrop */}
          <motion.div
            key="backdrop"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="absolute inset-0 bg-black/80"
            onClick={onClose}
          />

          {/* Modal */}
          <motion.div
            key="modal"
            initial={{ opacity: 0, scale: 0.95, y: 16 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.95, y: 16 }}
            transition={{ duration: 0.22, ease: "easeOut" }}
            className="relative flex w-full max-w-[480px] scale-90 flex-col overflow-hidden rounded-[28px] border text-primary-text"
            style={{
              background: colorScheme === 'light' ? 'var(--mantine-color-body)' : '#1C1C1C',
              borderColor: colorScheme === 'light'
                ? 'var(--mantine-color-gray-3)'
                : 'rgba(255, 255, 255, 0.15)',
              boxShadow: colorScheme === 'light'
                ? '0 8px 40px rgba(0,0,0,0.12)'
                : '0px 8px 32px 0px #00000099, 0px -1px 0px 0px #00000066 inset, 0px 1px 0px 0px #FFFFFF1F inset',
            }}>
              {/* Header */}
              <div className="flex items-center justify-between border-b border-underline/15 px-6 py-5">
                <div className="flex items-center gap-2 text-primary-text">
                  <Sparkles size={15} className="text-secondary-text" />
                  <span className="text-[15px] font-medium tracking-wide">
                    Punk ideas · Create asset
                  </span>
                </div>
                <button
                  onClick={onClose}
                  className="cursor-pointer rounded-full p-1 text-secondary-text transition-colors hover:bg-white/10 hover:text-primary-text"
                >
                  <X size={18} strokeWidth={1.5} />
                </button>
              </div>

              {/* Body */}
              <div className="flex flex-col gap-5 p-6">
                <p className="text-[13px] leading-relaxed text-secondary-text/90">
                  We&apos;ll use everything we&apos;ve learned about your campaign to create a
                  high-performing ad. Choose how you&apos;d like to bring it to life.
                </p>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                  {/* Ad Image Card */}
                  <div
                    role="button"
                    tabIndex={0}
                    onClick={() => setSelected("image")}
                    onKeyDown={(e) =>
                      (e.key === "Enter" || e.key === " ") && setSelected("image")
                    }
                    className={`cursor-pointer border rounded-2xl p-2 md:p-3.5 transition-all ${
                      selected === "image"
                        ? "border-primary-text bg-white/5 light:bg-black/[0.04]"
                        : "border-underline/15 bg-transparent hover:bg-white/5 light:hover:bg-black/[0.04]"
                    }`}
                  >
                    <div className="flex flex-row-reverse items-center gap-3 md:flex-col">
                      {/* Image wireframe preview */}
                      <div className="mb-0 md:mb-4 flex h-[80px] md:h-[120px] w-[100px] md:w-full shrink-0 flex-col overflow-hidden rounded-xl bg-white/5 light:bg-black/[0.03] p-3">
                        <div className="mb-2.5 flex items-center gap-1.5">
                          <div className="h-4 w-4 rounded-full bg-white/10 light:bg-black/[0.06]" />
                          <div className="h-1.5 w-10 rounded-full bg-white/10 light:bg-black/[0.06]" />
                        </div>
                        <div className="relative flex-1 overflow-hidden rounded-lg bg-white/[0.04] light:bg-black/[0.02]">
                          <svg
                            className="absolute inset-0 h-full w-full"
                            preserveAspectRatio="none"
                            viewBox="0 0 100 60"
                          >
                            <circle
                              cx="18"
                              cy="30"
                              r="7"
                              fill={colorScheme === "light" ? "rgba(0,0,0,0.04)" : "rgba(255,255,255,0.06)"}
                            />
                            <polyline
                              points="0,60 28,35 48,48 68,28 100,60"
                              fill="none"
                              stroke={colorScheme === "light" ? "rgba(0,0,0,0.08)" : "rgba(255,255,255,0.12)"}
                              strokeWidth="1.5"
                            />
                          </svg>
                        </div>
                      </div>

                      <div className="flex flex-1 items-start gap-2.5">
                        <div
                          className={`mt-0.5 flex h-[17px] w-[17px] shrink-0 items-center justify-center rounded-full border transition-colors ${
                            selected === "image"
                              ? "border-primary-text"
                              : "border-secondary-text/40"
                          }`}
                        >
                          {selected === "image" && (
                            <div className="h-[7px] w-[7px] rounded-full bg-primary-text" />
                          )}
                        </div>
                        <div>
                          <p className="mb-0.5 text-[14px] font-medium text-primary-text">
                            Ad Image
                          </p>
                          <p className="text-[12px] leading-snug text-secondary-text/70">
                            Generate a static visual optimized image
                          </p>
                        </div>
                      </div>
                    </div>
                  </div>

                  {/* Ad Video Card */}
                  <div
                    className="relative overflow-hidden rounded-2xl border border-underline/15 bg-transparent p-2 md:p-3.5 cursor-not-allowed"
                  >
                    <div className="flex flex-row-reverse items-center gap-3 md:flex-col">
                      {/* Video wireframe preview */}
                      <div className="mb-0 md:mb-4 flex h-[80px] md:h-[120px] w-[100px] md:w-full shrink-0 flex-col overflow-hidden rounded-xl bg-white/5 light:bg-black/[0.03] p-3">
                        <div className="relative flex-1 overflow-hidden rounded-lg bg-white/[0.04] light:bg-black/[0.02]">
                          <div className="absolute inset-0 flex items-center justify-center">
                            <PlayCircle
                              size={32}
                              className="text-white/15 light:text-black/15"
                              fill={colorScheme === "light" ? "rgba(0,0,0,0.04)" : "rgba(255,255,255,0.06)"}
                              strokeWidth={1}
                            />
                          </div>
                        </div>
                        {/* Scrubber bar */}
                        <div className="mt-2.5 flex items-center gap-1.5 px-0.5">
                          <div className="relative h-1 flex-1 overflow-visible rounded-full bg-white/10 light:bg-black/[0.06]">
                            <div className="absolute left-0 top-0 h-full w-[38%] rounded-full bg-white/25 light:bg-black/[0.15]" />
                            <div className="absolute top-1/2 left-[38%] h-2.5 w-2.5 -translate-y-1/2 rounded-full bg-white/35 light:bg-black/[0.25]" />
                          </div>
                        </div>
                      </div>

                      <div className="flex flex-1 items-start gap-2.5">
                        <div
                          className="mt-0.5 flex h-[17px] w-[17px] shrink-0 items-center justify-center rounded-full border border-secondary-text/40 transition-colors"
                        >
                        </div>
                        <div>
                          <p className="mb-0.5 text-[14px] font-medium text-primary-text">
                            Ad Video
                          </p>
                          <p className="text-[12px] leading-snug text-secondary-text/70">
                            Perfect for feeds, stories, display ads, and landing pages.
                          </p>
                        </div>
                      </div>
                    </div>

                    {/* Coming Soon Overlay */}
                    <div className="absolute inset-0 rounded-2xl flex items-center justify-center bg-black/70 light:bg-white/75 backdrop-blur-xl transition-all">
                      <span className="rounded-full light:bg-white! bg-black border border-white/10 light:border-black/10 px-3 py-1 text-[11px] font-semibold tracking-wider text-primary-text uppercase shadow-sm">
                        coming soon
                      </span>
                    </div>
                  </div>
                </div>
              </div>

              {/* Footer */}
              <div className="flex items-center justify-between border-t border-underline/15 px-6 py-4">
                <SecondaryBtn radius="xl" size="sm" onClick={onClose}>
                  Cancel
                </SecondaryBtn>
                <PrimaryGlassBtn
                  radius="xl"
                  size="sm"
                  disabled={!selected}
                  onClick={() => {
                    if (selected) {
                      onCreateAd(selected);
                      onClose();
                    }
                  }}
                >
                  Create ad
                </PrimaryGlassBtn>
              </div>
            </motion.div>
        </div>
      )}
    </AnimatePresence>
  );
}
