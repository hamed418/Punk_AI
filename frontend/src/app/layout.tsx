import type { Metadata } from 'next';
import { Inter, Outfit, JetBrains_Mono, Geist } from 'next/font/google';
import localFont from 'next/font/local';
import { ColorSchemeScript, mantineHtmlProps } from '@mantine/core';
import { Suspense } from 'react';
import Providers from '@/providers';
import PostHogPageView from '@/providers/PostHogPageView';
import './globals.css';

const inter = Inter({
  variable: '--font-inter',
  subsets: ['latin'],
});

const outfit = Outfit({
  variable: '--font-display',
  subsets: ['latin'],
});

const jetbrainsMono = JetBrains_Mono({
  variable: '--font-mono',
  subsets: ['latin'],
});

const geist = Geist({
  variable: '--font-sans',
  subsets: ['latin'],
});

const ocrx = localFont({
  src: './fonts/016d77631553ff359b97c15a2ddb99e0.woff',
  variable: '--font-ocrx',
  weight: '400 700',
  display: 'swap',
});

export const metadata: Metadata = {
  title: 'Punk AI',
  description: 'Punk AI Application',
  icons: {
    icon: "/logo.svg"
  }
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${inter.variable} ${outfit.variable} ${jetbrainsMono.variable} ${geist.variable} ${ocrx.variable} antialiased`}
      {...mantineHtmlProps}
    >
      <head>
        <ColorSchemeScript defaultColorScheme="dark" />
      </head>
      <body className="min-h-full font-sans" cz-shortcut-listen="true">
        <Providers>
          <Suspense fallback={null}>
            {/* check posthog view  sdf  sdf welcome to home */}
            <PostHogPageView />
          </Suspense>
          {children}
        </Providers>
      </body>
    </html>
  );
}
