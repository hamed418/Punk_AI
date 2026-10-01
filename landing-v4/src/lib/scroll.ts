/**
 * Smoothly scrolls to a page section with an offset so the section's
 * header text stops 10px below the fixed navbar (making the header text fully visible).
 */
export function smoothScrollToSection(href: string) {
  if (typeof window === 'undefined') return;
  if (!href.startsWith('#')) return;

  if (href === '#top') {
    window.scrollTo({ top: 0, behavior: 'smooth' });
    return;
  }

  const id = href.slice(1);
  const element = document.getElementById(id);
  if (!element) {
    // If element is not on the current page (e.g. from legal pages), navigate home with hash
    // eslint-disable-next-line @next/next/no-location-assign-relative-destination
    window.location.href = `/${href}`;
    return;
  }

  const nav = document.getElementById('nav');
  // Always use the primary fixed navbar bar height (excluding any open mobile dropdown menu)
  const navBarRow = nav?.querySelector<HTMLElement>('.nav__inner > div');
  const navHeight =
    navBarRow?.offsetHeight ||
    (nav && !nav.classList.contains('is-open') ? nav.offsetHeight : 60) ||
    60;
  const isSmallDevice = window.innerWidth < 1024;
  const currentY = window.scrollY;
  const elementTop = element.getBoundingClientRect().top + currentY;
  const isScrollingDown = elementTop > currentY;

  // On small devices, scrolling down past 500px auto-hides the navbar.
  // Scrolling up reveals the navbar.
  const willNavbarBeHidden =
    isSmallDevice &&
    (isScrollingDown
      ? elementTop > 500
      : Boolean(nav?.classList.contains('is-hidden') && Math.abs(elementTop - currentY) < 10));

  // When the navbar is not shown on small devices, reduce the gap to 20px.
  // Otherwise, provide space for the fixed navbar (navHeight + 10px).
  const offset = willNavbarBeHidden ? 20 : navHeight + 10;

  window.scrollTo({
    top: Math.max(0, elementTop - offset),
    behavior: 'smooth',
  });
}
