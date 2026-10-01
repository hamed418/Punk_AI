import React from 'react';

export interface POILogoProps {
  width?: number | string;
  height?: number | string;
  className?: string;
  color?: string;
  fillColor?: string;
  style?: React.CSSProperties;
}

export default function POILogo({
  width = 18,
  height = 26,
  className = '',
  color = '#ff2d78',
  fillColor = 'rgba(255, 45, 120, 0.25)',
  style,
}: POILogoProps) {
  return (
    <svg
      width={width}
      height={height}
      viewBox="0 0 160 250"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className={className}
      style={style}
    >
      {/* Phone outline */}
      <rect
        x="8"
        y="8"
        width="144"
        height="234"
        rx="30"
        stroke={color}
        strokeWidth="16"
        fill={fillColor}
      />

      {/* Top notch / speaker bar */}
      <rect
        x="54"
        y="20"
        width="52"
        height="12"
        rx="6"
        fill={color}
      />

      {/* Bottom home indicator bar */}
      <rect
        x="54"
        y="218"
        width="52"
        height="10"
        rx="5"
        fill={color}
      />
    </svg>
  );
}

export { POILogo as PhoneCaseLogo };