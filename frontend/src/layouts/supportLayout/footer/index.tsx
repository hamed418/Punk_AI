'use client';

import { Box } from '@mantine/core';
import Link from 'next/link';
import React from 'react';

export default function SupportFooter() {
    return (
        <footer className="w-full border-t border-[#FFFFFF12] bg-transparent">
            <Box className="mx-auto flex max-w-[1500px] flex-col items-center justify-between gap-4 p-4 md:flex-row md:p-8">
                {/* Left Section: Copyright */}
                <p className="text-primary-text/60 text-xs sm:text-sm font-normal">
                    © {new Date().getFullYear()} Punk AI
                </p>

                {/* Right Section: Links */}
                <Box className="flex flex-wrap items-center gap-6">
                    <Link
                        href="https://usepunk.ai/privacy"
                        className="text-primary-text/70 hover:text-primary-text text-xs sm:text-sm font-normal transition-colors"
                    >
                        Privacy
                    </Link>
                    <Link
                        href="https://usepunk.ai/terms"
                        className="text-primary-text/70 hover:text-primary-text text-xs sm:text-sm font-normal transition-colors"
                    >
                        Terms
                    </Link>
                    <a
                        href="mailto:support@punkai.com"
                        className="text-primary-text/70 hover:text-primary-text text-xs sm:text-sm font-normal transition-colors"
                    >
                        support@punkai.com
                    </a>
                </Box>
            </Box>
        </footer>
    );
}
