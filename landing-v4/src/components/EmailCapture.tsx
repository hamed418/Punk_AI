'use client';

import React, { useState, useRef, useEffect } from 'react';
import { trackEvent, identifyUser } from '@/lib/analytics';
import { sanitizeEmailDomain } from '@/lib/analytics/utm';

interface EmailCaptureProps {
  noteText?: React.ReactNode;
  buttonText?: string;
  className?: string;
}

export function EmailCapture({
  noteText = "We'll only email you about your invite.",
  buttonText = 'Request an invite',
  className = '',
}: EmailCaptureProps) {
  const formRef = useRef<HTMLFormElement>(null);
  const btnRef = useRef<HTMLButtonElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);

  const [email, setEmail] = useState('');
  const [, setHint] = useState('');
  const [, setShowHint] = useState(false);
  const [, setHasValue] = useState(false);
  const [status, setStatus] = useState<'idle' | 'sending' | 'done' | 'error'>(
    'idle'
  );
  const [note, setNote] = useState<React.ReactNode>(noteText);
  const [noteType, setNoteType] = useState<'' | 'err' | 'ok'>('');

  const FREE = [
    'gmail.com',
    'yahoo.com',
    'hotmail.com',
    'outlook.com',
    'icloud.com',
    'proton.me',
    'protonmail.com',
    'aol.com',
  ];

  const valid = (v: string) => /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(v);

  const statusRef = useRef(status);
  const setHoverRef = useRef<(on: boolean) => void>(() => {});

  // Button pixfill effect
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

    let W = 0,
      H = 0,
      cols = 0,
      rows = 0,
      order: Array<{ x: number; y: number; s: number }> = [],
      p = 0,
      tgt = 0,
      raf = 0,
      last = 0,
      dpr = 1;

    function size() {
      if (!btn || !canvas) return;
      Object.assign(canvas.style, {
        left: '0px',
        top: '0px',
        right: '0px',
        bottom: '0px',
        width: '100%',
        height: '100%',
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
      const dir = Math.sign(tgt - p);
      p = reduced
        ? tgt
        : Math.min(
            1,
            Math.max(0, p + ((dir * dt) / (dir > 0 ? IN_MS : OUT_MS)) * 1.16)
          );
      draw();
      if (p !== tgt) raf = requestAnimationFrame(step);
      else {
        raf = 0;
        last = 0;
      }
    }

    const set = (on: boolean) => {
      const want =
        on || statusRef.current === 'sending' || statusRef.current === 'done'
          ? 1
          : 0;
      if (want === tgt) return;
      tgt = want;
      if (!raf) raf = requestAnimationFrame(step);
    };

    setHoverRef.current = set;

    const onEnter = () => set(true);
    const onLeave = () => set(false);

    btn.addEventListener('pointerenter', onEnter);
    btn.addEventListener('pointerleave', onLeave);
    btn.addEventListener('focus', onEnter);
    btn.addEventListener('blur', onLeave);

    const ro = new ResizeObserver(size);
    ro.observe(btn);
    size();

    return () => {
      cancelAnimationFrame(raf);
      btn.removeEventListener('pointerenter', onEnter);
      btn.removeEventListener('pointerleave', onLeave);
      btn.removeEventListener('focus', onEnter);
      btn.removeEventListener('blur', onLeave);
      ro.disconnect();
    };
  }, []);

  useEffect(() => {
    statusRef.current = status;
    if (btnRef.current) {
      setHoverRef.current(btnRef.current.matches(':hover'));
    }
  }, [status]);

  const handleInput = (e: React.ChangeEvent<HTMLInputElement>) => {
    const v = e.target.value;
    setEmail(v);
    const trimmed = v.trim();
    setHasValue(trimmed.length > 0);

    if (status === 'error') {
      setStatus('idle');
      setNoteType('');
      setNote(noteText);
    }

    const at = trimmed.indexOf('@');
    if (at > 0 && trimmed.length > at + 1) {
      const dom = trimmed.slice(at + 1).toLowerCase();
      setHint(FREE.includes(dom) ? 'personal email' : dom);
      setShowHint(true);
    } else {
      setShowHint(false);
    }
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (status === 'sending' || status === 'done') return;

    const trimmed = email.trim();
    if (!valid(trimmed)) {
      setStatus('error');
      setNoteType('err');
      setNote(
        trimmed
          ? "That doesn't look like an email address."
          : 'Enter your work email to get access.'
      );
      return;
    }

    const domain = sanitizeEmailDomain(trimmed);

    trackEvent('early_access_form_submitted', {
      form_type: 'apply_waitlist',
      email_domain: domain,
      has_email: Boolean(trimmed),
    });

    trackEvent('waitlist_joined', {
      source: 'email_capture',
      email_domain: domain,
    });

    identifyUser(trimmed, {
      email: trimmed,
      is_waitlist_applicant: true,
    });

    setStatus('sending');
    setTimeout(() => {
      setStatus('done');
      setShowHint(false);
      setNoteType('ok');
      setNote(`Check ${trimmed} for a confirmation.`);
    }, 1100);
  };

  const formClasses = [
    'pk-cap group/cap relative isolate block w-[min(100%,520px)] bg-white p-[7px] [--pk:#f02d8a] [--gap:7px] [--h:66px] [--t:0.32s] [--tick:#141414]',
    status === 'sending' ? 'is-sending' : '',
    status === 'done' ? 'is-done' : '',
    status === 'error'
      ? 'is-error animate-[shake_0.4s_cubic-bezier(0.36,0.07,0.19,0.97)]'
      : '',
    className,
  ]
    .filter(Boolean)
    .join(' ');

  return (
    <>
      <form
        ref={formRef}
        className={formClasses}
        noValidate
        data-capture
        onSubmit={handleSubmit}
      >
        <div className="pk-cap__row relative flex h-[calc(66px-7px*2)] items-stretch">
          <label className="pk-cap__field group/field relative z-1 flex min-w-0 flex-1 items-center px-4.5">
            <input
              type="email"
              name="email"
              autoComplete="email"
              placeholder="Work email"
              required
              value={email}
              onChange={handleInput}
              readOnly={status === 'sending' || status === 'done'}
              className="font-body text-ink caret-punk placeholder:text-muted m-0 h-full w-full truncate border-0 bg-transparent px-0 py-0 text-[16px] leading-none font-medium outline-none"
            />
          </label>
          <button
            ref={btnRef}
            className={`pk-cap__btn has-pixfill group/btn font-body [WebkitTapHighlightColor:transparent] text-ink relative isolate z-1 inline-flex shrink-0 cursor-pointer items-stretch border-0 bg-transparent p-0 text-[15px] leading-none font-medium ${status === 'done' ? 'pointer-events-none' : ''}`}
            type="submit"
          >
            <canvas
              ref={canvasRef}
              className="pixfill pointer-events-none absolute inset-0 z-[-1] h-full w-full"
              aria-hidden="true"
            />
            <span className="lb flex items-center pr-5.5 pl-5 max-sm:hidden">
              <span className="block h-[1.2em] overflow-hidden">
                <span
                  className={`block h-[1.2em] leading-[1.2em] whitespace-nowrap transition-transform duration-[0.32s] ease-[cubic-bezier(0.7,0,0.2,1)] group-hover/btn:-translate-y-full group-focus-visible/btn:-translate-y-full ${status === 'sending' ? 'translate-y-[-200%]!' : ''} ${status === 'done' ? 'translate-y-[-300%]!' : ''}`}
                >
                  <span className="block h-[1.2em] leading-[1.2em]">
                    {buttonText}
                  </span>
                  <span className="block h-[1.2em] leading-[1.2em] text-white">
                    {buttonText}
                  </span>
                  <span className="block h-[1.2em] leading-[1.2em] text-white">
                    Adding you…
                  </span>
                  <span className="block h-[1.2em] leading-[1.2em] text-white">
                    You&apos;re on the list
                  </span>
                </span>
              </span>
            </span>
            <span className="ic bg-punk relative grid w-13 place-items-center text-white">
              <span
                className={`border-ink pointer-events-none absolute -inset-0.5 border-[1.5px] transition-opacity duration-200 [-webkit-mask:linear-gradient(#000,#000)_top_left/7px_7px_no-repeat,linear-gradient(#000,#000)_top_right/7px_7px_no-repeat,linear-gradient(#000,#000)_bottom_left/7px_7px_no-repeat,linear-gradient(#000,#000)_bottom_right/7px_7px_no-repeat] [mask:linear-gradient(#000,#000)_top_left/7px_7px_no-repeat,linear-gradient(#000,#000)_top_right/7px_7px_no-repeat,linear-gradient(#000,#000)_bottom_left/7px_7px_no-repeat,linear-gradient(#000,#000)_bottom_right/7px_7px_no-repeat] group-hover/btn:opacity-0 ${status === 'sending' || status === 'done' ? 'opacity-0!' : ''}`}
              />
              <svg
                className={`arrow h-4.5 w-4.5 transition-transform duration-[0.32s] ease-[cubic-bezier(0.7,0,0.2,1)] group-hover/btn:-rotate-90 ${status === 'sending' ? 'animate-nudge' : ''} ${status === 'done' ? 'hidden!' : 'block'}`}
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2.4"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <path d="M5 12h14M13 6l6 6-6 6" />
              </svg>
              <svg
                className={`check h-4.5 w-4.5 ${status === 'done' ? 'block!' : 'hidden'}`}
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2.6"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <path d="M5 12l5 5L20 7" />
              </svg>
            </span>
          </button>
        </div>
      </form>
      <div
        className={`pk-cap__note text-ink mt-3 min-h-[1.4em] text-center text-[13px] ${noteType === 'err' ? 'err text-[#d93a3a]!' : noteType === 'ok' ? 'ok' : ''}`}
        data-note
      >
        {note}
      </div>
    </>
  );
}
