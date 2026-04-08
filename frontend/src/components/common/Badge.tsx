type BadgeVariant = 'green' | 'yellow' | 'red' | 'blue' | 'gray'

const styles: Record<BadgeVariant, string> = {
  green:  'bg-green-100 text-green-700',
  yellow: 'bg-amber-100 text-amber-700',
  red:    'bg-red-100 text-red-700',
  blue:   'bg-primary-100 text-primary-700',
  gray:   'bg-slate-100 text-slate-600',
}

export function Badge({ children, variant = 'gray' }: { children: React.ReactNode; variant?: BadgeVariant }) {
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${styles[variant]}`}>
      {children}
    </span>
  )
}

// 凭证状态 → Badge
export function ReviewStatusBadge({ status }: { status: string }) {
  const map: Record<string, [string, BadgeVariant]> = {
    DRAFT:          ['草稿',   'gray'],
    PENDING_REVIEW: ['待审核', 'yellow'],
    POSTED:         ['已过账', 'green'],
    REJECTED:       ['已驳回', 'red'],
  }
  const [label, variant] = map[status] ?? [status, 'gray']
  return <Badge variant={variant}>{label}</Badge>
}

// 置信度 → Badge
export function ConfidenceBadge({ level }: { level: string }) {
  const map: Record<string, [string, BadgeVariant]> = {
    HIGH:   ['高置信', 'green'],
    MEDIUM: ['中置信', 'yellow'],
    LOW:    ['低置信', 'red'],
  }
  const [label, variant] = map[level] ?? [level, 'gray']
  return <Badge variant={variant}>{label}</Badge>
}
