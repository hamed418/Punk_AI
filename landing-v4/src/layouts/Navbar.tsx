'use client';

import React, { useEffect, useMemo, useRef, useState } from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { trackEvent } from '@/lib/analytics';
import { PunkLogo } from '@/components/PunkLogo';
import { AnimatePresence, motion, useReducedMotion } from 'motion/react';
import { smoothScrollToSection } from '@/lib/scroll';

const NAV_CTA_BTN_CLASSES =
  "pk-btn-nav pk-btn--primary relative isolate inline-flex w-auto items-center justify-center text-center h-[38px] md:h-10 px-3.5 md:px-5 rounded-[6px] font-body text-[13px] md:text-[14px] font-medium leading-none tracking-[-0.005em] text-[#F4F4F1] no-underline whitespace-nowrap cursor-pointer select-none outline-none border-0 [-webkit-tap-highlight-color:transparent] bg-gradient-to-b from-[#303030] via-[#1E1E1E_55%] to-[#161616] shadow-[inset_0_1px_0_#737373,inset_0_-1px_0_#0B0B0B,0_0_0_1px_#4A4A48,0_3px_0_#050505,0_3px_0_1px_#3A3A38,0_5px_6px_rgba(0,0,0,0.28),0_11px_18px_rgba(0,0,0,0.18)] translate-y-0 transition-[transform,box-shadow] duration-220 ease-[cubic-bezier(0.2,0.8,0.2,1)] hover:translate-y-[1px] hover:shadow-[inset_0_1px_0_#8C8C8C,inset_0_-1px_0_#101010,0_0_0_1px_#5A5A58,0_2px_0_#050505,0_2px_0_1px_#3A3A38,0_3px_4px_rgba(0,0,0,0.28),0_5px_10px_rgba(0,0,0,0.14)] active:translate-y-[2.5px] active:shadow-[inset_0_1px_0_#6A6A6A,inset_0_-1px_0_#101010,0_0_0_1px_#5A5A58,0_0_0_#050505,0_0_0_1px_#3A3A38,0_1px_2px_rgba(0,0,0,0.3)] focus-visible:outline-2 focus-visible:outline-(--punk) focus-visible:outline-offset-4 before:content-[''] before:absolute before:inset-0 before:rounded-[inherit] before:pointer-events-none before:z-0 before:bg-gradient-to-b before:from-[#3E3E3E] before:via-[#2B2B2B_55%] before:to-[#212121] before:shadow-[inset_0_1px_0_#8C8C8C,inset_0_-1px_0_#101010] before:opacity-0 before:transition-opacity before:duration-220 before:ease-out hover:before:opacity-100 focus-visible:before:opacity-100 active:before:opacity-100";

export interface NavLinkItem {
  label: string;
  href: string;
}

export interface NavbarProps {
  homeHref?: string;
  showNavLinks?: boolean;
  navLinks?: NavLinkItem[];
}

const DEFAULT_NAV_LINKS: NavLinkItem[] = [
  { label: 'How it works', href: '#how-it-works' },
  { label: 'Technology', href: '#technology' },
  { label: 'Pricing', href: '#pricing' },
  { label: 'FAQ', href: '#faq' },
];

