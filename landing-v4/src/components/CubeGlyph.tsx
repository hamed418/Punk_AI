export function CubeSvgDefs() {
  return (
    <svg
      width="0"
      height="0"
      className="absolute"
      style={{ position: 'absolute' }}
      aria-hidden="true"
    >
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
  );
}

export function CubeGlyph({ className = '' }: { className?: string }) {
  return (
    <svg
      className={`cube inline-block h-5 w-4.5 flex-none align-middle ${className}`}
      aria-hidden="true"
    >
      <use href="#cube" />
    </svg>
  );
}
