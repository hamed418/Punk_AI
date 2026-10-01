import { cn } from '@/lib/utils';
import { Box } from '@mantine/core';

const PunkSymbolsLogo = ({
  className,
  hearDarkFill = '#ce1c66',
  hearLightFill = '#f54397',
  hearStripesFill = 'transparent',
  faceBodyFill = '#ee9b59',
  bodyDarkFill = '#733016',
  bodyLightFill = '#843818',
  bubbleState = 'idle',
  isFlipped = false,
  isAnimating = false,
}: {
  className?: string;
  hearDarkFill?: string;
  hearLightFill?: string;
  hearStripesFill?: string;
  faceBodyFill?: string;
  bodyDarkFill?: string;
  bodyLightFill?: string;
  bubbleState?: 'idle' | 'star' | 'whiteQuestionMark' | 'heart' | 'lightning';
  isFlipped?: boolean;
  isAnimating?: boolean;
} = {}) => {
  const shouldAnimate = isAnimating ?? bubbleState !== 'idle';

  return (
    <Box
      className={cn(
        'relative -ml-6 flex size-16 items-center justify-center rounded-full',
        className
      )}
      style={{
        border: '1px solid',
        borderImageSource:
          'linear-gradient(136.45deg, rgba(255, 255, 255, 0.68) 2.69%, rgba(255, 255, 255, 0) 12.32%, rgba(255, 255, 255, 0.08) 86.05%, rgba(255, 255, 255, 0.4) 99.28%)',
        boxShadow:
          '0px 2px 2px 0px #FFFFFF40 inset, 1px -1px 2px 0px #FFFFFF1C inset',
        backdropFilter: 'blur(8px)',
        background: '#4B4B4B01',
      }}
    >
      <svg
        id="Layer_1"
        xmlns="http://www.w3.org/2000/svg"
        version="1.1"
        viewBox="0 0 1200 1019.34"
        className={
          'absolute top-1/2 left-1/2 aspect-square w-20 translate-x-[-32%] translate-y-[-62%] bg-transparent'
        }
        aria-hidden="true"
      >
        <defs>
          <style>{`
          .punk-symbols-tail {
            transform-origin: 318px 840px;
            animation: wagTail 0.5s ease-in-out infinite;
          }

          .punk-symbols-head {
            transform-origin: 440px 700px;
            animation: bobHead 0.5s ease-in-out infinite;
          }

          .loading-dot-1 {
            animation: appearDot1 2.5s ease-in-out infinite;
          }

          .loading-dot-2 {
            animation: appearDot2 2.5s ease-in-out infinite;
          }

          .loading-dot-3 {
            animation: appearDot3 2.5s ease-in-out infinite;
          }

          @keyframes wagTail {
            0%, 100% {
              transform: rotate(0deg);
            }
            50% {
              transform: rotate(-12deg);
            }
          }

          @keyframes bobHead {
            0%, 100% {
              transform: rotate(0deg) translateY(0px);
            }
            33% {
              transform: rotate(2.5deg) translateY(-5px);
            }
            66% {
              transform: rotate(-2.5deg) translateY(3px);
            }
          }

          @keyframes appearDot1 {
            0%, 15% {
              opacity: 0;
              transform: translateY(10px);
            }
            25% {
              opacity: 1;
              transform: translateY(-5px);
            }
            30%, 85% {
              opacity: 1;
              transform: translateY(0);
            }
            95%, 100% {
              opacity: 0;
              transform: translateY(0);
            }
          }

          @keyframes appearDot2 {
            0%, 40% {
              opacity: 0;
              transform: translateY(10px);
            }
            50% {
              opacity: 1;
              transform: translateY(-5px);
            }
            55%, 85% {
              opacity: 1;
              transform: translateY(0);
            }
            95%, 100% {
              opacity: 0;
              transform: translateY(0);
            }
          }

          @keyframes appearDot3 {
            0%, 65% {
              opacity: 0;
              transform: translateY(10px);
            }
            75% {
              opacity: 1;
              transform: translateY(-5px);
            }
            80%, 85% {
              opacity: 1;
              transform: translateY(0);
            }
            95%, 100% {
              opacity: 0;
              transform: translateY(0);
            }
          }
        `}</style>
        </defs>

        {bubbleState === 'heart' && (
          <g name="heart" transform="translate(180, 20) scale(4.5)">
            <path
              d="M12 21.35l-1.45-1.32C5.4 15.36 2 12.28 2 8.5 2 5.42 4.42 3 7.5 3c1.74 0 3.41.81 4.5 2.09C13.09 3.81 14.76 3 16.5 3 19.58 3 22 5.42 22 8.5c0 3.78-3.4 6.86-8.55 11.54L12 21.35z"
              fill="#ff4b4b"
              transform="scale(3.5)"
            />
          </g>
        )}

        {bubbleState === 'lightning' && (
          <g name="lightning" transform="translate(180, 20) scale(4.5)">
            <path
              d="M11 21h-1l1-7H7.5c-.58 0-.57-.32-.38-.66.19-.34.05-.08.16-.28L11.5 2h1l-1 7h3.5c.49 0 .56.33.47.51l-.07.15C12.96 17.55 11 21 11 21z"
              fill="#facc15"
              transform="scale(3.5)"
            />
          </g>
        )}

        {bubbleState === 'star' && (
          <g name="star" transform="translate(-338, -359) scale(5)">
            <path
              d="M124.646 124.918H118.994V130.57H124.646V124.918Z"
              fill="black"
            />
            <path
              d="M118.995 124.918H113.326V130.57H118.995V124.918Z"
              fill="black"
            />
            <path
              d="M113.328 130.57H107.66V136.204H113.328V130.57Z"
              fill="black"
            />
            <path
              d="M113.328 124.918H107.66V130.57H113.328V124.918Z"
              fill="#F7EDE6"
            />
            <path
              d="M113.328 119.285H107.66V124.918H113.328V119.285Z"
              fill="black"
            />
            <path
              d="M107.659 141.855H101.99V147.489H107.659V141.855Z"
              fill="black"
            />
            <path
              d="M107.659 136.203H101.99V141.855H107.659V136.203Z"
              fill="black"
            />
            <path
              d="M107.659 130.57H101.99V136.204H107.659V130.57Z"
              fill="#F7EDE6"
            />
            <path
              d="M107.659 124.918H101.99V130.57H107.659V124.918Z"
              fill="#F7EDE6"
            />
            <path
              d="M107.659 119.285H101.99V124.918H107.659V119.285Z"
              fill="#F7EDE6"
            />
            <path
              d="M107.659 113.633H101.99V119.285H107.659V113.633Z"
              fill="black"
            />
            <path d="M107.659 108H101.99V113.633H107.659V108Z" fill="black" />
            <path
              d="M101.99 130.57H96.3379V136.204H101.99V130.57Z"
              fill="black"
            />
            <path
              d="M101.99 124.918H96.3379V130.57H101.99V124.918Z"
              fill="#F7EDE6"
            />
            <path
              d="M101.99 119.285H96.3379V124.918H101.99V119.285Z"
              fill="black"
            />
            <path
              d="M96.3383 124.918H90.6699V130.57H96.3383V124.918Z"
              fill="black"
            />
            <path
              d="M90.6684 124.918H85V130.57H90.6684V124.918Z"
              fill="black"
            />
          </g>
        )}

        {bubbleState === 'whiteQuestionMark' && (
          <g
            name="whiteQuestionMark"
            transform="translate(-188, -159) scale(4)"
          >
            <g
              style={{
                transform: isFlipped ? 'scale(-1, 1)' : 'none',
                transformOrigin: '107px 122px',
              }}
            >
              <path
                d="M110.772 97H103.515H96.2578V104.257H103.515H110.772H118.03V97H110.772Z"
                className="fill-primary-text"
              />
              <path
                d="M118.029 111.514V118.771H125.286V111.514V104.257H118.029V111.514Z"
                className="fill-primary-text"
              />
              <path
                d="M96.257 104.257H89V111.514H96.257V104.257Z"
                className="fill-primary-text"
              />
              <path
                d="M118.027 118.771H110.77V126.028H118.027V118.771Z"
                className="fill-primary-text"
              />
              <path
                d="M110.771 126.028H103.514V133.285H110.771V126.028Z"
                className="fill-primary-text"
              />
              <path
                d="M110.771 140.542H103.514V147.799H110.771V140.542Z"
                className="fill-primary-text"
              />
            </g>
          </g>
        )}

        <polygon
          fill={bodyDarkFill}
          points="614.32 891.99 614.32 752.16 577.78 752.16 577.78 568.44 530.75 532.33 523.94 518.87 433.87 543.56 428.79 534.94 363.83 553.21 363.83 567.42 320.18 579.6 354.88 697.28 301.92 715.62 301.92 791.24 262.33 791.24 262.33 824.74 262.36 857.73 262.36 927.27 331.79 927.27 331.79 855.19 370.43 855.19 370.43 927.27 420.8 927.27 420.8 892.08 448.12 891.99 448.12 927.27 510.92 927.27 510.92 927.26 528.15 927.26 528.15 891.99 509.18 891.99 509.18 871.08 556.71 871.08 556.71 927.27 614.32 927.27 614.32 927.26 629.77 927.26 629.77 891.99 614.32 891.99"
        />
        <polygon
          name="punkTail"
          className={shouldAnimate ? 'punk-symbols-tail' : ''}
          fill={bodyLightFill}
          points="141.05 824.66 141.05 751.07 178.62 751.07 178.62 715.03 108.58 715.03 108.58 857.64 318.64 857.64 318.64 824.66 141.05 824.66"
        />
        <g name="punkHead" className={shouldAnimate ? 'punk-symbols-head' : ''}>
          <polygon
            fill={hearLightFill}
            points="560.88 410.33 548.82 451.13 554.95 467.42 560.88 410.33"
          />
          <polygon
            fill={hearLightFill}
            points="492.32 457.92 492.32 423.03 470.61 398.33 454.33 401.04 487.25 457.92 492.32 457.92"
          />
          <polygon
            fill={hearLightFill}
            points="450.81 449.16 425.65 428.56 410.93 433.98 450.81 483.26 450.81 449.16"
          />
          <polygon
            fill={hearLightFill}
            points="422.09 501.11 412.47 478.19 382.26 463.04 365.21 465.36 379.65 483.66 422.09 501.11"
          />
          <polygon
            fill={hearLightFill}
            points="366.82 508.82 347.48 505.66 332.28 510.69 375.89 531.34 366.82 508.82"
          />
          <polygon
            fill={hearLightFill}
            points="417.33 525.96 395.35 529.72 403 542.11 403 542.11 404.09 543.86 424.14 537.41 417.33 525.96"
          />
          <polygon
            fill={hearLightFill}
            points="469.8 521.39 455.09 501.8 436.33 504.86 448.55 525.01 469.8 521.39"
          />
          <polygon
            fill={hearLightFill}
            points="508.25 504.7 506.29 493.5 501.98 495.31 484.46 478.89 456.75 487.5 481.47 515.7 508.25 504.7"
          />
          <g>
            <polygon
              fill={faceBodyFill}
              points="394.76 684.8 377.24 627.85 338.68 639.29 337.9 639.52 299.65 650.86 319.75 709.65 323.69 721.13 360.61 710.2 399.07 698.8 394.76 684.8"
            />
            <path
              fill={faceBodyFill}
              d="M650.2,643.37l-27.84-102.9-25.85,6.47-3.52-13.38-41.41,12-5.04-13.95-107.19,27.93,5.86,18.99-44.36,12.06,28.61,99.15,30.33-10.07,12.12,41.45,105.89-29.6,47.41-13.25-7.16-26.49,32.14-8.41h0ZM459.43,653.08l-10.68-33.62,37.02-11.76,10.68,33.62-37.02,11.76ZM591.18,583l37.52-10.03,9.11,34.07-37.52,10.03-9.11-34.07Z"
            />
            <path
              fill={hearDarkFill}
              d="M567.51,515.65h-18.22l-3.71-19.11-22.82,3.37-13.94-41.6,18.22-.23-28.53-107.8,5.81,29.06-12.4,1.55,12.4,55.8-33.71-38.36,21.71,24.71v34.89h-5.07l-32.91-56.88,20.54,67.81-49.21-40.29,25.16,20.6v34.11l-39.88-49.29,17.05,51.92-45.72-22.86,30.21,15.15,9.62,22.93-42.43-17.45-14.44-18.3,39.13,49.6-37.52-6.14,9.06,22.52-43.61-20.65,36.42,36.43-43.01-1.94-10.46,5.81,45.02,17.35h.01l3.28,1.27.04-2.19.28-10.63,40.23-12.92-1.08-1.74h0l-7.66-12.39,21.98-3.76,6.14,10.39h0l7.99,12.7,81.37-22.08,5.77,11.93,27.93-7.28,5.04,13.95,22.98-6.66-7.05-23.26h0ZM448.55,525.01l-12.23-20.14,18.76-3.06,14.72,19.59-21.25,3.61ZM481.47,515.7l-24.73-28.2,27.72-8.61,17.52,16.42,4.3-1.81,1.97,11.2-26.79,11h0Z"
            />
            <polygon
              fill={hearLightFill}
              points="588.15 514.81 588.15 514.81 560.88 410.33 554.95 467.42 510.9 350.28 498.5 350.28 527.03 458.09 508.82 458.31 522.77 499.91 545.59 496.53 549.29 515.65 567.51 515.65 574.56 538.91 592.99 533.56 593.04 533.56 588.15 514.81"
            />
            <g>
              <rect
                x="453.18"
                y="612.75"
                width="38.84"
                height="35.27"
                transform="translate(-168.65 172.63) rotate(-17.62)"
              />
              <rect
                x="595.08"
                y="577.38"
                width="38.84"
                height="35.27"
                transform="translate(-132.77 178.8) rotate(-14.96)"
              />
            </g>
            <polygon
              fill={bodyDarkFill}
              points="613.78 508.29 588.15 514.81 593.04 533.56 592.99 533.56 596.51 546.95 622.37 540.48 613.78 508.29"
            />
            <polygon
              fill={bodyLightFill}
              points="422.09 736.38 471.92 721.13 459.8 679.69 429.47 689.75 400.85 590.6 445.22 578.53 439.36 559.55 518.61 538.9 512.84 526.97 431.47 549.05 424.14 537.41 363.86 556.78 363.54 569.61 360.26 568.35 320.21 579.52 320.24 579.66 338.68 639.29 377.24 627.85 399.07 698.8 360.58 710.2 373.07 750.47 422.09 736.38"
            />
          </g>
          <g transform="translate(317.34, 397.30) scale(4.52, 3.91)">
            <path
              d="M39.9346 27.7725L37.4346 20.7725H37.6846H37.9346L40.9346 27.7725H39.9346Z"
              fill={hearStripesFill}
            />
            <path
              d="M31.5125 32.8498L26.9082 27.0145L27.1451 26.9347L27.382 26.8549L32.4602 32.5304L31.5125 32.8498Z"
              fill={hearStripesFill}
            />
            <path
              d="M8.12828 36.2771L5.93457 31.3734L6.13614 31.3662L6.33771 31.359L8.93457 36.2483L8.12828 36.2771Z"
              fill={hearStripesFill}
            />
            <path
              d="M40.9345 20.7725L35.4346 0.272491L35.9345 0.272465L40.4345 18.2725L40.9345 20.7725Z"
              fill={hearStripesFill}
            />
            <path
              d="M25.8924 25.1319L20.9346 19.5939L21.1661 19.4995L21.3976 19.4051L26.8184 24.7544L25.8924 25.1319Z"
              fill={hearStripesFill}
            />
            <path
              d="M17.4345 32.2724L12.4345 25.7724L11.4346 24.2725L18.4346 32.2724L17.4345 32.2724Z"
              fill={hearStripesFill}
            />
            <path
              d="M33.262 21.4745L29.5078 15.0591L29.7535 15.0128L29.9991 14.9665L34.2446 21.2891L33.262 21.4745Z"
              fill={hearStripesFill}
            />
          </g>
        </g>
        <g>
          <polygon
            fill={faceBodyFill}
            points="375.46 792.09 375.46 825.27 334.87 825.27 334.87 856.63 335.44 856.63 370.46 856.63 370.47 856.63 409.31 856.63 409.67 856.63 422.09 856.63 422.09 821.37 422.09 821.37 422.09 792.09 375.46 792.09"
          />
          <polygon
            fill={bodyDarkFill}
            points="422.09 856.64 422.09 856.63 409.67 856.63 409.31 856.63 370.47 856.63 370.46 856.63 370.46 927.18 370.47 927.18 370.47 927.26 420.83 927.26 420.83 927.18 420.83 891.9 448.15 891.9 448.51 891.9 448.51 856.64 422.09 856.64"
          />
          <polygon
            fill={faceBodyFill}
            points="526.3 811.86 526.3 811.86 526.3 750.83 487.72 750.83 487.72 786.11 487.72 821.37 516.79 821.37 516.79 847.14 526.3 847.14 555.62 847.14 555.62 821.37 555.62 811.86 526.3 811.86"
          />
          <polygon
            fill={bodyDarkFill}
            points="614.34 891.91 614.34 752.08 577.81 752.08 577.81 691.54 491.85 715.55 487.72 716.71 487.45 716.78 471.92 721.13 448.87 728.18 422.09 736.38 422.09 750.83 448.51 750.83 448.51 786.1 448.87 786.1 448.87 786.11 487.45 786.11 487.72 786.11 487.72 786.1 487.72 750.83 526.3 750.83 526.3 786.1 526.3 786.11 526.3 811.86 526.3 811.86 555.62 811.86 555.62 821.37 555.62 847.14 526.3 847.14 526.3 856.64 509.21 856.64 509.21 870.99 556.74 870.99 556.74 927.18 584.02 927.18 584.02 927.18 629.81 927.18 629.81 891.91 614.34 891.91"
          />
          <polygon
            fill={bodyLightFill}
            points="509.21 891.9 509.21 856.64 526.3 856.64 526.3 847.14 516.79 847.14 516.79 821.37 487.72 821.37 487.72 786.11 448.51 786.1 448.51 786.09 448.51 750.83 422.09 750.83 422.09 736.38 373.07 750.47 360.58 710.2 323.69 721.13 319.76 709.64 301.95 715.54 301.95 791.16 262.36 791.16 262.36 824.66 262.36 857.64 262.36 927.18 348.04 927.27 348.04 891.99 335.44 891.99 334.87 891.99 334.87 856.63 334.87 825.27 375.46 825.27 375.46 792.09 422.09 792.09 422.09 856.63 448.51 856.63 448.51 856.64 448.54 927.26 528.17 927.18 528.17 891.9 509.21 891.9"
          />
        </g>
      </svg>
    </Box>
  );
};

export default PunkSymbolsLogo;