export function Navbar({ homeHref, showNavLinks, navLinks }: NavbarProps = {}) {
  const pathname = usePathname();
  const logoHref = homeHref ?? (pathname === '/' ? '#top' : '/');
  const links = useMemo(
    () => navLinks ?? (pathname === '/' ? DEFAULT_NAV_LINKS : []),
    [navLinks, pathname]
  );
  const displayNavLinks = showNavLinks ?? links.length > 0;
  const linksRef = useRef(links);

  useEffect(() => {
    linksRef.current = links;
  }, [links]);

  const [isOpen, setIsOpen] = useState(false);
  const [isStuck, setIsStuck] = useState(false);
  const [isHidden, setIsHidden] = useState(false);
  const [isPast400, setIsPast400] = useState(false);
  const shouldReduceMotion = useReducedMotion();
  const [activeId, setActiveId] = useState<string>('');
  const navRef = useRef<HTMLElement>(null);
  const lastYRef = useRef(0);
  const isOpenRef = useRef(isOpen);
  const activeIdRef = useRef('');

  useEffect(() => {
    isOpenRef.current = isOpen;
    const nav = navRef.current;
    if (nav) {
      if (isOpen) {
        nav.classList.remove('is-stuck');
        nav.classList.remove('is-hidden');
      } else {
        nav.classList.toggle('is-stuck', window.scrollY > 8);
      }
    }
  }, [isOpen]);

  useEffect(() => {
    const nav = navRef.current;
    if (!nav) return;

    nav.querySelectorAll('canvas.pixfill').forEach((c) => c.remove());
    nav
      .querySelectorAll('.has-pixfill')
      .forEach((el) => el.classList.remove('has-pixfill'));

    const sectionIds = ['how-it-works', 'technology', 'pricing', 'faq'];

    const updateActiveSection = (y: number) => {
      if (!linksRef.current.some((l) => l.href.startsWith('#'))) return;

      // 1. Near the top of the page (Hero, Prompt, VSL)
      if (y < 200) {
        if (activeIdRef.current !== '') {
          activeIdRef.current = '';
          setActiveId('');
          const links =
            nav.querySelectorAll<HTMLAnchorElement>('.nav__links a');
          links.forEach((a) => a.classList.remove('is-current'));
        }
        return;
      }

      // 2. Check if at the bottom of the page
      const isAtBottom =
        window.innerHeight + y >= document.documentElement.scrollHeight - 60;
      if (isAtBottom) {
        if (activeIdRef.current !== 'faq') {
          activeIdRef.current = 'faq';
          setActiveId('faq');
          const links =
            nav.querySelectorAll<HTMLAnchorElement>('.nav__links a');
          links.forEach((a) => {
            a.classList.toggle('is-current', a.getAttribute('href') === '#faq');
          });
        }
        return;
      }

      // 3. Reverse scan to find the current active section
      let current = '';
      for (let i = sectionIds.length - 1; i >= 0; i--) {
        const id = sectionIds[i];
        const el = document.getElementById(id);
        if (el) {
          const top = el.offsetTop - 180;
          if (y >= top) {
            current = id;
            break;
          }
        }
      }

      if (current && current !== activeIdRef.current) {
        activeIdRef.current = current;
        setActiveId(current);
        const links = nav.querySelectorAll<HTMLAnchorElement>('.nav__links a');
        links.forEach((a) => {
          a.classList.toggle(
            'is-current',
            a.getAttribute('href') === `#${current}`
          );
        });
      } else if (!current && activeIdRef.current !== '') {
        activeIdRef.current = '';
        setActiveId('');
        const links = nav.querySelectorAll<HTMLAnchorElement>('.nav__links a');
        links.forEach((a) => a.classList.remove('is-current'));
      }
    };

    let ticking = false;
    const onScroll = () => {
      const y = window.scrollY;
      const stuck = y > 8 && !isOpenRef.current;
      setIsStuck(stuck);
      nav.classList.toggle('is-stuck', stuck);

      setIsPast400(y > 323);

      if (Math.abs(y - lastYRef.current) > 6) {
        const hidden = y > lastYRef.current && y > 500 && !isOpenRef.current;
        setIsHidden(hidden);
        nav.classList.toggle('is-hidden', hidden);
        lastYRef.current = y;
      }

      updateActiveSection(y);
      ticking = false;
    };

    onScroll();

    const handleScroll = () => {
      if (!ticking) {
        ticking = true;
        requestAnimationFrame(onScroll);
      }
    };

    const handleResize = () => {
      if (window.innerWidth > 860) {
        setIsOpen(false);
      }
      onScroll();
    };

    window.addEventListener('scroll', handleScroll, { passive: true });
    window.addEventListener('resize', handleResize, { passive: true });

    return () => {
      window.removeEventListener('scroll', handleScroll);
      window.removeEventListener('resize', handleResize);
    };
  }, []);

  const toggleMenu = () => {
    setIsOpen((prev) => !prev);
  };

  const closeMenu = () => {
    setIsOpen(false);
  };

  const handleCtaClick = () => {
    closeMenu();
    trackEvent('cta_clicked', {
      cta_name: 'navbar_join_beta',
      cta_location: 'navbar',
      button_text: 'Join Beta',
    });
  };

  const frontendUrl =
    process.env.NEXT_PUBLIC_FRONTEND_URL || 'https://chat.usepunk.ai';
  const joinBetaUrl = `${frontendUrl.replace(/\/+$/, '')}`;

  const handleNavLinkClick = (
    label: string,
    href: string,
    navType: 'header_desktop' | 'header_mobile' = 'header_desktop',
    e?: React.MouseEvent<HTMLAnchorElement>
  ) => {
    closeMenu();
    if (href.startsWith('#')) {
      if (e) e.preventDefault();
      const id = href.slice(1);
      activeIdRef.current = id;
      setActiveId(id);
      const nav = navRef.current;
      if (nav) {
        const anchorLinks = Array.from(
          nav.querySelectorAll<HTMLAnchorElement>('.nav__links a')
        );
        anchorLinks.forEach((a) =>
          a.classList.toggle('is-current', a.getAttribute('href') === href)
        );
      }
      smoothScrollToSection(href);
    }
    trackEvent('nav_link_clicked', {
      link_label: label,
      destination_href: href,
      nav_type: navType,
    });
  };

  return (
    <header
      className={`nav fixed top-0 right-0 left-0 z-50 border-b transition-[transform,background-color,border-color,box-shadow] duration-350 ease-[cubic-bezier(0.2,0.8,0.2,1)] [body.ea-open_&]:pr-(--sbw,0px) ${
        isOpen
          ? 'is-open will-change-auto max-lg:translate-y-0! max-lg:transform-none! max-lg:will-change-auto!'
          : isHidden
            ? 'is-hidden -translate-y-full will-change-transform'
            : 'translate-y-0 will-change-transform'
      } ${isHidden ? '[&.is-hidden]:-translate-y-full' : ''} ${
        isOpen
          ? 'max-lg:shadow-pk! max-lg:[&.is-open]:shadow-pk! max-lg:border-b! max-lg:border-b-black/6! max-lg:bg-white/75! max-lg:backdrop-blur-3xl! max-lg:backdrop-saturate-[1.6]! max-lg:[-webkit-backdrop-filter:blur(64px)_saturate(1.6)]! max-lg:[&.is-open]:transform-none! max-lg:[&.is-open]:border-b! max-lg:[&.is-open]:border-b-black/6! max-lg:[&.is-open]:bg-white/75! max-lg:[&.is-open]:backdrop-blur-3xl! max-lg:[&.is-open]:backdrop-saturate-[1.6]! max-lg:[&.is-open]:will-change-auto! max-lg:[&.is-open]:[-webkit-backdrop-filter:blur(64px)_saturate(1.6)]!'
          : isStuck
            ? 'is-stuck border-b-[rgba(255,255,255,0.45)] bg-[rgba(244,243,240,0.55)] shadow-[0_4px_24px_rgba(20,20,20,0.05)] backdrop-blur-[18px] backdrop-saturate-[1.4] [-webkit-backdrop-filter:blur(18px)_saturate(1.4)] [&.is-stuck]:border-b-[rgba(255,255,255,0.45)] [&.is-stuck]:bg-[rgba(244,243,240,0.55)] [&.is-stuck]:shadow-[0_4px_24px_rgba(20,20,20,0.05)] [&.is-stuck]:backdrop-blur-[18px] [&.is-stuck]:backdrop-saturate-[1.4] [&.is-stuck]:[-webkit-backdrop-filter:blur(18px)_saturate(1.4)]'
            : 'border-b-transparent bg-transparent shadow-none [&.is-stuck]:border-b-[rgba(255,255,255,0.45)] [&.is-stuck]:bg-[rgba(244,243,240,0.55)] [&.is-stuck]:shadow-[0_4px_24px_rgba(20,20,20,0.05)] [&.is-stuck]:backdrop-blur-[18px] [&.is-stuck]:backdrop-saturate-[1.4] [&.is-stuck]:[-webkit-backdrop-filter:blur(18px)_saturate(1.4)]'
      }`}
      style={{
        transition:
          'transform 0.35s cubic-bezier(0.2, 0.8, 0.2, 1), background 0.25s ease, border-color 0.25s ease, box-shadow 0.25s ease',
      }}
      id="nav"
      ref={navRef}
    >
      <div className="nav__inner flex w-full flex-col px-5 lg:mx-auto lg:max-w-295 lg:flex-row lg:items-center lg:justify-between lg:px-6">
        <div className="flex h-15 w-full items-center justify-between lg:w-auto lg:justify-start">
          {logoHref.startsWith('#') ? (
            <a
              className="nav__logo [&>svg]:block [&>svg]:h-7 [&>svg]:w-auto"
              href={logoHref}
              aria-label="punk home"
              onClick={(e) => {
                e.preventDefault();
                closeMenu();
                smoothScrollToSection(logoHref);
              }}
            >
              <PunkLogo />
            </a>
          ) : (
            <Link
              className="nav__logo [&>svg]:block [&>svg]:h-7 [&>svg]:w-auto"
              href={logoHref}
              aria-label="punk home"
              onClick={closeMenu}
            >
              <PunkLogo />
            </Link>
          )}
          <div className="flex items-center lg:hidden">
            <AnimatePresence initial={false}>
              {isPast400 && (
                <motion.div
                  initial={
                    shouldReduceMotion
                      ? { opacity: 0 }
                      : {
                          width: 0,
                          opacity: 0,
                          scale: 0.95,
                          marginRight: 0,
                        }
                  }
                  animate={
                    shouldReduceMotion
                      ? { opacity: 1 }
                      : {
                          width: 'auto',
                          opacity: 1,
                          scale: 1,
                          marginRight: displayNavLinks ? 8 : 0,
                        }
                  }
                  exit={
                    shouldReduceMotion
                      ? { opacity: 0 }
                      : {
                          width: 0,
                          opacity: 0,
                          scale: 0.95,
                          marginRight: 0,
                        }
                  }
                  transition={{
                    width: { duration: 0.28, ease: [0.16, 1, 0.3, 1] },
                    marginRight: { duration: 0.6, ease: [0.16, 1, 0.3, 1] },
                    opacity: { duration: 0.2, ease: 'easeOut' },
                    scale: { duration: 0.25, ease: [0.16, 1, 0.3, 1] },
                  }}
                  className="-my-2 py-2"
                >
                  <span className="nav__cta inline-flex px-3.5 shrink-0 items-center">
                    <a
                      href={joinBetaUrl}
                      target="_blank"
                      rel="noopener noreferrer"
                      data-ea=""
                      onClick={handleCtaClick}
                      className={NAV_CTA_BTN_CLASSES}
                    >
                      <span className="pk-btn__label relative z-1 flex w-full items-center justify-center text-center">
                        <span className="block w-full text-center">
                          Join beta
                        </span>
                      </span>
                    </a>
                  </span>
                </motion.div>
              )}
            </AnimatePresence>
            {displayNavLinks && (
              <button
                className="nav__toggle cursor-pointer border-0 bg-transparent p-2"
                aria-label="Menu"
                aria-expanded={isOpen}
                onClick={toggleMenu}
              >
                <span
                  className={`my-1.25 block h-0.5 w-5.5 bg-(--ink) transition-all duration-200 ease-out ${
                    isOpen
                      ? 'translate-y-1.75 rotate-45'
                      : 'translate-y-0 rotate-0'
                  }`}
                ></span>
                <span
                  className={`my-1.25 block h-0.5 w-5.5 bg-(--ink) transition-all duration-200 ease-out ${
                    isOpen ? 'opacity-0' : 'opacity-100'
                  }`}
                ></span>
                <span
                  className={`my-1.25 block h-0.5 w-5.5 bg-(--ink) transition-all duration-200 ease-out ${
                    isOpen
                      ? '-translate-y-1.75 -rotate-45'
                      : 'translate-y-0 rotate-0'
                  }`}
                ></span>
              </button>
            )}
          </div>
        </div>

        {/* Desktop links & CTA */}
        <div className="hidden items-center lg:flex">
          {displayNavLinks && (
            <div className="nav__menu flex items-center">
              <nav className="nav__links flex gap-9" aria-label="Primary">
                {links.map((link) => {
                  const isHash = link.href.startsWith('#');
                  const isCurrent = isHash
                    ? activeId === link.href.slice(1)
                    : pathname === link.href ||
                      pathname?.startsWith(link.href + '/');

                  const linkClasses = `text-[14px] font-medium text-(--ink) relative py-1.5 after:content-[''] after:absolute after:left-0 after:bottom-0 after:h-0.5 after:bg-(--punk) after:transition-[right] after:duration-200 after:ease hover:after:right-0 ${
                    isCurrent ? 'is-current after:right-0' : 'after:right-full'
                  }`;

                  return isHash ? (
                    <a
                      key={link.href}
                      href={link.href}
                      className={linkClasses}
                      onClick={(e) =>
                        handleNavLinkClick(
                          link.label,
                          link.href,
                          'header_desktop',
                          e
                        )
                      }
                    >
                      {link.label}
                    </a>
                  ) : (
                    <Link
                      key={link.href}
                      href={link.href}
                      className={linkClasses}
                      onClick={() =>
                        handleNavLinkClick(
                          link.label,
                          link.href,
                          'header_desktop'
                        )
                      }
                    >
                      {link.label}
                    </Link>
                  );
                })}
              </nav>
            </div>
          )}

          <AnimatePresence initial={false}>
            {isPast400 && (
              <motion.div
                initial={
                  shouldReduceMotion
                    ? { opacity: 0 }
                    : {
                        width: 0,
                        opacity: 0,
                        scale: 0.95,
                        marginLeft: 0,
                      }
                }
                animate={
                  shouldReduceMotion
                    ? { opacity: 1 }
                    : {
                        width: 'auto',
                        opacity: 1,
                        scale: 1,
                        marginLeft: displayNavLinks ? 22 : 0,
                      }
                }
                exit={
                  shouldReduceMotion
                    ? { opacity: 0 }
                    : {
                        width: 0,
                        opacity: 0,
                        scale: 0.95,
                        marginLeft: 0,
                      }
                }
                transition={{
                  width: { duration: 0.28, ease: [0.16, 1, 0.3, 1] },
                  marginLeft: { duration: 0.28, ease: [0.16, 1, 0.3, 1] },
                  opacity: { duration: 0.2, ease: 'easeOut' },
                  scale: { duration: 0.25, ease: [0.16, 1, 0.3, 1] },
                }}
                className="-my-2 py-2"
              >
                <span className="nav__cta inline-flex px-3.5 shrink-0 items-center">
                  <a
                    href={joinBetaUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                    data-ea=""
                    onClick={handleCtaClick}
                    className={NAV_CTA_BTN_CLASSES}
                  >
                    <span className="pk-btn__label relative z-1 flex w-full items-center justify-center text-center">
                      <span className="block w-full text-center">
                        Join beta
                      </span>
                    </span>
                  </a>
                </span>
              </motion.div>
            )}
          </AnimatePresence>
        </div>

        {/* Mobile dropdown */}
        {displayNavLinks && (
          <div
            className={`nav__menu lg:hidden ${
              isOpen
                ? 'flex w-full flex-col gap-4.5 border-t border-black/6 pt-3 pb-6'
                : 'hidden'
            }`}
          >
            <nav
              className="nav__links flex flex-col gap-3.5"
              aria-label="Primary Mobile"
            >
              {links.map((link) => {
                const isHash = link.href.startsWith('#');
                const isCurrent = isHash
                  ? activeId === link.href.slice(1)
                  : pathname === link.href ||
                    pathname?.startsWith(link.href + '/');

                const linkClasses = `text-[14px] font-medium text-(--ink) relative py-1.5 after:content-[''] after:absolute after:left-0 after:bottom-0 after:h-0.5 after:bg-(--punk) after:transition-[right] after:duration-200 after:ease hover:after:right-0 ${
                  isCurrent ? 'is-current after:right-0' : 'after:right-full'
                }`;

                return isHash ? (
                  <a
                    key={link.href}
                    href={link.href}
                    className={linkClasses}
                    onClick={(e) =>
                      handleNavLinkClick(
                        link.label,
                        link.href,
                        'header_mobile',
                        e
                      )
                    }
                  >
                    {link.label}
                  </a>
                ) : (
                  <Link
                    key={link.href}
                    href={link.href}
                    className={linkClasses}
                    onClick={() =>
                      handleNavLinkClick(link.label, link.href, 'header_mobile')
                    }
                  >
                    {link.label}
                  </Link>
                );
              })}
            </nav>
          </div>
        )}
      </div>
    </header>
  );
}

export default Navbar;
