"use client";

export function PathCell({
  title,
  subtitle,
  onClick,
  href
}: {
  title: string;
  subtitle?: string | null;
  onClick?: () => void;
  href?: string | null;
}) {
  const body = (
    <>
      <strong title={title}>{title}</strong>
      {subtitle ? <span title={subtitle}>{subtitle}</span> : null}
    </>
  );
  if (onClick) {
    return (
      <button className="linkButton pathCell" onClick={onClick}>
        {body}
      </button>
    );
  }
  if (href) {
    return (
      <a className="pathCell pathCellLink" href={href}>
        {body}
      </a>
    );
  }
  return <div className="pathCell">{body}</div>;
}
