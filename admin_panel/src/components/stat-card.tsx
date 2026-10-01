import { ArrowDownCircle, ArrowUpCircle } from "lucide-react";

export interface StatCardProps {
  /** Label shown above the value (e.g. "Total campaigns") */
  title: string;
  /** Primary metric value (e.g. "348", "$41,320") */
  value: string;
  /** Optional secondary text beside the value (e.g. "per user/month") */
  subValue?: string;
  /** Delta text (e.g. "+12%", "-24") */
  change?: string;
  /** Controls arrow direction and color intent */
  isPositive?: boolean;
  /** Accent color for the trend indicator — use DESIGN_TOKENS.colors.highlight* */
  accentColor?: string;
  /** Contextual description (e.g. "Than last month") */
  description?: string;
  /** Whether to show arrow icon */
  showArrow?: boolean;
}

const StatCard = ({
  title,
  value,
  subValue,
  change,
  isPositive = true,
  accentColor,
  description,
  showArrow = false,
}: StatCardProps) => {
  return (
    <div className="rounded-12 border border-border-default p-0.5 bg-surface-primary flex flex-col transition-all duration-200 hover:shadow-xs">
      {/* Top Primary Section — Stats Bar White Space */}
      <div className="h-17.25 rounded-10 p-2 bg-surface-card flex flex-col justify-between">
        <span className="text-[13px] font-normal text-text-dark">
          {title}
        </span>
        <div className="flex items-baseline gap-1.5 min-w-0">
          <span className="text-[24px] font-bold text-text-dark leading-tight tracking-tight">
            {value}
          </span>
          {subValue && (
            <span className="text-[12px] font-normal text-text-muted truncate">
              {subValue}
            </span>
          )}
        </div>
      </div>

      {/* Bottom Meta Section — Stats Bar Grey Space */}
      <div className="h-7.5 px-2 py-1.5 flex items-center justify-between">
        {description && (
          <span className="text-[12px] font-normal text-text-muted">
            {description}
          </span>
        )}

        {change && (
          <div
            className="flex items-center gap-1 font-medium text-[12px]"
            style={{ color: accentColor }}
          >
            {showArrow && (
              isPositive ? (
                <ArrowUpCircle size={14} strokeWidth={1.8} />
              ) : (
                <ArrowDownCircle size={14} strokeWidth={1.8} />
              )
            )}
            <span>{change}</span>
          </div>
        )}
      </div>
    </div>
  );
};

export default StatCard;
