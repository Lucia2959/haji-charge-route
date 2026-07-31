"use client";

// BYD 돌핀 차량이 앞→옆→뒤→윗면으로 0.01초씩 돌아가며 그려지는 로더.
// 4개 면 SVG를 CSS 키프레임으로 순차 표시(순수 CSS, JS 루프 없음).

export default function CarLoader({
  size = 48,
  label,
  frameMs = 200, // 면당 표시 시간(기본 0.2초 → 한 바퀴 0.8초, 일반적인 속도)
}: {
  size?: number;
  label?: string;
  frameMs?: number;
}) {
  const faces = [CarFront, CarSide, CarBack, CarTop];
  const total = frameMs * faces.length;
  return (
    <div className="cl-wrap">
      <div className="cl-stage" aria-hidden="true" style={{ width: size, height: size }}>
        {faces.map((Face, i) => (
          <span
            key={i}
            className="cl-face"
            style={{
              animationDuration: `${total}ms`,
              animationDelay: `${frameMs * i}ms`,
            }}
          >
            <Face />
          </span>
        ))}
      </div>
      {label && <span className="cl-label">{label}</span>}

      <style jsx>{`
        .cl-wrap {
          display: flex;
          flex-direction: column;
          align-items: center;
          gap: 10px;
        }
        .cl-stage {
          position: relative;
        }
        .cl-face {
          position: absolute;
          inset: 0;
          display: flex;
          align-items: center;
          justify-content: center;
          opacity: 0;
          animation-name: cl-cycle;
          animation-iteration-count: infinite;
          animation-timing-function: steps(1, end);
        }
        .cl-face :global(svg) {
          width: 100%;
          height: 100%;
        }
        @keyframes cl-cycle {
          0%,
          24.9% {
            opacity: 1;
          }
          25%,
          100% {
            opacity: 0;
          }
        }
        .cl-label {
          font-size: 12px;
          color: var(--byd-primary, #0a2540);
          font-weight: 600;
        }
        @media (prefers-reduced-motion: reduce) {
          .cl-face {
            animation: none;
          }
          .cl-face:first-of-type {
            opacity: 1;
          }
        }
      `}</style>
    </div>
  );
}

const TEAL = "#00b894";
const DARK = "#0a2540";
const GLASS = "#bfe9dd";

function CarFront() {
  return (
    <svg viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg">
      <rect x="10" y="24" width="44" height="30" rx="7" fill={TEAL} />
      <path d="M17 25 L23 13 H41 L47 25 Z" fill={DARK} />
      <rect x="20" y="15" width="24" height="9" rx="2" fill={GLASS} />
      <rect x="13" y="42" width="10" height="6" rx="2.5" fill="#fff" />
      <rect x="41" y="42" width="10" height="6" rx="2.5" fill="#fff" />
      <rect x="8" y="50" width="48" height="5" rx="2.5" fill={DARK} />
    </svg>
  );
}

function CarSide() {
  return (
    <svg viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg">
      <path
        d="M6 40 Q6 34 14 33 L20 24 Q22 21 27 21 H42 Q47 21 50 26 L55 33 Q58 34 58 40 V44 H6 Z"
        fill={TEAL}
      />
      <path d="M24 24 H41 Q44 24 46 28 L49 33 H24 Z" fill={GLASS} />
      <circle cx="19" cy="45" r="7" fill={DARK} />
      <circle cx="19" cy="45" r="3" fill="#fff" />
      <circle cx="45" cy="45" r="7" fill={DARK} />
      <circle cx="45" cy="45" r="3" fill="#fff" />
    </svg>
  );
}

function CarBack() {
  return (
    <svg viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg">
      <rect x="10" y="24" width="44" height="30" rx="7" fill={TEAL} />
      <path d="M17 25 L23 14 H41 L47 25 Z" fill={DARK} />
      <rect x="21" y="16" width="22" height="8" rx="2" fill={GLASS} />
      <rect x="13" y="42" width="11" height="6" rx="2.5" fill="#ff5a5a" />
      <rect x="40" y="42" width="11" height="6" rx="2.5" fill="#ff5a5a" />
      <rect x="8" y="50" width="48" height="5" rx="2.5" fill={DARK} />
    </svg>
  );
}

function CarTop() {
  return (
    <svg viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg">
      <rect x="16" y="6" width="32" height="52" rx="12" fill={TEAL} />
      <rect x="21" y="16" width="22" height="14" rx="4" fill={DARK} />
      <rect x="22" y="9" width="20" height="6" rx="3" fill={GLASS} />
      <rect x="22" y="31" width="20" height="6" rx="3" fill={GLASS} />
      <rect x="12" y="20" width="5" height="9" rx="2" fill={DARK} />
      <rect x="47" y="20" width="5" height="9" rx="2" fill={DARK} />
    </svg>
  );
}
