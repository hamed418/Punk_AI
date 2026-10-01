'use client';

import Link from 'next/link';
import { motion } from 'framer-motion';
import { Plus, MessageSquareOff } from 'lucide-react';
import AnimatedPunkSvgIcon from '@/components/AnimatedPunkLogo';
import { handleLogoClick } from '@/utils/handleLogoClick';
import PrimaryGlassBtn from '@/components/PrimaryGlassBtn';

export default function ChatThreadNotFound() {
  return (
    <div className="relative flex h-screen w-full flex-col items-center justify-center overflow-hidden font-inter text-primary-text px-4">
      {/* Subtle Background Overlay */}
      <div className="pointer-events-none absolute inset-0 bg-[url('/images/dottedNew.jpg')] bg-cover bg-center bg-no-repeat opacity-40 light:opacity-0" />

      {/* Main Content */}
      <main className="relative z-10 flex max-w-lg flex-col items-center text-center">
        {/* Animated Brand / Chat Icon */}
        <motion.div
          initial={{ scale: 0.8, opacity: 0 }}
          animate={{ scale: 1, opacity: 1 }}
          transition={{ duration: 0.4, ease: [0.16, 1, 0.3, 1] }}
          onClick={handleLogoClick}
          className="relative mb-6 cursor-pointer active:scale-95 transition-transform"
        >
          <div className="relative flex items-center justify-center p-3">
            <AnimatedPunkSvgIcon className="w-24 h-24 sm:w-28 sm:h-28 -ml-4" continuous />
            <div className="absolute bottom-1 right-0 rounded-full bg-sidebar-bg/90 border border-white/10 p-1.5 backdrop-blur-md shadow-lg text-primary-text/60">
              <MessageSquareOff size={16} />
            </div>
          </div>
        </motion.div>

        {/* Title */}
        <motion.h1
          initial={{ y: 15, opacity: 0 }}
          animate={{ y: 0, opacity: 1 }}
          transition={{ duration: 0.4, delay: 0.1 }}
          className="text-2xl sm:text-4xl font-extrabold tracking-tight text-primary-text leading-tight mb-3 font-display"
        >
          Conversation Not Found
        </motion.h1>

        {/* Description */}
        <motion.p
          initial={{ y: 15, opacity: 0 }}
          animate={{ y: 0, opacity: 1 }}
          transition={{ duration: 0.4, delay: 0.2 }}
          className="text-xs sm:text-sm text-primary-text/70 max-w-md leading-relaxed mb-6 font-sans"
        >
          This chat thread doesn&apos;t exist, has been deleted, or you don&apos;t have access to it. Let&apos;s get you into a fresh session.
        </motion.p>

        {/* Actions */}
        <motion.div
          initial={{ y: 15, opacity: 0 }}
          animate={{ y: 0, opacity: 1 }}
          transition={{ duration: 0.4, delay: 0.3 }}
          className="flex flex-col sm:flex-row items-center gap-3 w-full max-w-xs justify-center"
        >
          <Link href="/chat" className="w-full sm:w-auto">
            <PrimaryGlassBtn
              className="w-full sm:w-auto px-6 py-2.5 text-xs font-semibold tracking-wide"
              leftSection={<Plus size={15} />}
            >
              Start New Chat
            </PrimaryGlassBtn>
          </Link>
        </motion.div>
      </main>
    </div>
  );
}
