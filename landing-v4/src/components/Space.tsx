import React from 'react';

export type ResponsiveHeight = {
  base: number;
  sm?: number;
  md?: number;
  lg?: number;
  xl?: number;
};

export interface SpaceProps {
  height: number | ResponsiveHeight;
  className?: string;
}

const Space = ({ height, className = '' }: SpaceProps) => {
  if (typeof height === 'number') {
    return (
      <div
        className={className}
        style={{ height: `${height}px` }}
        aria-hidden="true"
      />
    );
  }

  const base = height.base;
  const sm = height.sm ?? base;
  const md = height.md ?? sm;
  const lg = height.lg ?? md;
  const xl = height.xl ?? lg;

  return (
    <div
      className={`h-(--space-base) sm:h-(--space-sm) md:h-(--space-md) lg:h-(--space-lg) xl:h-(--space-xl) ${className}`.trim()}
      style={
        {
          '--space-base': `${base}px`,
          '--space-sm': `${sm}px`,
          '--space-md': `${md}px`,
          '--space-lg': `${lg}px`,
          '--space-xl': `${xl}px`,
        } as React.CSSProperties
      }
      aria-hidden="true"
    />
  );
};

export default Space;
