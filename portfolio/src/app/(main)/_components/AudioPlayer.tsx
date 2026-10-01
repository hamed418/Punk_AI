"use client";

import { useEffect, useRef } from "react";

export default function AudioPlayer() {
  const audioRef = useRef<HTMLAudioElement>(null);

  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return;

    audio.volume = 0.55;
    audio.play().catch(() => {});

    const firstInteraction = () => {
      if (audio.muted) {
        audio.muted = false;
        audio.play().catch(() => {});
      }
      window.removeEventListener("pointerdown", firstInteraction);
      window.removeEventListener("keydown", firstInteraction);
      window.removeEventListener("scroll", firstInteraction);
    };

    window.addEventListener("pointerdown", firstInteraction);
    window.addEventListener("keydown", firstInteraction);
    window.addEventListener("scroll", firstInteraction);

    return () => {
      window.removeEventListener("pointerdown", firstInteraction);
      window.removeEventListener("keydown", firstInteraction);
      window.removeEventListener("scroll", firstInteraction);
    };
  }, []);

  return <audio ref={audioRef} id="bgm" src="/song.mp3" loop preload="auto" muted />;
}
