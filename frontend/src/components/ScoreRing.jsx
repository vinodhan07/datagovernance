export default function ScoreRing({ score = 0, size = 80 }) {
  const radius = 36
  const circumference = 2 * Math.PI * radius
  const clampedScore = Math.max(0, Math.min(100, score))
  const offset = circumference - (clampedScore / 100) * circumference

  const color =
    clampedScore >= 80 ? '#10b981' :
    clampedScore >= 60 ? '#f59e0b' : '#ef4444'

  return (
    <svg width={size} height={size} viewBox="0 0 80 80">
      {/* Track */}
      <circle
        cx="40" cy="40" r={radius}
        fill="none"
        stroke="#e2e8f0"
        strokeWidth="5"
      />
      {/* Progress */}
      <circle
        cx="40" cy="40" r={radius}
        fill="none"
        stroke={color}
        strokeWidth="5"
        strokeLinecap="round"
        strokeDasharray={circumference}
        strokeDashoffset={offset}
        transform="rotate(-90 40 40)"
        style={{ transition: 'stroke-dashoffset 0.6s ease-out, stroke 0.3s' }}
      />
      {/* Label */}
      <text
        x="40" y="40"
        textAnchor="middle"
        dominantBaseline="central"
        fontSize="15"
        fontWeight="700"
        fill={color}
        fontFamily="'Plus Jakarta Sans', sans-serif"
      >
        {Math.round(clampedScore)}%
      </text>
    </svg>
  )
}
