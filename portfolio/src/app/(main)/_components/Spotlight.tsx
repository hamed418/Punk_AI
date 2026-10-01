"use client";

import { useEffect, useRef } from "react";

export default function Spotlight() {
  const spotRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handlePointerMove = (e: PointerEvent) => {
      if (spotRef.current) {
        spotRef.current.style.setProperty("--mx", `${e.clientX}px`);
        spotRef.current.style.setProperty("--my", `${e.clientY}px`);
      }
    };

    window.addEventListener("pointermove", handlePointerMove);
    return () => {
      window.removeEventListener("pointermove", handlePointerMove);
    };
  }, []);

  return (
    <div
      ref={spotRef}
      className="fixed inset-0 pointer-events-none z-0 mix-blend-multiply bg-[radial-gradient(400px_400px_at_var(--mx,50%)_var(--my,50%),rgba(255,77,151,0.018),transparent_85%)]"
    />
  );
}



