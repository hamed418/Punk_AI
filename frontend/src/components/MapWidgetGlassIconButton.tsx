'use client';

import {
  Popover,
  type PopoverDropdownProps,
  type PopoverProps,
} from '@mantine/core';
import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from 'react';

export const widgetPanelStyle = {
  boxShadow: '0px 2px 3px 0px #0000000F',
};

export const widgetNoiseBackground = `url("data:image/svg+xml,%3Csvg viewBox='0 0 200 200' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='noiseFilter'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.85' numOctaves='3' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23noiseFilter)'/%3E%3C/svg%3E")`;

export interface MapWidgetGlassIconButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  children: ReactNode;
  neonColor?: string;
  glowColor?: string;
  pulse?: boolean;
}

const MapWidgetGlassIconButton = forwardRef<
  HTMLButtonElement,
  MapWidgetGlassIconButtonProps
>(function MapWidgetGlassIconButton(
  {
    children,
    className = '',
    style,
    neonColor,
    glowColor,
    pulse = true,
    ...props
  },
  ref
) {
  const dynamicStyles: Record<string, string> = {};
  if (neonColor) dynamicStyles['--neon-color'] = neonColor;
  if (glowColor) dynamicStyles['--neon-glow'] = glowColor;

  return (
    <button
      ref={ref}
      type="button"
      style={{
        ...widgetPanelStyle,
        backgroundImage: 'none !important',
        backdropFilter: 'blur(75.9000015258789px)',
        background: 'rgba(192, 132, 252, 0.12)',
        ...dynamicStyles,
        ...style,
      }}
      className={`${pulse ? 'neon-pulse-pink' : ''} absolute bottom-2 left-2 z-999 flex h-8 w-8 cursor-pointer items-center justify-center rounded-xl text-white transition-all duration-200 hover:scale-110 active:scale-98 ${className}`}
      {...props}
    >
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 z-0 rounded-[inherit] opacity-15 mix-blend-overlay"
        // style={{ backgroundImage: widgetNoiseBackground }}
      />
      <span className="relative z-10 flex items-center justify-center">
        {children}
      </span>
    </button>
  );
});

export default MapWidgetGlassIconButton;

export function MapWidgetInfoPopover({
  children,
  classNames,
  styles,
  position = 'right-end',
  offset = 4,
  withinPortal = false,
  zIndex = 999,
  middlewares = { flip: false, shift: false },
  ...props
}: PopoverProps) {
  return (
    <Popover
      position={position}
      withArrow
      shadow="md"
      offset={offset}
      withinPortal={withinPortal}
      zIndex={zIndex}
      middlewares={middlewares}
      {...props}
      classNames={{
        dropdown: 'border-transparent!',
        ...classNames,
      }}
      styles={{
        ...styles,
        dropdown: {
          backgroundColor: 'rgba(0, 0, 0, 0.8)',
          border: '1px solid rgba(255, 255, 255, 0.1)',
          ...widgetPanelStyle,
          ...(styles && typeof styles === 'object'
            ? styles.dropdown
            : undefined),
        },
        arrow: {
          arrow: {
            background: 'rgba(0, 0, 0, 0.8)',
            border: '1px solid rgba(255, 255, 255, 0.1)',
            backdropFilter: 'blur(75.9px)',
          },
          ...(styles && typeof styles === 'object' ? styles.arrow : undefined),
        },
      }}
    >
      {children}
    </Popover>
  );
}

interface MapWidgetGlassPopoverDropdownProps extends PopoverDropdownProps {
  children: ReactNode;
}

export function MapWidgetGlassPopoverDropdown({
  children,
  className = '',
  maw = 300,
  style,
  ...props
}: MapWidgetGlassPopoverDropdownProps) {
  return (
    <Popover.Dropdown
      maw={maw}
      {...props}
      className={`light:shadow-widget! light:border-white/20! light:border! relative z-999! rounded-3xl bg-[#FFFFFF03]! p-3 ${className}`}
      style={{
        ...widgetPanelStyle,
        background: 'rgba(255, 255, 255, 0.01)',
        backdropFilter: 'blur(75.9000015258789px)',
        border: 'none !important',
        boxShadow:
          '0px 8px 24px 0px #00000080, 0px -1px 0px 0px #00000066 inset,0px 1px 0px 0px #FFFFFF1F inset',
        ...style,
      }}
    >
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 z-0 opacity-15 mix-blend-overlay"
        // style={{ backgroundImage: widgetNoiseBackground }}
      />
      <div className="relative z-10">{children}</div>
    </Popover.Dropdown>
  );
}
