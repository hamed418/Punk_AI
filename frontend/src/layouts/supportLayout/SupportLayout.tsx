'use client';

import { AppShell } from '@mantine/core';
import React from 'react';
import SupportNavbar from './navbar';
import SupportFooter from './footer';

interface SupportLayoutProps {
    children: React.ReactNode;
}

export default function SupportLayout({ children }: SupportLayoutProps) {
    return (
        <AppShell
            header={{ height: 64 }}
            padding={0}
            withBorder={false}
            className="bg-primary-bg! min-h-screen"
        >
            <AppShell.Header p={0} className="border-none! bg-[#0A0A0BB8]!">
                <SupportNavbar />
            </AppShell.Header>

            {/* Background Pattern */}
            <div className="pointer-events-none fixed inset-0 bg-[url('/images/dottedNew.jpg')] light:opacity-0 bg-cover bg-center bg-no-repeat z-0" />

            <AppShell.Main className="relative z-10 flex min-h-screen w-full flex-col pt-16">
                <main className="relative flex-1">{children}</main>
                <SupportFooter />
            </AppShell.Main>
        </AppShell>
    );
}
