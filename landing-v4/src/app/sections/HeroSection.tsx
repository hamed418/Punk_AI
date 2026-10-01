'use client';

import Image, { getImageProps } from 'next/image';
import React, { useEffect, useRef, useSyncExternalStore } from 'react';
import { trackEvent } from '@/lib/analytics';
import Space from '@/components/Space';

const subscribeMobile = (callback: () => void) => {
  const mql = window.matchMedia('(max-width: 767px)');
  mql.addEventListener('change', callback);
  return () => mql.removeEventListener('change', callback);
};

const getMobileSnapshot = () => window.matchMedia('(max-width: 767px)').matches;
const getServerSnapshot = () => false;

const heroImgCommon = { alt: '', width: 5376, height: 3008, priority: true };
const {
  props: { srcSet: mobileHeroSrcSet },
} = getImageProps({ ...heroImgCommon, src: '/heroBgMobile.png' });
const {
  props: { srcSet: desktopHeroSrcSet },
} = getImageProps({ ...heroImgCommon, src: '/heroBg.png' });

const HERO_CTA_BTN_CLASSES =
  'pk-btn pk-btn-hero pk-btn--secondary pk-btn--lg relative isolate inline-flex items-center justify-center text-center cursor-pointer select-none no-underline border-0 outline-none [-webkit-tap-highlight-color:transparent] font-body text-[15px] sm:text-[16px] font-medium leading-none tracking-[-0.005em] text-[#141414] focus-visible:outline-2 focus-visible:outline-(--punk) focus-visible:outline-offset-4';

const HIGHLIGHT_TAGS = [
  {
    name: 'Goes to Equinox',
    sub: 'Visits 3x/week',
    left: '6.25%',
    top: '47.50%',
    width: '5.80%',
    height: '24.07%',
    fd: '-1.2s',
  },
  {
    name: 'Matcha drinker',
    sub: 'Visits 4x/week',
    left: '21.65%',
    top: '53.80%',
    width: '3.87%',
    height: '13.43%',
    fd: '-5.4s',
  },
  {
    name: 'Dog park regular',
    sub: 'Visits 5x/week',
    left: '65.48%',
    top: '54.10%',
    width: '6.40%',
    height: '23.54%',
    fd: '-3.1s',
  },
  {
    name: 'Whole Foods shopper',
    sub: 'Visits 2x/week',
    left: '90.03%',
    top: '51.70%',
    width: '4.76%',
    height: '17.02%',
    fd: '-8.0s',
  },
];

