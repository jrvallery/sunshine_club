CREATE TABLE IF NOT EXISTS golden_labels_v2 (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  review_item_id uuid REFERENCES review_items_v2(id) ON DELETE SET NULL,
  run_id uuid REFERENCES pipeline_runs(id) ON DELETE SET NULL,
  source_path text NOT NULL,
  relative_path text,
  sample_path text,
  segment_id text NOT NULL DEFAULT '',
  extracted_text_snippet text,
  content_class text,
  correct_primary_tag text NOT NULL,
  correct_secondary_tags jsonb NOT NULL DEFAULT '[]'::jsonb,
  ocr_quality_label text,
  expected_review_required boolean,
  sensitive_record boolean NOT NULL DEFAULT false,
  correct_destination_path text,
  correct_placement_year text,
  correct_privacy text,
  reviewer text,
  notes text,
  proposed_tag text,
  proposed_secondary_tags jsonb NOT NULL DEFAULT '[]'::jsonb,
  proposed_confidence numeric,
  reviewed_at timestamptz NOT NULL DEFAULT now(),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (source_path, segment_id)
);

CREATE INDEX IF NOT EXISTS golden_labels_v2_run_id_idx ON golden_labels_v2(run_id);
CREATE INDEX IF NOT EXISTS golden_labels_v2_review_item_id_idx ON golden_labels_v2(review_item_id);
CREATE INDEX IF NOT EXISTS golden_labels_v2_correct_primary_tag_idx ON golden_labels_v2(correct_primary_tag);
