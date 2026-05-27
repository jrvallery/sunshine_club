"use client";

import Link from "next/link";

export function RunContextBadge({
  runId,
  runKey,
  preset
}: {
  runId?: number | string | null;
  runKey?: string | null;
  preset?: string | null;
}) {
  if (!runId) {
    return <span className="muted">Manual / legacy</span>;
  }
  return (
    <div className="runContextBadge">
      <Link className="viewLink" href={`/runs/${runId}/report`}>
        {runKey || `Run #${runId}`}
      </Link>
      {preset ? <span>{preset}</span> : null}
    </div>
  );
}
