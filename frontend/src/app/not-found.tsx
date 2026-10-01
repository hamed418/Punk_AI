'use client';


import Link from 'next/link';
import { motion } from 'framer-motion';
import { ArrowLeft } from 'lucide-react';
import { handleLogoClick } from '@/utils/handleLogoClick';
import AnimatedPunkSvgIcon from '@/components/AnimatedPunkLogo';
import PrimaryGlassBtn from '@/components/PrimaryGlassBtn';

export default function NotFound() {
  return (
    <div className="relative h-full min-h-screen w-full overflow-y-auto custom-scrollbar bg-sidebar-bg text-primary-text font-inter flex flex-col justify-between p-4 sm:p-8">
      {/* Background Pattern */}
      <div className="pointer-events-none fixed inset-0 bg-[url('/images/dottedNew.jpg')] light:opacity-0 bg-cover bg-center bg-no-repeat" />

      {/* Main 404 Content */}
      <main className="relative z-10 flex-1 flex flex-col items-center justify-center text-center max-w-3xl mx-auto py-12 px-2">
        {/* Clickable Brand Logo Icon */}
        <motion.div
          initial={{ scale: 0.8, opacity: 0 }}
          animate={{ scale: 1, opacity: 1 }}
          transition={{ duration: 0.5, ease: [0.16, 1, 0.3, 1] }}
          onClick={handleLogoClick}
          className="relative mb-4 group cursor-pointer active:scale-95 transition-transform"
        >
          <div className="relative flex items-center justify-center p-4">
            <AnimatedPunkSvgIcon className="w-28 h-28 sm:w-36 sm:h-36 -ml-8" continuous />
          </div>
        </motion.div>

        {/* 404 Status Pill */}
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4, delay: 0.15 }}
          className="mb-3 px-3 py-1 rounded-full text-xs font-mono font-semibold tracking-widest text-primary-text/60 bg-white/4 border border-white/8"
        >
          404 • NOT FOUND
        </motion.div>

        {/* 404 Hero Numbers & Title */}
        <motion.h1
          initial={{ y: 20, opacity: 0 }}
          animate={{ y: 0, opacity: 1 }}
          transition={{ duration: 0.5, delay: 0.2 }}
          className="text-4xl sm:text-6xl font-extrabold tracking-tight text-primary-text leading-tight mb-4 font-display"
        >
          Page Lost in Hyperspace
        </motion.h1>

        {/* Explanation */}
        <motion.p
          initial={{ y: 20, opacity: 0 }}
          animate={{ y: 0, opacity: 1 }}
          transition={{ duration: 0.5, delay: 0.3 }}
          className="text-sm sm:text-base text-primary-text/70 max-w-lg leading-relaxed mb-8 font-sans"
        >
          The page you are looking for doesn&apos;t exist or has been moved to another vector. Let&apos;s get you back on track.
        </motion.p>

        {/* Call-to-Action Buttons */}
        <motion.div
          initial={{ y: 20, opacity: 0 }}
          animate={{ y: 0, opacity: 1 }}
          transition={{ duration: 0.5, delay: 0.4 }}
          className="flex flex-col sm:flex-row items-center gap-3 w-full max-w-xs justify-center"
        >
          <Link href="/" className="w-full sm:w-auto">
            <PrimaryGlassBtn
              className="w-full sm:w-auto px-6 py-2.5 text-xs font-semibold tracking-wide"
              leftSection={<ArrowLeft size={15} />}
            >
              Back to Chat
            </PrimaryGlassBtn>
          </Link>
        </motion.div>
      </main>
    </div>
  );
}
