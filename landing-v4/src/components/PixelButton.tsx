'use client';

import React, { useEffect, useRef } from 'react';
import Link from 'next/link';

export interface PixelButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  href?: string;
  as?: 'button' | 'span' | 'div';
  onClick?: (e: React.MouseEvent) => void;
  className?: string;
  labelClassName?: string;
  children: React.ReactNode;
  icon?: React.ReactNode;
  iconPosition?: 'left' | 'right';
  variant?: 'capture' | 'primary' | 'secondary';
  sendingText?: string;
  doneText?: string;
  type?: 'button' | 'submit' | 'reset';
  target?: string;
  rel?: string;
  style?: React.CSSProperties;
}

export function PixelButton({
  href,
  onClick,
  className = '',
  labelClassName = '',
  children,
  icon,
  variant,
  sendingText = 'Adding you…',
  doneText = "You're on the list",
  type = 'button',
  target,
  rel,
  style,
  as,
  ...rest
}: PixelButtonProps) {
  const btnRef = useRef<HTMLElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);

  const isCapture =
    variant === 'capture' || (variant !== 'primary' && variant !== 'secondary');

  const isSecondary = variant === 'secondary';

  useEffect(() => {
    const btn = btnRef.current;
    const canvas = canvasRef.current;
    if (!btn || !canvas) return;

    const reduced = window.matchMedia(
      '(prefers-reduced-motion: reduce)'
    ).matches;
    const TILE = 7;
    const IN_MS = 420;
    const OUT_MS = 300;

    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    const cap = btn.closest('[data-capture]') || btn.closest('form');

    let W = 0,
      H = 0,
      cols = 0,
      rows = 0,
      order: Array<{ x: number; y: number; s: number }> = [],
      p = 0,
      targetVal = 0,
      raf = 0,
      last = 0,
      dpr = 1;

    function size() {
      if (!btn || !canvas) return;
      const inset = isCapture
        ? 0
        : parseFloat(getComputedStyle(btn).getPropertyValue('--pk-gap')) || 6;

      Object.assign(canvas.style, {
        position: 'absolute',
        left: inset + 'px',
        top: inset + 'px',
        right: inset + 'px',
        bottom: inset + 'px',
        width: `calc(100% - ${inset * 2}px)`,
        height: `calc(100% - ${inset * 2}px)`,
        pointerEvents: 'none',
        zIndex: '-1',
      });

      const r = canvas.getBoundingClientRect();
      dpr = Math.min(window.devicePixelRatio || 1, 2);
      canvas.width = Math.max(1, Math.round(r.width * dpr));
      canvas.height = Math.max(1, Math.round(r.height * dpr));
      W = canvas.width;
      H = canvas.height;
      cols = Math.max(1, Math.round(r.width / TILE));
      rows = Math.max(1, Math.round(r.height / TILE));
      order = [];
      for (let y = 0; y < rows; y++) {
        for (let x = 0; x < cols; x++) {
          order.push({
            x,
            y,
            s: ((x + 0.5) / cols) * 0.82 + Math.random() * 0.18,
          });
        }
      }
      draw();
    }

    function draw() {
      if (!ctx) return;
      ctx.clearRect(0, 0, W, H);
      if (p <= 0) return;
      ctx.fillStyle =
        (btn && getComputedStyle(btn).getPropertyValue('--pk').trim()) ||
        '#F02D8A';
      if (p >= 1) {
        ctx.fillRect(0, 0, W, H);
        return;
      }
      for (const o of order) {
        const k = Math.min(1, Math.max(0, (p - o.s) / 0.16));
        if (k <= 0) continue;
        const q = Math.ceil(k * 3) / 3;
        const x0 = Math.round((o.x * W) / cols);
        const x1 = Math.round(((o.x + 1) * W) / cols);
        const y0 = Math.round((o.y * H) / rows);
        const y1 = Math.round(((o.y + 1) * H) / rows);
        if (q >= 1) {
          ctx.fillRect(x0, y0, x1 - x0, y1 - y0);
          continue;
        }
        const bw = Math.round((x1 - x0) * q);
        const bh = Math.round((y1 - y0) * q);
        ctx.fillRect(
          x0 + Math.round((x1 - x0 - bw) / 2),
          y0 + Math.round((y1 - y0 - bh) / 2),
          bw,
          bh
        );
      }
    }

    function step(now: number) {
      const dt = now - (last || now);
      last = now;
      const dir = Math.sign(targetVal - p);
      p = reduced
        ? targetVal
        : Math.min(
            1,
            Math.max(0, p + ((dir * dt) / (dir > 0 ? IN_MS : OUT_MS)) * 1.16)
          );
      draw();
      if (p !== targetVal) {
        raf = requestAnimationFrame(step);
      } else {
        raf = 0;
        last = 0;
      }
    }

    const set = (on: boolean) => {
      const want =
        on ||
        (cap &&
          (cap.classList.contains('is-sending') ||
            cap.classList.contains('is-done')))
          ? 1
          : 0;
      if (want === targetVal) return;
      targetVal = want;
      if (!raf) raf = requestAnimationFrame(step);
    };

    const handlePointerEnter = () => set(true);
    const handlePointerLeave = () => set(false);
    const handleFocus = () => set(true);
    const handleBlur = () => set(false);

    btn.addEventListener('pointerenter', handlePointerEnter);
    btn.addEventListener('pointerleave', handlePointerLeave);
    btn.addEventListener('focus', handleFocus);
    btn.addEventListener('blur', handleBlur);

    let mutObs: MutationObserver | null = null;
    if (cap) {
      mutObs = new MutationObserver(() => set(btn.matches(':hover')));
      mutObs.observe(cap, { attributes: true, attributeFilter: ['class'] });
    }

    const ro = new ResizeObserver(size);
    ro.observe(btn);
    size();

    if (btn.matches(':hover') || document.activeElement === btn) {
      set(true);
    }

    return () => {
      if (raf) cancelAnimationFrame(raf);
      ro.disconnect();
      if (mutObs) mutObs.disconnect();
      btn.removeEventListener('pointerenter', handlePointerEnter);
      btn.removeEventListener('pointerleave', handlePointerLeave);
      btn.removeEventListener('focus', handleFocus);
      btn.removeEventListener('blur', handleBlur);
    };
  }, [isCapture]);

  const defaultArrow = (
    <svg
      className="h-4.5 w-4.5 transition-transform duration-300 ease-[cubic-bezier(0.7,0,0.2,1)] group-hover/btn:-rotate-90 group-focus-visible/btn:-rotate-90"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2.4"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M5 12h14M13 6l6 6-6 6" />
    </svg>
  );

  const defaultCheck = (
    <svg
      className="hidden h-4.5 w-4.5 group-[.is-done]/cap:block!"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2.6"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M5 12l5 5L20 7" />
    </svg>
  );

  const captureBtnClasses = [
    'group/btn',
    'font-body',
    'text-ink',
    'relative',
    'isolate',
    'z-1',
    'inline-flex',
    'shrink-0',
    'cursor-pointer',
    'items-stretch',
    'border-0',
    'bg-transparent',
    'p-0',
    'text-[15px]',
    'leading-none',
    'font-medium',
    'select-none',
    'outline-none',
    'focus:outline-none',
    'focus-visible:outline-none',
    '[-webkit-tap-highlight-color:transparent]',
    'group-[.is-done]/cap:pointer-events-none',
    className,
  ]
    .filter(Boolean)
    .join(' ');

  const standardBtnClasses = [
    'group/btn',
    isSecondary
      ? '[--pk-tick:rgba(20,20,20,0.4)]'
      : '[--pk-tick:rgba(20,20,20,0.6)]',
    'relative',
    'isolate',
    'inline-flex',
    'items-stretch',
    '[height:var(--pk-h,54px)]',
    '[padding:var(--pk-gap,6px)]',
    'font-body',
    'text-[14.5px]',
    'font-medium',
    'leading-none',
    '[color:var(--pk-ink,#141414)]',
    '[background:var(--pk-bg,transparent)]',
    'no-underline',
    'border-0',
    'cursor-pointer',
    'box-border',
    'select-none',
    'outline-none',
    'focus:outline-none',
    'focus-visible:outline-none',
    '[-webkit-tap-highlight-color:transparent]',
    'active:before:[filter:brightness(0.9)]',
    'motion-reduce:before:transition-none',
    "after:content-['']",
    'after:absolute',
    'after:inset-0',
    'after:pointer-events-none',
    'after:border-[1.5px]',
    'after:border-[var(--pk-tick,#141414)]',
    'after:transition-opacity',
    'after:duration-200',
    'hover:after:opacity-0',
    'focus-visible:after:opacity-0',
    'group-hover/btn:after:opacity-0',
    'group-focus-visible/btn:after:opacity-0',
    'after:[-webkit-mask:linear-gradient(#000,#000)_top_left/var(--pk-tick-len,10px)_var(--pk-tick-len,10px)_no-repeat,linear-gradient(#000,#000)_top_right/var(--pk-tick-len,10px)_var(--pk-tick-len,10px)_no-repeat,linear-gradient(#000,#000)_bottom_left/var(--pk-tick-len,10px)_var(--pk-tick-len,10px)_no-repeat,linear-gradient(#000,#000)_bottom_right/var(--pk-tick-len,10px)_var(--pk-tick-len,10px)_no-repeat]',
    'after:[mask:linear-gradient(#000,#000)_top_left/var(--pk-tick-len,10px)_var(--pk-tick-len,10px)_no-repeat,linear-gradient(#000,#000)_top_right/var(--pk-tick-len,10px)_var(--pk-tick-len,10px)_no-repeat,linear-gradient(#000,#000)_bottom_left/var(--pk-tick-len,10px)_var(--pk-tick-len,10px)_no-repeat,linear-gradient(#000,#000)_bottom_right/var(--pk-tick-len,10px)_var(--pk-tick-len,10px)_no-repeat]',
    className,
  ]
    .filter(Boolean)
    .join(' ');

  const fullClassName = isCapture ? captureBtnClasses : standardBtnClasses;

  const mergedStyle: React.CSSProperties = isCapture
    ? ({
        '--pk': '#F02D8A',
        '--h': '66px',
        '--gap': '7px',
        '--t': '.32s',
        ...style,
      } as React.CSSProperties)
    : style || {};

  const innerContent = isCapture ? (
    <>
      <canvas
        ref={canvasRef}
        className="pointer-events-none absolute inset-0 -z-1 h-full w-full"
        aria-hidden="true"
      />
      <span className="flex items-center pr-5.5 pl-5 max-sm:hidden">
        <span className="text-ink block h-[1.2em] leading-[1.2em] transition-colors duration-200 group-hover/btn:text-white group-focus-visible/btn:text-white">
          {children}
        </span>
      </span>
      <span className="bg-punk relative grid w-13 shrink-0 place-items-center text-white">
        <span
          className="border-ink pointer-events-none absolute -inset-0.5 border-[1.5px] transition-opacity duration-200 [-webkit-mask:linear-gradient(#000,#000)_top_left/7px_7px_no-repeat,linear-gradient(#000,#000)_top_right/7px_7px_no-repeat,linear-gradient(#000,#000)_bottom_left/7px_7px_no-repeat,linear-gradient(#000,#000)_bottom_right/7px_7px_no-repeat] [mask:linear-gradient(#000,#000)_top_left/7px_7px_no-repeat,linear-gradient(#000,#000)_top_right/7px_7px_no-repeat,linear-gradient(#000,#000)_bottom_left/7px_7px_no-repeat,linear-gradient(#000,#000)_bottom_right/7px_7px_no-repeat] group-hover/btn:opacity-0 group-focus-visible/btn:opacity-0 group-[.is-done]/cap:opacity-0! group-[.is-sending]/cap:opacity-0!"
          aria-hidden="true"
        />
        {icon !== undefined ? (
          icon
        ) : (
          <>
            <svg
              className="group-[.is-sending]/cap:animate-nudge h-4.5 w-4.5 transition-transform duration-300 ease-[cubic-bezier(0.7,0,0.2,1)] group-hover/btn:-rotate-90 group-focus-visible/btn:-rotate-90 group-[.is-done]/cap:hidden!"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2.4"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d="M5 12h14M13 6l6 6-6 6" />
            </svg>
            {defaultCheck}
          </>
        )}
      </span>
    </>
  ) : (
    <>
      <canvas
        ref={canvasRef}
        className="pointer-events-none absolute inset-0 -z-1"
        aria-hidden="true"
      />
      {icon !== undefined
        ? icon && (
            <span className="bg-punk after:border-ink relative grid w-[calc(var(--pk-h,54px)-var(--pk-gap,6px)*2)] shrink-0 place-items-center text-white after:pointer-events-none after:absolute after:-inset-0.5 after:border-[1.5px] after:transition-opacity after:duration-200 after:content-[''] after:[-webkit-mask:linear-gradient(#000,#000)_top_left/7px_7px_no-repeat,linear-gradient(#000,#000)_top_right/7px_7px_no-repeat,linear-gradient(#000,#000)_bottom_left/7px_7px_no-repeat,linear-gradient(#000,#000)_bottom_right/7px_7px_no-repeat] after:[mask:linear-gradient(#000,#000)_top_left/7px_7px_no-repeat,linear-gradient(#000,#000)_top_right/7px_7px_no-repeat,linear-gradient(#000,#000)_bottom_left/7px_7px_no-repeat,linear-gradient(#000,#000)_bottom_right/7px_7px_no-repeat] group-hover/btn:after:opacity-0 group-focus-visible/btn:after:opacity-0">
              {icon}
            </span>
          )
        : !isSecondary && (
            <span className="bg-punk after:border-ink relative grid w-[calc(var(--pk-h,54px)-var(--pk-gap,6px)*2)] shrink-0 place-items-center text-white after:pointer-events-none after:absolute after:-inset-0.5 after:border-[1.5px] after:transition-opacity after:duration-200 after:content-[''] after:[-webkit-mask:linear-gradient(#000,#000)_top_left/7px_7px_no-repeat,linear-gradient(#000,#000)_top_right/7px_7px_no-repeat,linear-gradient(#000,#000)_bottom_left/7px_7px_no-repeat,linear-gradient(#000,#000)_bottom_right/7px_7px_no-repeat] after:[mask:linear-gradient(#000,#000)_top_left/7px_7px_no-repeat,linear-gradient(#000,#000)_top_right/7px_7px_no-repeat,linear-gradient(#000,#000)_bottom_left/7px_7px_no-repeat,linear-gradient(#000,#000)_bottom_right/7px_7px_no-repeat] group-hover/btn:after:opacity-0 group-focus-visible/btn:after:opacity-0">
              {defaultArrow}
            </span>
          )}
      <span className={`text-ink flex items-center px-3 leading-none font-medium transition-colors duration-200 group-hover/btn:text-white group-focus-visible/btn:text-white md:px-5${labelClassName ? ' ' + labelClassName : ''}`}>
        {children}
      </span>
    </>
  );

  if (href) {
    return (
      <Link
        ref={btnRef as React.RefObject<HTMLAnchorElement>}
        href={href}
        onClick={onClick}
        className={fullClassName}
        style={mergedStyle}
        target={target}
        rel={rel}
        {...(rest as React.AnchorHTMLAttributes<HTMLAnchorElement>)}
      >
        {innerContent}
      </Link>
    );
  }

  if (as === 'span') {
    return (
      <span
        ref={btnRef as React.RefObject<HTMLSpanElement>}
        onClick={onClick}
        className={fullClassName}
        style={mergedStyle}
        {...(rest as React.HTMLAttributes<HTMLSpanElement>)}
      >
        {innerContent}
      </span>
    );
  }

  return (
    <button
      ref={btnRef as React.RefObject<HTMLButtonElement>}
      type={type}
      onClick={onClick}
      className={fullClassName}
      style={mergedStyle}
      {...(rest as React.ButtonHTMLAttributes<HTMLButtonElement>)}
    >
      {innerContent}
    </button>
  );
}

export default PixelButton;
