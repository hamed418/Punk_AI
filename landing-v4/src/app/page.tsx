"use client";

import React, { useEffect } from "react";
import { Navbar } from "@/layouts/Navbar";

import { VSLSection } from "@/app/sections/VSLSection";
import { HowItWorksSection } from "@/app/sections/HowItWorksSection";
import { TechnologySection } from "@/app/sections/TechnologySection";
import { BeforeAndAfterSection } from "@/app/sections/BeforeAndAfterSection";
import { PricingSection } from "@/app/sections/PricingSection";
import { FAQSection } from "@/app/sections/FAQSection";
import DynastySection from "@/app/sections/DynastySection";
import EarlyAccessSection from "@/app/sections/EarlyAccessSection";
import { HeroSection } from "@/app/sections/HeroSection";
import { PromptSection } from "@/app/sections/PromptSection";
import Space from "@/components/Space";

export default function Home() {
  // Global client interactions: Reveal, Button Pixfill, Heading Autofit, Button Label Roll
  useEffect(() => {
    // 1. Button label roll
    document.querySelectorAll(".btn").forEach((b) => {
      if (b.querySelector(".btn__t")) return;
      const label = b.textContent ? b.textContent.trim() : "";
      b.innerHTML = `<span class="btn__t"><span>${label}</span><span aria-hidden="true">${label}</span></span>`;
    });

    // 2. Reveal observer
    const io = new IntersectionObserver(
      (entries) => {
        entries.forEach((en) => {
          if (en.isIntersecting) {
            en.target.classList.add("is-in");
            io.unobserve(en.target);
          }
        });
      },
      { threshold: 0.12 }
    );
    document.querySelectorAll(".reveal").forEach((el) => io.observe(el));

    // 3. Button pixel fill effect
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const TILE = 7,
      IN_MS = 420,
      OUT_MS = 300;
    const cleanups: Array<() => void> = [];

    document.querySelectorAll("#nav canvas.pixfill, .nav__cta canvas.pixfill, .hero__cta canvas.pixfill, #pricing canvas.pixfill, .plans canvas.pixfill").forEach((c) => c.remove());
    document.querySelectorAll(".hero__cta .has-pixfill, #pricing .has-pixfill, .plans .has-pixfill").forEach((el) => el.classList.remove("has-pixfill"));

    document.querySelectorAll(".pk-btn:not(.pk-btn-nav):not(.pk-btn-hero):not(.nav__cta *):not(#nav *):not(.hero__cta *):not(.hero__cta):not(#pricing *):not(.plans *), .pk-cap__btn").forEach((btnEl) => {
      const btn = btnEl as HTMLElement;
      if (btn.closest(".nav__cta") || btn.closest("#nav") || btn.closest(".hero__cta") || btn.closest("#pricing") || btn.closest(".plans") || btn.classList.contains("pk-btn-nav") || btn.classList.contains("pk-btn-hero")) return;
      if (btn.querySelector("canvas.pixfill")) return;

      const canvas = document.createElement("canvas");
      canvas.className = "pixfill";
      canvas.setAttribute("aria-hidden", "true");
      btn.prepend(canvas);
      btn.classList.add("has-pixfill");

      const ctx = canvas.getContext("2d");
      if (!ctx) return;
      const cap = btn.closest(".pk-cap");
      let W = 0,
        H = 0,
        cols = 0,
        rows = 0,
        order: Array<{ x: number; y: number; s: number }> = [],
        p = 0,
        target = 0,
        raf = 0,
        last = 0;

      function size() {
        const inset = btn.classList.contains("pk-btn")
          ? parseFloat(getComputedStyle(btn).getPropertyValue("--pk-gap")) || 0
          : 0;
        Object.assign(canvas.style, {
          left: inset + "px",
          top: inset + "px",
          right: inset + "px",
          bottom: inset + "px",
          width: `calc(100% - ${inset * 2}px)`,
          height: `calc(100% - ${inset * 2}px)`
        });
        const r = canvas.getBoundingClientRect();
        const dpr = Math.min(window.devicePixelRatio || 1, 2);
        canvas.width = Math.max(1, Math.round(r.width * dpr));
        canvas.height = Math.max(1, Math.round(r.height * dpr));
        W = canvas.width;
        H = canvas.height;
        cols = Math.max(1, Math.round(r.width / TILE));
        rows = Math.max(1, Math.round(r.height / TILE));
        order = [];
        for (let y = 0; y < rows; y++) {
          for (let x = 0; x < cols; x++) {
            order.push({ x, y, s: ((x + 0.5) / cols) * 0.82 + Math.random() * 0.18 });
          }
        }
        draw();
      }

      function draw() {
        if (!ctx) return;
        ctx.clearRect(0, 0, W, H);
        if (p <= 0) return;
        ctx.fillStyle = getComputedStyle(btn).getPropertyValue("--pk").trim() || "#F02D8A";
        if (p >= 1) {
          ctx.fillRect(0, 0, W, H);
          return;
        }
        for (const o of order) {
          const k = Math.min(1, Math.max(0, (p - o.s) / 0.16));
          if (k <= 0) continue;
          const q = Math.ceil(k * 3) / 3;
          const x0 = Math.round((o.x * W) / cols),
            x1 = Math.round(((o.x + 1) * W) / cols),
            y0 = Math.round((o.y * H) / rows),
            y1 = Math.round(((o.y + 1) * H) / rows);
          if (q >= 1) {
            ctx.fillRect(x0, y0, x1 - x0, y1 - y0);
            continue;
          }
          const bw = Math.round((x1 - x0) * q),
            bh = Math.round((y1 - y0) * q);
          ctx.fillRect(x0 + Math.round((x1 - x0 - bw) / 2), y0 + Math.round((y1 - y0 - bh) / 2), bw, bh);
        }
      }

      function step(now: number) {
        const dt = now - (last || now);
        last = now;
        const dir = Math.sign(target - p);
        p = reduced ? target : Math.min(1, Math.max(0, p + (dir * dt) / (dir > 0 ? IN_MS : OUT_MS) * 1.16));
        draw();
        if (p !== target) {
          raf = requestAnimationFrame(step);
        } else {
          raf = 0;
          last = 0;
        }
      }

      const set = (on: boolean) => {
        const want =
          on || (cap && (cap.classList.contains("is-sending") || cap.classList.contains("is-done"))) ? 1 : 0;
        if (want === target) return;
        target = want;
        if (!raf) raf = requestAnimationFrame(step);
      };

      const onEnter = () => set(true);
      const onLeave = () => set(false);
      const onFocus = () => set(true);
      const onBlur = () => set(false);

      btn.addEventListener("pointerenter", onEnter);
      btn.addEventListener("pointerleave", onLeave);
      btn.addEventListener("focus", onFocus);
      btn.addEventListener("blur", onBlur);

      let mutObs: MutationObserver | null = null;
      if (cap) {
        mutObs = new MutationObserver(() => set(btn.matches(":hover")));
        mutObs.observe(cap, { attributes: true, attributeFilter: ["class"] });
      }

      const resObs = new ResizeObserver(size);
      resObs.observe(btn);
      size();

      cleanups.push(() => {
        btn.removeEventListener("pointerenter", onEnter);
        btn.removeEventListener("pointerleave", onLeave);
        btn.removeEventListener("focus", onFocus);
        btn.removeEventListener("blur", onBlur);
        if (mutObs) mutObs.disconnect();
        resObs.disconnect();
        if (raf) cancelAnimationFrame(raf);
      });
    });

    // 4. Section titles autofit
    const heads = Array.from(document.querySelectorAll(".section__head h2.h-fit")) as HTMLElement[];
    const FLOOR = 22;
    function fit() {
      heads.forEach((h) => {
        h.style.fontSize = "";
      });
      if (window.innerWidth < 800) return;
      if (!heads.length) return;
      let size = parseFloat(getComputedStyle(heads[0]).fontSize);
      heads.forEach((h) => {
        const parent = h.parentElement;
        if (!parent) return;
        const room = parent.clientWidth;
        let s = parseFloat(getComputedStyle(h).fontSize);
        let guard = 40;
        h.style.fontSize = s + "px";
        while (h.scrollWidth > room && s > FLOOR && guard--) {
          s = Math.max(FLOOR, s - 1);
          h.style.fontSize = s + "px";
        }
        size = Math.min(size, s);
      });
      heads.forEach((h) => {
        h.style.fontSize = size + "px";
      });
    }

    fit();
    window.addEventListener("resize", fit, { passive: true });
    if (document.fonts && document.fonts.ready) {
      document.fonts.ready.then(fit);
    }

    return () => {
      io.disconnect();
      cleanups.forEach((c) => c());
      window.removeEventListener("resize", fit);
    };
  }, []);

  return (
    <>
      {/* Cube glyph definition reused across the page */}
      <svg width="0" height="0" style={{ position: "absolute" }} aria-hidden="true">
        <defs>
          <symbol id="cube" viewBox="0 0 20 22">
            <path d="M10 1.2 18.6 6.2 10 11.2 1.4 6.2Z" fill="#FFA3CD" />
            <path d="M1.4 6.2 10 11.2v9.6L1.4 15.8Z" fill="#F02D8A" />
            <path d="M18.6 6.2 10 11.2v9.6l8.6-5Z" fill="#C21D6F" />
            <path
              d="M10 1.2 18.6 6.2v9.6L10 20.8 1.4 15.8V6.2Zm0 10L1.4 6.2M10 11.2l8.6-5M10 11.2v9.6"
              fill="none"
              stroke="#2B0A1A"
              strokeWidth=".9"
              strokeLinejoin="round"
            />
          </symbol>
        </defs>
      </svg>

      <Navbar />

      <main id="top">
        <HeroSection />
        <PromptSection />

        <Space height={{base: 70, md: 140}}/>
        <VSLSection />
        <Space height={{base: 70, md: 140}}/>
        <HowItWorksSection />
        <Space height={{base: 70, md: 140}}/>
        <TechnologySection />
        <Space height={{base: 70, md: 140}}/>
        <BeforeAndAfterSection />
        <Space height={{base: 70, md: 140}}/>
        <PricingSection />
        <Space height={{base: 70, md: 140}}/>
        <FAQSection />
      </main>

      <Space height={{base: 70, md: 140}}/>
      <DynastySection />
      <EarlyAccessSection />
    </>
  );
}
