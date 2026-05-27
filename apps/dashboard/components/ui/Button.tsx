import type { ButtonHTMLAttributes, ReactNode } from "react";

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "danger";
  children: ReactNode;
};

export function Button({ variant = "secondary", className = "", children, ...props }: ButtonProps) {
  const variantClass = variant === "primary" ? "primaryButton" : variant === "danger" ? "secondaryButton dangerText" : "secondaryButton";
  return (
    <button className={`${variantClass} ${className}`.trim()} {...props}>
      {children}
    </button>
  );
}
