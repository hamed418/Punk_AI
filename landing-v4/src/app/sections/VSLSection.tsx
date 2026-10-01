'use client';

import React, { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Play, Pause, X, Volume2, VolumeX, RotateCw, Maximize2 } from 'lucide-react';

export function VSLSection() {
  const sectionRef = useRef<HTMLElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const heroRef = useRef<HTMLDivElement>(null);
  const vslWrapRef = useRef<HTMLDivElement>(null);
  const perspRef = useRef<HTMLDivElement>(null);

  const topDissolveRef = useRef<HTMLCanvasElement>(null);
  const botDissolveRef = useRef<HTMLCanvasElement>(null);

  const [mounted, setMounted] = useState(false);
  const [isMobileModalOpen, setIsMobileModalOpen] = useState(false);
  const [viewportDims, setViewportDims] = useState<{ w: number; h: number }>({
    w: 0,
    h: 0,
  });
  const [rotationAngle, setRotationAngle] = useState<90 | 270>(90);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [isModalPlaying, setIsModalPlaying] = useState(false);
  const [isModalMuted, setIsModalMuted] = useState(false);
  const [showControls, setShowControls] = useState(true);
  const hideControlsTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const modalVideoRef = useRef<HTMLVideoElement>(null);

  useEffect(() => {
    setMounted(true);
  }, []);

  const scrollPosRef = useRef(0);
  const isEndingRef = useRef(false);

  const exitAllFullscreen = () => {
    // 1. Apple WebKit video-level fullscreen (iPhone / iPad)
    const mv = modalVideoRef.current as any;
    const iv = videoRef.current as any;
    if (mv) {
      if (typeof mv.webkitExitFullscreen === 'function') {
        try {
          mv.webkitExitFullscreen();
        } catch {}
      } else if (typeof mv.webkitExitFullScreen === 'function') {
        try {
          mv.webkitExitFullScreen();
        } catch {}
      }
    }
    if (iv) {
      if (typeof iv.webkitExitFullscreen === 'function') {
        try {
          iv.webkitExitFullscreen();
        } catch {}
      } else if (typeof iv.webkitExitFullScreen === 'function') {
        try {
          iv.webkitExitFullScreen();
        } catch {}
      }
    }

    // 2. Standard document-level fullscreen (Android, Chrome, Safari on iPad/Mac, etc.)
    if (typeof document !== 'undefined') {
      const doc = document as any;
      if (
        doc.fullscreenElement ||
        doc.webkitFullscreenElement ||
        doc.mozFullScreenElement ||
        doc.msFullscreenElement
      ) {
        if (doc.exitFullscreen) {
          doc.exitFullscreen().catch(() => {});
        } else if (doc.webkitExitFullscreen) {
          try {
            doc.webkitExitFullscreen();
          } catch {}
        } else if (doc.mozCancelFullScreen) {
          try {
            doc.mozCancelFullScreen();
          } catch {}
        } else if (doc.msExitFullscreen) {
          try {
            doc.msExitFullscreen();
          } catch {}
        }
      }
    }

    // 3. Screen orientation unlock
    if (
      typeof window !== 'undefined' &&
      window.screen?.orientation &&
      'unlock' in window.screen.orientation
    ) {
      try {
        (window.screen.orientation as any).unlock();
      } catch {}
    }
  };

  const handleOpenMobileModal = () => {
    if (typeof window !== 'undefined') {
      scrollPosRef.current =
        window.scrollY ||
        window.pageYOffset ||
        document.documentElement.scrollTop ||
        0;
    }

    const inlineV = videoRef.current;
    if (inlineV) inlineV.pause();

    const w = typeof window !== 'undefined' ? window.innerWidth : 390;
    const h = typeof window !== 'undefined' ? window.innerHeight : 844;
    setViewportDims({ w, h });
    setIsMobileModalOpen(true);
  };

  const handleCloseModal = () => {
    exitAllFullscreen();

    const inlineV = videoRef.current;
    const modalV = modalVideoRef.current;
    if (inlineV && modalV) {
      inlineV.currentTime = modalV.currentTime;
      modalV.pause();
    }
    setIsMobileModalOpen(false);
    if (typeof document !== 'undefined') {
      document.body.style.overflow = '';
    }

    if (typeof window !== 'undefined' && scrollPosRef.current) {
      const targetY = scrollPosRef.current;
      setTimeout(() => {
        window.scrollTo({
          top: targetY,
          behavior: 'instant' as ScrollBehavior,
        });
      }, 50);
    }
  };

  const handleVideoEnded = () => {
    if (isEndingRef.current) return;
    isEndingRef.current = true;

    // 1. Exit all native and browser fullscreen modes immediately
    exitAllFullscreen();

    // 2. Pause and reset both modal and inline video players to start (0s)
    const inlineV = videoRef.current;
    const modalV = modalVideoRef.current;
    if (modalV) {
      modalV.pause();
      modalV.currentTime = 0;
    }
    if (inlineV) {
      inlineV.pause();
      inlineV.currentTime = 0;
    }

    // 3. Reset playback state
    setIsModalPlaying(false);
    setCurrentTime(0);

    // 4. Close mobile modal to restore original screen state
    setIsMobileModalOpen(false);
    if (typeof document !== 'undefined') {
      document.body.style.overflow = '';
    }

    // 5. Restore scroll position in case mobile browser shifted viewport
    if (typeof window !== 'undefined' && scrollPosRef.current) {
      const targetY = scrollPosRef.current;
      setTimeout(() => {
        window.scrollTo({
          top: targetY,
          behavior: 'instant' as ScrollBehavior,
        });
      }, 50);
    }

    setTimeout(() => {
      isEndingRef.current = false;
    }, 600);
  };

  const toggleModalPlay = (e?: React.MouseEvent) => {
    e?.stopPropagation();
    const mv = modalVideoRef.current;
    if (!mv) return;
    if (mv.paused) {
      mv.play().catch(() => {});
    } else {
      mv.pause();
    }
    resetControlsTimeout();
  };

  const toggleModalMute = (e?: React.MouseEvent) => {
    e?.stopPropagation();
    const mv = modalVideoRef.current;
    if (!mv) return;
    mv.muted = !mv.muted;
    setIsModalMuted(mv.muted);
    resetControlsTimeout();
  };

  const handleSeek = (e: React.ChangeEvent<HTMLInputElement>) => {
    const time = Number(e.target.value);
    const mv = modalVideoRef.current;
    if (mv) {
      mv.currentTime = time;
      setCurrentTime(time);
    }
    resetControlsTimeout();
  };

  const handleNativeFullscreen = (e: React.MouseEvent) => {
    e.stopPropagation();
    const mv = modalVideoRef.current;
    if (!mv) return;
    // Synchronous call on user tap works reliably on iOS Safari
    if (
      'webkitEnterFullscreen' in mv &&
      typeof (mv as any).webkitEnterFullscreen === 'function'
    ) {
      try {
        (mv as any).webkitEnterFullscreen();
      } catch (err) {
        console.warn('webkitEnterFullscreen error', err);
      }
    } else if (mv.requestFullscreen) {
      mv.requestFullscreen().catch(() => {});
      if (
        typeof window !== 'undefined' &&
        window.screen?.orientation &&
        'lock' in window.screen.orientation
      ) {
        (window.screen.orientation as any).lock('landscape').catch(() => {});
      }
    }
  };

  const resetControlsTimeout = () => {
    setShowControls(true);
    if (hideControlsTimerRef.current) clearTimeout(hideControlsTimerRef.current);
    hideControlsTimerRef.current = setTimeout(() => {
      if (modalVideoRef.current && !modalVideoRef.current.paused) {
        setShowControls(false);
      }
    }, 3500);
  };

  const formatTime = (seconds: number) => {
    if (isNaN(seconds) || seconds < 0) return '0:00';
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins}:${secs < 10 ? '0' : ''}${secs}`;
  };

  // Manage modal open lifecycle, resize and orientation sync
  useEffect(() => {
    if (!isMobileModalOpen) return;

    const updateDims = () => {
      setViewportDims({
        w: window.innerWidth,
        h: window.innerHeight,
      });
    };

    updateDims();
    window.addEventListener('resize', updateDims, { passive: true });
    window.addEventListener('orientationchange', updateDims, { passive: true });

    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';

    // Synchronize play in modal
    let cleanAppleFs: (() => void) | null = null;
    const inlineV = videoRef.current;
    const modalV = modalVideoRef.current;
    if (modalV) {
      if (inlineV) {
        modalV.currentTime = inlineV.currentTime || 0;
      }
      modalV.muted = false;
      const playPromise = modalV.play();
      if (playPromise) {
        playPromise.catch(() => {
          modalV.muted = true;
          modalV.play().catch(() => {});
        });
      }

      const onAppleFullscreenEnd = () => {
        if (
          modalV.ended ||
          (modalV.duration && modalV.currentTime >= modalV.duration - 0.5)
        ) {
          handleVideoEnded();
        } else {
          handleCloseModal();
        }
      };
      (modalV as any).addEventListener?.(
        'webkitendfullscreen',
        onAppleFullscreenEnd
      );
      cleanAppleFs = () => {
        (modalV as any).removeEventListener?.(
          'webkitendfullscreen',
          onAppleFullscreenEnd
        );
      };
    }

    return () => {
      cleanAppleFs?.();
      window.removeEventListener('resize', updateDims);
      window.removeEventListener('orientationchange', updateDims);
      document.body.style.overflow = prevOverflow;
    };
  }, [isMobileModalOpen]);

  // Main section effect
  useEffect(() => {
    // 1. Video autoplay controller (Desktop only)
    const videoEl =
      videoRef.current ||
      (document.getElementById('vslVideo') as HTMLVideoElement | null);
    if (!videoEl) return;
    const v = videoEl;

    const wrap =
      vslWrapRef.current ||
      (document.getElementById('vslWrap') as HTMLElement | null) ||
      (v.closest('#vslWrap') as HTMLElement | null);
    if (!wrap) return;

    v.muted = true;
    v.defaultMuted = true;
    v.playsInline = true;

    const isMobileDevice = () =>
      typeof window !== 'undefined' &&
      window.matchMedia('(max-width: 767px)').matches;

    v.loop = !isMobileDevice();

    const loadFallback = () => {
      if (v.dataset.fallback) return;
      v.dataset.fallback = '1';
      v.src = '/api/video/clip-vsl';
      v.load();
      if (onScreen && !isMobileDevice()) go();
    };

    v.addEventListener('error', loadFallback);
    v.src = '/punk-vsl.mp4';
    setTimeout(() => {
      if (v.error || v.networkState === 3) loadFallback();
    }, 150);

    let onScreen = false;
    let armed: ReturnType<typeof setTimeout> | number = 0;

    const go = () => {
      if (isMobileDevice()) return;
      if (!v.paused) return;
      const p = v.play();
      if (p && p.catch) p.catch(() => {});
    };

    const arm = () => {
      if (isMobileDevice()) return;
      clearTimeout(armed);
      armed = setTimeout(() => {
        if (onScreen) go();
      }, 900);
    };

    v.addEventListener('canplay', () => {
      if (onScreen && v.paused && !isMobileDevice()) go();
    });
    v.addEventListener('loadeddata', () => {
      if (onScreen && v.paused && !isMobileDevice()) go();
    });

    const gestures = ['pointerdown', 'touchstart', 'keydown', 'scroll'];
    const gestureHandler = () => {
      if (onScreen && v.paused && !isMobileDevice()) go();
    };
    gestures.forEach((ev) =>
      window.addEventListener(ev, gestureHandler, { passive: true })
    );

    const ioWrap = new IntersectionObserver(
      ([e]) => {
        onScreen = e.isIntersecting;
        if (onScreen) {
          if (!isMobileDevice()) {
            arm();
          }
        } else if (!onScreen) {
          clearTimeout(armed);
          v.pause();
        }
      },
      { threshold: 0.25 }
    );
    ioWrap.observe(wrap);

    // 2. VSL sits in a two-stroke frame (outer soft pane, inner white frame)
    const hero =
      heroRef.current || (document.getElementById('vsl') as HTMLElement | null);
    const canvas = canvasRef.current;
    const persp =
      perspRef.current ||
      (document.getElementById('vslPersp') as HTMLElement | null);

    const ASPECT_FALLBACK = 1594 / 1022;

    function layout() {
      if (!hero || !wrap || !persp) return;
      const secW = hero.clientWidth;
      const avail = secW;
      const ring = avail < 560 ? 10 : 14;
      const w = avail;
      const iw = w - ring * 2;
      const aspect =
        v.videoWidth && v.videoHeight
          ? v.videoWidth / v.videoHeight
          : ASPECT_FALLBACK;
      const ih = iw / aspect;
      const h = ih + ring * 2;

      wrap.style.width = w + 'px';
      wrap.style.height = h + 'px';
      wrap.style.setProperty('--t', String(ring));
      Object.assign(persp.style, {
        left: ring + 'px',
        top: ring + 'px',
        width: iw + 'px',
        height: ih + 'px',
        perspective: 'none',
      });
      if (canvas) {
        canvas.style.display = 'none';
      }
    }

    layout();
    wrap.classList.add('vsl--static');

    v.addEventListener('loadedmetadata', layout);

    const roHero = new ResizeObserver(layout);
    if (hero) roHero.observe(hero);

    // 3. VSL field edges: the page dissolves into the picture
    const top = topDissolveRef.current;
    const bot = botDissolveRef.current;
    const sec = sectionRef.current;
    let roDissolve: ResizeObserver | null = null;
    if (top && bot && sec) {
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
        paint(top, false);
        paint(bot, true);
      };
      roDissolve = new ResizeObserver(draw);
      roDissolve.observe(sec);
      draw();
    }

    const handleInlineEnded = () => {
      if (isMobileDevice()) {
        handleVideoEnded();
      }
    };
    v.addEventListener('ended', handleInlineEnded);

    const handleInlineAppleFullscreenEnd = () => {
      if (isMobileDevice()) {
        handleVideoEnded();
      }
    };
    (v as any).addEventListener?.('webkitendfullscreen', handleInlineAppleFullscreenEnd);

    return () => {
      v.removeEventListener('ended', handleInlineEnded);
      (v as any).removeEventListener?.('webkitendfullscreen', handleInlineAppleFullscreenEnd);
      v.removeEventListener('loadedmetadata', layout);
      ioWrap.disconnect();
      roHero.disconnect();
      roDissolve?.disconnect();
      gestures.forEach((ev) => window.removeEventListener(ev, gestureHandler));
      v.removeEventListener('error', loadFallback);
    };
  }, []);

  const isPortrait = viewportDims.h >= viewportDims.w;

  const modalStyle: React.CSSProperties = isPortrait
    ? rotationAngle === 90
      ? {
          position: 'fixed',
          top: 0,
          left: 0,
          width: `${viewportDims.h || 844}px`,
          height: `${viewportDims.w || 390}px`,
          transform: 'rotate(90deg) translateY(-100%)',
          transformOrigin: '0 0',
        }
      : {
          position: 'fixed',
          top: 0,
          left: 0,
          width: `${viewportDims.h || 844}px`,
          height: `${viewportDims.w || 390}px`,
          transform: 'rotate(270deg) translateX(-100%)',
          transformOrigin: '0 0',
        }
    : {
        position: 'fixed',
        top: 0,
        left: 0,
        width: `${viewportDims.w || 844}px`,
        height: `${viewportDims.h || 390}px`,
        transform: 'none',
      };

  const modalPortal =
    mounted && isMobileModalOpen && typeof document !== 'undefined'
      ? createPortal(
          <div
            className="fixed top-0 left-0 z-[999999] bg-black overflow-hidden flex items-center justify-center select-none"
            style={modalStyle}
            onClick={resetControlsTimeout}
          >
            {/* Video Element */}
            <video
              ref={modalVideoRef}
              src="/punk-vsl.mp4"
              playsInline
              webkit-playsinline="true"
              preload="auto"
              className="w-full h-full object-contain bg-black cursor-pointer"
              onClick={toggleModalPlay}
              onEnded={handleVideoEnded}
              onTimeUpdate={() => {
                if (modalVideoRef.current) {
                  const ct = modalVideoRef.current.currentTime;
                  const dur = modalVideoRef.current.duration;
                  setCurrentTime(ct);
                  if (dur > 0 && ct >= dur - 0.25) {
                    handleVideoEnded();
                  }
                }
              }}
              onLoadedMetadata={() => {
                if (modalVideoRef.current) {
                  setDuration(modalVideoRef.current.duration);
                }
              }}
              onPlay={() => setIsModalPlaying(true)}
              onPause={() => setIsModalPlaying(false)}
            >
              <source src="/punk-vsl.mp4" type="video/mp4" />
            </video>

            {/* Floating Center Play Icon when paused */}
            {!isModalPlaying && (
              <button
                type="button"
                onClick={toggleModalPlay}
                className="absolute inset-0 m-auto flex h-16 w-16 items-center justify-center rounded-full bg-white/20 backdrop-blur-xl border border-white/40 shadow-2xl text-white active:scale-90 transition-transform pointer-events-auto z-30"
                aria-label="Play video"
              >
                <Play size={28} className="translate-x-0.5 fill-current" />
              </button>
            )}

            {/* Top Header Bar */}
            <div
              className={`absolute top-0 left-0 right-0 p-3 sm:p-4 flex items-center justify-between z-40 bg-gradient-to-b from-black/85 via-black/40 to-transparent transition-opacity duration-300 ${
                showControls ? 'opacity-100 pointer-events-auto' : 'opacity-0 pointer-events-none'
              }`}
            >
              <div className="flex items-center gap-2">
                <span className="h-2 w-2 rounded-full bg-emerald-400 animate-pulse" />
                <span className="text-white text-xs sm:text-sm font-semibold tracking-wide font-sans drop-shadow">
                  Punk AI Demo
                </span>
              </div>

              <div className="flex items-center gap-2">
                {isPortrait && (
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      setRotationAngle((prev) => (prev === 90 ? 270 : 90));
                    }}
                    title="Flip rotation"
                    className="flex h-9 w-9 items-center justify-center rounded-full bg-white/15 hover:bg-white/25 active:scale-95 text-white backdrop-blur-md border border-white/20 transition-all"
                  >
                    <RotateCw size={16} />
                  </button>
                )}

                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    handleCloseModal();
                  }}
                  title="Close video"
                  className="flex h-9 w-9 items-center justify-center rounded-full bg-white/20 hover:bg-white/30 active:scale-95 text-white backdrop-blur-md border border-white/30 transition-all"
                >
                  <X size={18} />
                </button>
              </div>
            </div>

            {/* Bottom Controls Bar */}
            <div
              className={`absolute bottom-0 left-0 right-0 px-4 pt-4 pb-3 sm:pb-4 flex flex-col gap-2 z-40 bg-gradient-to-t from-black/90 via-black/50 to-transparent transition-opacity duration-300 ${
                showControls ? 'opacity-100 pointer-events-auto' : 'opacity-0 pointer-events-none'
              }`}
            >
              {/* Scrubber Range Bar */}
              <div className="w-full flex items-center">
                <input
                  type="range"
                  min={0}
                  max={duration || 100}
                  step={0.1}
                  value={currentTime}
                  onChange={handleSeek}
                  onClick={(e) => e.stopPropagation()}
                  className="w-full h-1.5 bg-white/30 rounded-lg appearance-none cursor-pointer accent-[#2F8BE0] focus:outline-none"
                />
              </div>

              {/* Buttons Row */}
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <button
                    type="button"
                    onClick={toggleModalPlay}
                    className="text-white hover:text-white/80 active:scale-90 transition-transform p-1"
                    aria-label={isModalPlaying ? 'Pause' : 'Play'}
                  >
                    {isModalPlaying ? <Pause size={20} /> : <Play size={20} className="fill-current" />}
                  </button>

                  <button
                    type="button"
                    onClick={toggleModalMute}
                    className="text-white hover:text-white/80 active:scale-90 transition-transform p-1"
                    aria-label={isModalMuted ? 'Unmute' : 'Mute'}
                  >
                    {isModalMuted ? <VolumeX size={20} /> : <Volume2 size={20} />}
                  </button>

                  <span className="text-[11px] sm:text-xs text-white/80 font-mono select-none">
                    {formatTime(currentTime)} / {formatTime(duration)}
                  </span>
                </div>

                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={handleNativeFullscreen}
                    title="Fullscreen"
                    className="text-white hover:text-white/80 active:scale-90 transition-transform p-1"
                    aria-label="Native Fullscreen"
                  >
                    <Maximize2 size={18} />
                  </button>
                </div>
              </div>
            </div>
          </div>,
          document.body
        )
      : null;

  return (
    <section
      className="show reveal relative isolate overflow-x-clip pt-[clamp(56px,6vw,96px)] pb-[clamp(56px,6vw,96px)]"
      aria-label="Find your customers in the real world"
      ref={sectionRef}
    >
      <style>{`
        .show-sky-bg {
          position: absolute;
          inset: 0;
          z-index: -10;
          pointer-events: none;
          background-color: #2F8BE0;
          background-image: url('/vsl-sky.webp');
          background-repeat: no-repeat;
          background-position: center bottom;
          background-size: cover;
          image-rendering: auto;
        }
        .show__dissolve {
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
        .show__dissolve--top { top: -2px; }
        .show__dissolve--bottom { bottom: -2px; }
      `}</style>

      {/* VSL Sky Background */}
      <div className="show-sky-bg" aria-hidden="true" />

      {/* VSL Field Edges: pixel dissolves into the page */}
      <canvas
        ref={topDissolveRef}
        id="showDissolveTop"
        className="show__dissolve show__dissolve--top"
        aria-hidden="true"
      />
      <canvas
        ref={botDissolveRef}
        id="showDissolveBottom"
        className="show__dissolve show__dissolve--bottom"
        aria-hidden="true"
      />

      <div className="wrap mx-auto w-[min(var(--max,1180px),calc(100%-40px))] max-sm:w-[calc(100%-32px)]">
        <div
          ref={heroRef}
          id="vsl"
          className="hero-vsl flex w-full justify-center px-0"
        >
          <div
            ref={vslWrapRef}
            id="vslWrap"
            className="vsl vsl--static relative flex-none outline-none rounded-[28px] max-[560px]:rounded-[20px] bg-white/34 shadow-none isolate-auto backdrop-filter-none"
          >
            <canvas
              ref={canvasRef}
              className="vsl__frame hidden pointer-events-none absolute z-2"
              aria-hidden="true"
            ></canvas>
            <div
              ref={perspRef}
              id="vslPersp"
              className="vsl__persp absolute z-1 rounded-[14px] max-[560px]:rounded-[10px] overflow-hidden bg-white shadow-[0_0_0_1px_rgba(20,60,110,0.18),0_0_0_7px_rgba(255,255,255,0.58),0_0_0_8px_rgba(255,255,255,0.35)]"
            >
              <div
                id="vslMedia"
                className="vsl__media absolute -inset-px origin-center overflow-hidden bg-(--dark) will-change-transform rounded-[14px] max-[560px]:rounded-[10px] [&>video]:block [&>video]:h-full [&>video]:w-full [&>video]:border-0 [&>video]:object-cover"
              >
                <video
                  className="vsl__video absolute inset-0 block h-full w-full border-0 bg-[#F4F3F0] object-cover rounded-[14px] max-[560px]:rounded-[10px]"
                  id="vslVideo"
                  ref={videoRef}
                  src="/punk-vsl.mp4"
                  muted
                  playsInline
                  preload="auto"
                  poster="/vsl-poster.jpg"
                  aria-label="punk demo: describing an audience, confirming the map, building the creative and publishing"
                >
                  <source src="/punk-vsl.mp4" type="video/mp4" />
                </video>

                {/* Mobile Play Button & Blur Overlay */}
                <div
                  onClick={handleOpenMobileModal}
                  className="md:hidden absolute inset-0 z-10 flex flex-col items-center justify-center cursor-pointer transition-all duration-300 bg-black/35 backdrop-blur-[6px]"
                  aria-label="Play demo video in full screen"
                >
                  <div className="relative flex items-center justify-center">
                    {/* Soft animated ambient glow */}
                    <div className="absolute -inset-3 rounded-full bg-white/25 blur-md animate-pulse pointer-events-none" />

                    {/* Circular Glass Play Button */}
                    <button
                      type="button"
                      onClick={handleOpenMobileModal}
                      className="relative flex h-16 w-16 sm:h-20 sm:w-20 items-center justify-center rounded-full bg-white/20 backdrop-blur-xl border border-white/50 shadow-[0_8px_32px_rgba(0,0,0,0.35),0_0_0_1px_rgba(255,255,255,0.4)_inset] text-white transition-all duration-200 active:scale-90 hover:bg-white/30"
                      aria-label="Play demo video"
                    >
                      <Play size={28} className="translate-x-0.5 fill-current text-white drop-shadow-[0_2px_4px_rgba(0,0,0,0.4)]" />
                    </button>
                  </div>
                  <span className="mt-3.5 text-[12px] sm:text-[13px] font-medium tracking-wide text-white drop-shadow-[0_2px_4px_rgba(0,0,0,0.7)] font-sans select-none">
                    Watch Demo
                  </span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Mobile Rotated Fullscreen Modal Portal */}
      {modalPortal}
    </section>
  );
}

export default VSLSection;
