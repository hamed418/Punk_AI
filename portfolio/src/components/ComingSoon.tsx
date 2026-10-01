"use client";

import { Suspense } from "react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";
import { Text } from "@mantine/core";
import Spotlight from "../app/(main)/_components/Spotlight";
import AudioPlayer from "../app/(main)/_components/AudioPlayer";
import Navbar from "@/layout/navbar";
import Footer from "@/layout/footer";

interface ComingSoonProps {
  title?: string;
}

function ComingSoonContent({ title }: ComingSoonProps) {
  const searchParams = useSearchParams();
  const pageParam = searchParams.get("page");

  const displayTitle =
    title ||
    (pageParam ? `${pageParam.charAt(0).toUpperCase() + pageParam.slice(1)}` : null);

  return (
    <main className="flex flex-col items-center justify-center text-center gap-6 max-w-lg mx-auto">
      <img
        src="/monkeys.png"
        alt="Empty"
        className="h-[clamp(100px,16vh,180px)] w-auto select-none opacity-90 mb-2"
      />

      <div className="flex flex-col items-center gap-3">
        {displayTitle && (
          <Text className="text-[11px]! uppercase! tracking-[3px]! text-(--muted)! font-medium!">
            {displayTitle}
          </Text>
        )}

        <h1 className="text-[clamp(2rem,4vw,3.2rem)] font-light tracking-tight font-serif italic text-(--fg)">
          Coming Soon
        </h1>

        <Text className="text-[13px]! text-(--muted)! tracking-[0.5px]! max-w-xs! font-normal! leading-relaxed!">
          We are working on something new. Check back shortly for updates.
        </Text>
      </div>

      <Link
        href="/"
        className="mt-4 text-[11px] uppercase tracking-[2.5px] font-medium text-(--fg) hover:opacity-50 transition-opacity duration-200 inline-flex items-center gap-2"
      >
        ← Back to Home
      </Link>
    </main>
  );
}

export default function ComingSoonPage({ title }: ComingSoonProps) {
  return (
    <>
      <Spotlight />
      <AudioPlayer />
      <div className="relative z-10 h-full grid grid-rows-[auto_1fr] px-6 sm:px-12 py-10 gap-0">
        <Navbar />
        <Suspense
          fallback={
            <main className="flex flex-col items-center justify-center text-center">
              <h1 className="text-3xl font-serif italic">Coming Soon</h1>
            </main>
          }
        >
          <ComingSoonContent title={title} />
        </Suspense>
      </div>
      <Footer />
    </>
  );
}

