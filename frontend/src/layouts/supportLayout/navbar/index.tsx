'use client';

import { Box, Drawer } from '@mantine/core';
import { useDisclosure } from '@mantine/hooks';
import { ChevronLeft, ExternalLink, Mail, ShieldCheck, FileText } from 'lucide-react';
import Link from 'next/link';
import SidebarLogo from '@/layouts/mainLayout/sideBar/sidebarHeader/SidebarLogo';
import CollapseIcon from '@/layouts/mainLayout/sideBar/sidebarHeader/CollapseIcon';
import PrimaryGlassBtn from '@/components/PrimaryGlassBtn';


export default function SupportNavbar() {
    const [mobileOpened, { toggle: toggleMobile, close: closeMobile }] = useDisclosure();

    return (
        <>
            {/* Mobile Sidebar Drawer */}
            <Drawer
                opened={mobileOpened}
                onClose={closeMobile}
                size="auto"
                padding={0}
                withCloseButton={false}
                zIndex={3000}
                styles={{
                    content: { backgroundColor: 'transparent', boxShadow: 'none' },
                    body: { padding: 0 },
                }}
            >
                <Box className="relative h-dvh p-2 font-inter!">
                    <Box
                        className="sidebar-shadow relative z-10 flex h-[calc(100vh-16px)] w-[272px] flex-col overflow-hidden rounded-2xl px-4 py-4 backdrop-blur-3xl"
                        style={{
                            backdropFilter: 'blur(78px)',
                            background: 'var(--mantine-sidebar-mobile-bg)',
                        }}
                    >
                        {/* Header in Mobile Sidebar */}
                        <Box className="flex items-center justify-between border-b border-white/10 pb-4">
                            <Box className="flex items-center gap-2 gap-2 item-center justify-center">
                                <SidebarLogo className="h-8 w-auto" />
                                <span className="text-primary-text/70 text-md font-light">/</span>
                                <span className="text-primary-text/70 text-sm font-normal">Support</span>
                            </Box>

                            <button
                                type="button"
                                onClick={closeMobile}
                                aria-label="Close menu"
                                className="text-primary-text/70 hover:text-primary-text cursor-pointer p-1.5 transition-colors"
                            >
                                <ChevronLeft className="size-5" />
                            </button>
                        </Box>

                        {/* Navigation Links */}
                        <Box className="flex flex-1 flex-col space-y-2 pt-6">
                            <Link
                                href="https://usepunk.ai/privacy"
                                onClick={closeMobile}
                                className="hover:bg-white/5 text-primary-text/80 hover:text-primary-text flex items-center space-x-3 rounded-xl px-3 py-2.5 text-sm font-medium transition-colors"
                            >
                                <ShieldCheck className="size-4 text-primary-text/60" />
                                <span>Privacy</span>
                            </Link>
                            <Link
                                href="https://usepunk.ai/terms"
                                onClick={closeMobile}
                                className="hover:bg-white/5 text-primary-text/80 hover:text-primary-text flex items-center space-x-3 rounded-xl px-3 py-2.5 text-sm font-medium transition-colors"
                            >
                                <FileText className="size-4 text-primary-text/60" />
                                <span>Terms</span>
                            </Link>
                            <a
                                href="mailto:support@punkai.com"
                                onClick={closeMobile}
                                className="hover:bg-white/5 text-primary-text/80 hover:text-primary-text flex items-center space-x-3 rounded-xl px-3 py-2.5 text-sm font-medium transition-colors"
                            >
                                <Mail className="size-4 text-primary-text/60" />
                                <span>support@punkai.com</span>
                            </a>
                        </Box>

                        {/* Bottom Button */}
                        <Box className="mt-auto border-t border-white/10 pt-4">
                            <Link
                                href="/chat"
                                onClick={closeMobile}
                                className="flex w-full items-center justify-center space-x-2 rounded-xl border border-neutral-700 bg-neutral-900/80 py-2.5 text-sm font-medium text-primary-text transition-all hover:border-neutral-500 hover:bg-neutral-800"
                            >
                                <span>Open app</span>
                                <ExternalLink className="size-4" />
                            </Link>
                        </Box>
                    </Box>
                </Box>
            </Drawer>

            {/* Main Header */}
            <header className="relative w-full bg-[#0A0A0BB8] backdrop-blur-md">
                <Box className="mx-auto flex h-16 max-w-[1500px] items-center justify-between p-4 md:p-8">
                    {/* Left Section */}
                    <Box className="flex items-center space-x-3">
                        {/* Mobile Sidebar Toggle Button */}
                        <button
                            type="button"
                            onClick={toggleMobile}
                            aria-label="Open sidebar"
                            className="text-primary-text/70 hover:text-primary-text cursor-pointer p-1 transition-colors md:hidden"
                        >
                            <CollapseIcon className="h-4 w-4" />
                        </button>

                        <Box className="flex items-center gap-2 gap-2 item-center justify-center">
                            <SidebarLogo className="h-8 w-auto" />
                            <span className="text-primary-text/70 text-md font-light">/</span>
                            <span className="text-primary-text/70 text-sm font-normal">Support</span>
                        </Box>

                    </Box>

                    {/* Desktop Navigation Links */}
                    <Box className="hidden items-center space-x-6 md:flex">
                        <Link
                            href="/privacy"
                            className="text-primary-text/70 hover:text-primary-text text-xs sm:text-sm font-medium transition-colors"
                        >
                            privacy
                        </Link>
                        <Link
                            href="/terms"
                            className="text-primary-text/70 hover:text-primary-text text-xs sm:text-sm font-medium transition-colors"
                        >
                            Terms
                        </Link>
                        <a
                            href="mailto:support@punkai.com"
                            className="text-primary-text/70 hover:text-primary-text text-xs sm:text-sm font-medium transition-colors"
                        >
                            support@punkai.com
                        </a>
                        <Link
                            href="/chat"
                        >
                            <PrimaryGlassBtn>
                                Open app
                            </PrimaryGlassBtn>
                        </Link>
                    </Box>

                    {/* Mobile Right Action */}
                    <Box className="flex items-center md:hidden">
                        <Link
                            href="/chat"
                            className="rounded-full border border-neutral-700 bg-neutral-900/60 px-3 py-1 text-xs font-medium text-primary-text transition-all hover:border-neutral-500 hover:bg-neutral-800"
                        >
                            Open app
                        </Link>
                    </Box>
                </Box>
            </header>
        </>
    );
}