export function HeroSection() {
  const heroRef = useRef<HTMLElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const imgRef = useRef<HTMLImageElement>(null);
  const isMobile = useSyncExternalStore(
    subscribeMobile,
    getMobileSnapshot,
    getServerSnapshot
  );

  // 1. Hero highlight layer tracking
  useEffect(() => {
    const bg = document.getElementById('heroBg');
    const layer = document.getElementById('heroHl');
    if (!bg || !layer) return;

    const RATIO = 1344 / 752;

    function fit() {
      const W = bg!.clientWidth;
      const H = bg!.clientHeight;
      let w = W;
      let h = W / RATIO;
      if (h < H) {
        h = H;
        w = H * RATIO;
      }
      layer!.style.width = w + 'px';
      layer!.style.height = h + 'px';
      layer!.style.left = (W - w) / 2 + 'px';
      layer!.style.top = '0px';
    }

    function nudge() {
      const tags = Array.from(layer!.querySelectorAll<HTMLElement>('.tag'));
      tags.forEach((t) => {
        t.style.removeProperty('transform');
        t.style.setProperty('--hl-tx', '-50%');
        const r = t.getBoundingClientRect();
        const vw = document.documentElement.clientWidth;
        const M = 10;
        const over =
          Math.max(0, r.right - (vw - M)) || -Math.max(0, M - r.left);
        if (over) {
          t.style.setProperty('--hl-tx', `calc(-50% - ${Math.round(over)}px)`);
        }
      });

      const copy = Array.from(document.querySelectorAll('.hero__copy > *'))
        .map((e) => e.getBoundingClientRect())
        .filter((r) => r.width && r.height);

      tags.forEach((t) => {
        for (const c of copy) {
          const r = t.getBoundingClientRect();
          if (!(
            r.top < c.bottom &&
            r.bottom > c.top &&
            r.left < c.right &&
            r.right > c.left
          ))
            continue;
          const tc = (r.left + r.right) / 2;
          const cc = (c.left + c.right) / 2;
          const dx = tc < cc ? -(r.right - c.left + 10) : c.right - r.left + 10;
          const cur = t.style.getPropertyValue('--hl-tx') || '-50%';
          t.style.setProperty('--hl-tx', `calc(${cur} + ${Math.round(dx)}px)`);
        }
      });

      const GAP = 10;
      const order = tags
        .slice()
        .sort(
          (a, b) =>
            a.getBoundingClientRect().left - b.getBoundingClientRect().left
        );
      for (let i = 1; i < order.length; i++) {
        const prev = order[i - 1].getBoundingClientRect();
        const r = order[i].getBoundingClientRect();
        if (
          r.top < prev.bottom &&
          r.bottom > prev.top &&
          r.left < prev.right + GAP
        ) {
          const need = Math.round(prev.right + GAP - r.left);
          const vw = document.documentElement.clientWidth;
          const bump = (el: HTMLElement, sign: string) => {
            const cur = el.style.getPropertyValue('--hl-tx') || '-50%';
            el.style.setProperty('--hl-tx', `calc(${cur} ${sign} ${need}px)`);
          };
          if (r.right + need <= vw - 10) bump(order[i], '+');
          else bump(order[i - 1], '-');
        }
      }
    }

    function relayout() {
      fit();
      nudge();
    }

    const ro = new ResizeObserver(relayout);
    ro.observe(bg);
    relayout();
    window.addEventListener('load', relayout);

    return () => {
      ro.disconnect();
      window.removeEventListener('load', relayout);
    };
  }, []);

  // Floating tags ripple wave and interaction effect (from reference.html)
  useEffect(() => {
    const layer = document.getElementById('heroHl');
    if (!layer) return;

    const tags = Array.from(layer.querySelectorAll<HTMLElement>('.tag'));
    if (!tags.length) return;

    const cleanups: (() => void)[] = [];

    tags.forEach((tag, k) => {
      const name = tag.querySelector<HTMLElement>('.tag__name');
      if (!name) return;

      const play = () => {
        tag.classList.remove('play');
        void tag.offsetWidth;
        tag.classList.add('play');
      };

      const handleMouseEnter = () => {
        play();
      };

      const handleAnimEnd = (e: AnimationEvent) => {
        if (
          (e.target as HTMLElement).classList.contains('ch') &&
          e.target === name.lastElementChild
        ) {
          tag.classList.remove('play');
        }
      };

      tag.addEventListener('mouseenter', handleMouseEnter);
      tag.addEventListener('animationend', handleAnimEnd as EventListener);

      let isIntersecting = true;
      const io = new IntersectionObserver(([entry]) => {
        isIntersecting = entry.isIntersecting;
      });
      io.observe(tag);

      let intervalId: ReturnType<typeof setInterval> | null = null;
      const timeoutId = setTimeout(
        () => {
          play();
          intervalId = setInterval(() => {
            if (
              isIntersecting &&
              !window.matchMedia('(prefers-reduced-motion: reduce)').matches
            ) {
              play();
            }
          }, 7000);
        },
        1800 + k * 1600
      );

      cleanups.push(() => {
        tag.removeEventListener('mouseenter', handleMouseEnter);
        tag.removeEventListener('animationend', handleAnimEnd as EventListener);
        io.disconnect();
        clearTimeout(timeoutId);
        if (intervalId) clearInterval(intervalId);
      });
    });

    return () => {
      cleanups.forEach((c) => c());
    };
  }, []);

  // 2. Hero bottom dissolve: the page dissolves into the picture
  useEffect(() => {
    const bot =
      canvasRef.current ||
      (document.getElementById('heroDissolve') as HTMLCanvasElement | null);
    const sec = heroRef.current;
    let roDissolve: ResizeObserver | null = null;
    if (bot && sec) {
      const H = 44; // band depth including 2px bleed outside the section
      const TIERS = [
        { from: 0, to: 10, cell: 4 },
        { from: 10, to: 24, cell: 3 },
        { from: 24, to: 40, cell: 2 },
      ]; // distance from the page edge -> cell size (coarse at the edge, fine inside)
      const seeded = (i: number) => {
        const x = Math.sin(i * 12.9898) * 43758.5453;
        return x - Math.floor(x);
      };
      const pageColour = () => {
        const bodyCol = getComputedStyle(document.body).backgroundColor;
        if (bodyCol && bodyCol !== 'rgba(0, 0, 0, 0)' && bodyCol !== 'transparent') return bodyCol;
        const docCol = getComputedStyle(document.documentElement).backgroundColor;
        if (docCol && docCol !== 'rgba(0, 0, 0, 0)' && docCol !== 'transparent') return docCol;
        return '#FAF9F5';
      };
      const paint = (canvas: HTMLCanvasElement, flip: boolean) => {
        const W = sec.clientWidth;
        canvas.width = W;
        canvas.height = H;
        const g = canvas.getContext('2d');
        if (!g) return;
        g.clearRect(0, 0, W, H);
        g.fillStyle = pageColour();

        // Solid band over the 2px bleed margin to prevent any subpixel background bleed on any device
        if (!flip) {
          g.fillRect(0, 0, W, 3);
        } else {
          g.fillRect(0, H - 3, W, 3);
        }

        for (const tier of TIERS) {
          const size = tier.cell;
          for (let d = tier.from; d < tier.to; d += size) {
            for (let x = 0; x < W + size; x += size) {
              const keep = Math.pow(1 - d / 40, 1.7);
              const th = seeded(
                ((x / size) | 0) * 131 + ((d / size) | 0) * 17 + size
              );
              if (th >= keep) continue;
              const y = flip ? H - 3 - d - size : d + 2;
              g.fillRect(x, y, size, size);
            }
          }
        }
      };
      const draw = () => {
        paint(bot, true);
      };
      roDissolve = new ResizeObserver(draw);
      roDissolve.observe(sec);
      draw();
    }

    return () => {
      roDissolve?.disconnect();
    };
  }, []);

  // Ensure no pixfill canvas is attached to hero CTA button
  useEffect(() => {
    document
      .querySelectorAll('.hero__cta canvas.pixfill')
      .forEach((c) => c.remove());
    document
      .querySelectorAll('.hero__cta .has-pixfill')
      .forEach((el) => el.classList.remove('has-pixfill'));
  }, []);

  const handleCtaClick = () => {
    trackEvent('cta_clicked', {
      cta_name: 'hero_join_beta',
      cta_location: 'hero',
      button_text: 'Join Beta',
    });
  };

  const frontendUrl =
    process.env.NEXT_PUBLIC_FRONTEND_URL || 'https://chat.usepunk.ai';
  const joinBetaUrl = `${frontendUrl.replace(/\/+$/, '')}`;

  return (
    <>
      <section
        className="hero relative isolate flex min-h-[calc(47.5vw+80px)] items-start pt-[calc(clamp(88px,7.5vw,118px)+80px)] pb-42.5 max-md:min-h-0 max-md:pt-30 max-md:pb-44"
        ref={heroRef}
      >
        <style>{`
          .hero__dissolve {
            position: absolute;
            left: 0;
            right: 0;
            width: 100%;
            height: 44px;
            z-index: 1;
            pointer-events: none;
            image-rendering: pixelated;
            image-rendering: crisp-edges;
          }
          .hero__dissolve--bottom { bottom: -2px; }
        `}</style>

        <div
          className="hero__bg absolute inset-x-0 top-0 bottom-0 -z-20 overflow-hidden bg-[#2A6FC9]"
          id="heroBg"
          aria-hidden="true"
        >
          <picture className="contents">
            <source media="(max-width: 767px)" srcSet={mobileHeroSrcSet} />
            <source media="(min-width: 768px)" srcSet={desktopHeroSrcSet} />
            <Image
              id="heroImg"
              ref={imgRef}
              src="/hero-bg.jpg"
              alt=""
              width={5376}
              height={3008}
              priority
              className="hero__img absolute inset-0 block h-full w-full object-cover object-top max-md:object-[center_38%]"
            />
          </picture>
          <div
            className="hero__hl pointer-events-none absolute max-xl:hidden"
            id="heroHl"
          >
            {HIGHLIGHT_TAGS.map((tag) => (
              <div
                key={tag.name}
                className="hl absolute [--lead:8px]"
                style={
                  {
                    left: tag.left,
                    top: tag.top,
                    width: tag.width,
                    height: tag.height,
                    '--hl-fd': tag.fd,
                  } as React.CSSProperties
                }
              >
                <div className="tag" aria-label={tag.name}>
                  <i className="tag__dot" aria-hidden="true" />
                  <span className="tag__t">
                    <span className="tag__name">
                      {tag.name.split('').map((char, i) => (
                        <span
                          key={i}
                          className="ch"
                          aria-hidden="true"
                          style={{ '--i': i } as React.CSSProperties}
                        >
                          {char}
                        </span>
                      ))}
                    </span>
                    <span className="tag__sub">{tag.sub}</span>
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Hero Field Edge: pixel dissolves into the page */}
        <canvas
          ref={canvasRef}
          id="heroDissolve"
          className="hero__dissolve hero__dissolve--bottom"
          aria-hidden="true"
        />

        <div className="wrap relative z-10 mx-auto w-[min(1240px,calc(100%-40px))] max-sm:w-[calc(100%-32px)]">
          <div className="hero__copy relative z-10 mx-auto grid max-w-205 justify-items-center text-center">
            <h1 className="font-display m-0 mb-3 w-full max-w-[28ch] sm:max-w-[34ch] md:max-w-none text-[clamp(23px,1.2rem+1.5vw,38px)] leading-[1.16] sm:leading-[1.12] font-semibold tracking-[-0.03em] sm:tracking-[-0.045em] text-balance text-white [text-shadow:0_1px_2px_rgba(0,10,30,0.38)]">
              Target people with Meta ads <br className="hidden md:inline" />
              based on the places they visit in real life.
            </h1>
            <p className="lede font-body m-0 mb-4.5 w-full max-w-[46ch] sm:max-w-[54ch] md:max-w-155 lg:max-w-none text-[clamp(13.5px,0.825rem+0.35vw,15px)] leading-[1.55] sm:leading-[1.6] font-medium text-pretty text-white [text-shadow:0_1px_2px_rgba(0,10,30,0.42)]">
              Describe where your customers go. Punk searches location data from apps and websites to build an audience from devices that have been there. Launch ads easily in Punk, or use the audience in Meta Ads Manager.
            </p>

            <div className="hero__cta">
              <a
                href={joinBetaUrl}
                target="_blank"
                rel="noopener noreferrer"
                data-ea=""
                onClick={handleCtaClick}
                className={HERO_CTA_BTN_CLASSES}
              >
                <span className="pk-btn__label relative z-1 flex h-full items-center justify-center text-center">
                  <span>
                    <span>Get started for free</span>
                  </span>
                </span>
              </a>
            </div>
          </div>
        </div>
      </section>

      <Space height={{base: 70, md: 140}} />

      {/* ============ Meta line ============ */}
      <section className="metaline reveal pb-16" aria-label="Currently targeting for">
        <div className="wrap">
          <div className="metaline__wrap">
            <span className="metaline__eyebrow">No Meta ads experience needed. Just chat.</span>
            <p className="metaline__name">
              <svg
                className="meta-ico"
                viewBox="0 0 16 16"
                fill="currentColor"
                aria-hidden="true"
              >
                <path
                  fillRule="evenodd"
                  d="M8.217 5.243C9.145 3.988 10.171 3 11.483 3 13.96 3 16 6.153 16.001 9.907c0 2.29-.986 3.725-2.757 3.725-1.543 0-2.395-.866-3.924-3.424l-.667-1.123-.118-.197a55 55 0 0 0-.53-.877l-1.178 2.08c-1.673 2.925-2.615 3.541-3.923 3.541C1.086 13.632 0 12.217 0 9.973 0 6.388 1.995 3 4.598 3q.477-.001.924.122c.31.086.611.22.913.407.577.359 1.154.915 1.782 1.714m1.516 2.224q-.378-.615-.727-1.133L9 6.326c.845-1.305 1.543-1.954 2.372-1.954 1.723 0 3.102 2.537 3.102 5.653 0 1.188-.39 1.877-1.195 1.877-.773 0-1.142-.51-2.61-2.87zM4.846 4.756c.725.1 1.385.634 2.34 2.001A212 212 0 0 0 5.551 9.3c-1.357 2.126-1.826 2.603-2.581 2.603-.777 0-1.24-.682-1.24-1.9 0-2.602 1.298-5.264 2.846-5.264q.137 0 .27.018"
                />
              </svg>
              Meta Ads
            </p>
          </div>
        </div>
      </section>
    </>
  );
}

export default HeroSection;
