"use client";

import { useState } from "react";

import { MultiTagPicker, TagPicker } from "../components/ui/TagPicker";
import { primaryTagOptions, secondaryTagOptions } from "../lib/taxonomy";

type ReviewDecisionFormProps = {
  apiBaseUrl: string;
  itemId: number;
  proposedClass: string | null;
  proposedTag: string | null;
  secondaryTags: string[];
};

export function ReviewDecisionForm({
  apiBaseUrl,
  itemId,
  proposedClass,
  proposedTag,
  secondaryTags
}: ReviewDecisionFormProps) {
  const [status, setStatus] = useState<string>("");
  const [correctTag, setCorrectTag] = useState(proposedTag ?? "");
  const [correctSecondaryTags, setCorrectSecondaryTags] = useState(secondaryTags);

  async function submit(formData: FormData) {
    setStatus("Saving...");
    const response = await fetch(`${apiBaseUrl}/admin/review/items/${itemId}/decision`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        decision: formData.get("decision"),
        correct_class: String(formData.get("correct_class") ?? "").trim() || null,
        correct_tag: correctTag.trim() || null,
        correct_secondary_tags: correctSecondaryTags,
        reviewer: String(formData.get("reviewer") ?? "").trim() || null,
        notes: String(formData.get("notes") ?? "").trim() || null,
        save_as_golden: formData.get("save_as_golden") === "on"
      })
    });
    if (!response.ok) {
      setStatus("Save failed");
      return;
    }
    setStatus("Saved");
    window.location.reload();
  }

  return (
    <form className="reviewForm" action={submit}>
      <label>
        <span>Decision</span>
        <select name="decision" defaultValue="accept">
          <option value="accept">Accept</option>
          <option value="change">Change</option>
          <option value="defer">Defer</option>
          <option value="reject">Reject</option>
        </select>
      </label>
      <label>
        <span>Class</span>
        <input name="correct_class" defaultValue={proposedClass ?? ""} />
      </label>
      <TagPicker label="Primary tag" options={primaryTagOptions} value={correctTag} onChange={setCorrectTag} />
      <MultiTagPicker label="Secondary tags" options={secondaryTagOptions} value={correctSecondaryTags} onChange={setCorrectSecondaryTags} />
      <label>
        <span>Reviewer</span>
        <input name="reviewer" defaultValue="james" />
      </label>
      <label>
        <span>Notes</span>
        <textarea name="notes" rows={2} />
      </label>
      <label className="checkboxLabel">
        <input name="save_as_golden" type="checkbox" defaultChecked />
        <span>Golden label</span>
      </label>
      <button type="submit">Save</button>
      {status ? <div className="formStatus">{status}</div> : null}
    </form>
  );
}
