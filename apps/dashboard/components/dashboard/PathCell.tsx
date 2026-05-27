"use client";

export function PathCell({
  title,
  subtitle,
  onClick
}: {
  title: string;
  subtitle?: string | null;
  onClick?: () => void;
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
  return <div className="pathCell">{body}</div>;
}
