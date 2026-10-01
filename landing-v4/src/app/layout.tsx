import type { Metadata } from 'next';
import { Inter, Bricolage_Grotesque, JetBrains_Mono } from 'next/font/google';
import './globals.css';
import './reference_styles.css';

const inter = Inter({
  subsets: ['latin'],
  variable: '--font-body',
  display: 'swap',
});

const bricolage = Bricolage_Grotesque({
  subsets: ['latin'],
  variable: '--font-display',
  display: 'swap',
});

const mono = JetBrains_Mono({
  subsets: ['latin'],
  weight: ['500'],
  variable: '--mono',
  display: 'swap',
});

export const metadata: Metadata = {
  title: 'punk — Tell punk who you want to reach',
  description:
    'Describe your customer in plain English. punk finds the devices behind that real-world behaviour, builds the audience and launches your Meta campaign in minutes.',
  icons: {
    icon: '/logo.svg',
  },
};

import PostHogProvider from '@/providers/PostHogProvider';
import PostHogPageView from '@/providers/PostHogPageView';

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html
      lang="en"
      className={`${inter.variable} ${bricolage.variable} ${mono.variable} w-full max-w-full overflow-x-hidden scroll-smooth bg-white`}
    >
      <body
        cz-shortcut-listen="true"
        className="font-body text-ink [&_*:focus-visible]:outline-punk m-0 w-full max-w-full overflow-x-hidden bg-[#FAF9F5] text-[16px] leading-[1.55] antialiased [&_*:focus-visible]:outline-2 [&_*:focus-visible]:outline-offset-[3px]"
      >
        <PostHogProvider>
          <PostHogPageView />
          {children}
        </PostHogProvider>
      </body>
    </html>
  );
}
