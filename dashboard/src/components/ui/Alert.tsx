import React from 'react';
import { AlertCircle, CheckCircle2, Info, AlertTriangle, X } from 'lucide-react';

export type AlertVariant = 'default' | 'destructive' | 'warning' | 'success';

export interface AlertProps extends React.HTMLAttributes<HTMLDivElement> {
  variant?: AlertVariant;
  title?: string;
  onClose?: () => void;
  showIcon?: boolean;
}

const variantStyles: Record<AlertVariant, { bg: string, border: string, text: string, titleText: string, icon: React.FC<any> }> = {
  default: {
    bg: 'bg-slate-800/50',
    border: 'border-slate-700/50',
    text: 'text-slate-300',
    titleText: 'text-slate-100',
    icon: Info,
  },
  destructive: {
    bg: 'bg-rose-500/10',
    border: 'border-rose-500/20',
    text: 'text-rose-200',
    titleText: 'text-rose-400',
    icon: AlertCircle,
  },
  warning: {
    bg: 'bg-amber-500/10',
    border: 'border-amber-500/20',
    text: 'text-amber-200',
    titleText: 'text-amber-400',
    icon: AlertTriangle,
  },
  success: {
    bg: 'bg-emerald-500/10',
    border: 'border-emerald-500/20',
    text: 'text-emerald-200',
    titleText: 'text-emerald-400',
    icon: CheckCircle2,
  },
};

export const Alert = React.forwardRef<HTMLDivElement, AlertProps>(
  ({ className = '', variant = 'default', title, children, showIcon = true, onClose, ...props }, ref) => {
    const styles = variantStyles[variant];
    const Icon = styles.icon;

    return (
      <div
        ref={ref}
        role="alert"
        className={`relative w-full rounded-xl border p-4 backdrop-blur-md transition-all shadow-sm ${styles.bg} ${styles.border} ${className}`}
        {...props}
      >
        <div className="flex items-start gap-3">
          {showIcon && <Icon className={`mt-0.5 h-5 w-5 shrink-0 ${styles.titleText}`} />}
          <div className="flex-1 space-y-1">
            {title && (
              <h5 className={`font-semibold leading-none tracking-tight ${styles.titleText}`}>
                {title}
              </h5>
            )}
            <div className={`text-sm leading-relaxed ${styles.text}`}>
              {children}
            </div>
          </div>
          {onClose && (
            <button
              onClick={onClose}
              className={`shrink-0 opacity-70 hover:opacity-100 transition-opacity ${styles.titleText}`}
            >
              <X className="h-4 w-4" />
            </button>
          )}
        </div>
      </div>
    );
  }
);
Alert.displayName = 'Alert';

export const AlertDescription = React.forwardRef<
  HTMLParagraphElement,
  React.HTMLAttributes<HTMLParagraphElement>
>(({ className = '', ...props }, ref) => (
  <div
    ref={ref}
    className={`text-sm leading-relaxed ${className}`}
    {...props}
  />
));
AlertDescription.displayName = 'AlertDescription';
