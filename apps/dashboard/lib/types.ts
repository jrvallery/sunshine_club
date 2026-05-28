export type ReviewSummary = {
  db_path: string;
  total_results: number;
  total_review_items: number;
  total_golden_labels: number;
  review_by_status: Record<string, number>;
  results_by_route_status: Record<string, number>;
  results_by_quality: Record<string, number>;
  results_by_primary_tag: Record<string, number>;
  results_by_secondary_tag: Record<string, number>;
};

export type ReviewFacets = Record<string, Record<string, number>>;

export type ReviewItem = {
  id: number | string;
  source?: "sqlite" | "postgres";
  source_path: string;
  relative_path: string;
  route_status: string;
  review_reason: string | null;
  status: string;
  proposed_class: string | null;
  proposed_tag: string | null;
  secondary_tags: string[];
  extraction_text_snippet: string | null;
  confidence: number | null;
  warnings: string[];
  display_warnings?: string[];
  ocr_evidence?: OcrEvidence;
  ocr_quality_label?: string | null;
  run_id?: number | null;
  run_key?: string | null;
  run_preset_key?: string | null;
  embedding_provider?: string | null;
  llm_tag_provider?: string | null;
  ocr_fallback_provider?: string | null;
  enable_llm_tags?: boolean | null;
  decision?: string | null;
  correct_class?: string | null;
  correct_tag?: string | null;
  correct_secondary_tags?: string[];
  expected_review_required?: boolean | null;
  sensitive_record?: boolean;
  correct_destination_path?: string | null;
  correct_placement_year?: string | null;
  correct_privacy?: string | null;
  review_stage?: string | null;
  priority?: string | null;
  assigned_reviewer?: string | null;
  notes?: string | null;
  model_usage_summary?: {
    scope: string;
    total_calls: number;
    failed_calls: number;
    external_calls: number;
    local_calls: number;
    unknown_external_cost_calls: number;
    total_runtime_ms: number;
    total_tokens: number;
    estimated_external_cost_usd: number;
    purposes: string[];
    providers: string[];
  };
  result: PipelineResult;
};

export type OcrEvidence = {
  fallback_used?: boolean;
  fallback_provider?: string | null;
  fallback_reason?: string | null;
  fallback_notes?: string[];
  original_text_snippet?: string | null;
  fallback_text_snippet?: string | null;
  final_text_snippet?: string | null;
};

export type PipelineResult = {
  sample_path?: string;
  source_path?: string;
  relative_path?: string;
  final_class?: string;
  quality?: string;
  extraction_status?: string;
  extraction_strategy?: string;
  top_tag_candidate?: string | null;
  tag_confidence?: number | null;
  tag_evidence?: string[];
  secondary_tags?: string[];
  route_status?: string;
  review_reason?: string | null;
  destination_path?: string | null;
  placement_status?: string | null;
  placement_rule?: string | null;
  placement_date_confidence?: string | null;
  default_privacy?: string | null;
  reviewer_role?: string | null;
  semantic_examples?: SemanticExample[];
  competing_tags?: Array<Record<string, unknown>>;
  confidence_inputs?: Record<string, unknown>;
  ocr_evidence?: OcrEvidence;
  warnings?: string[];
};

export type SemanticExample = {
  score?: number;
  relative_path?: string;
  correct_primary_tag?: string;
};

export type FileRecord = {
  id: number | string;
  source?: "sqlite" | "postgres";
  source_path: string;
  relative_path: string;
  sample_path?: string | null;
  filename: string;
  extension?: string | null;
  mime_type?: string | null;
  size_bytes?: number | null;
  source_collection?: string | null;
  source_mtime?: string | null;
  content_class?: string | null;
  latest_run_id?: number | string | null;
  latest_run_key?: string | null;
  latest_run_preset_key?: string | null;
  latest_embedding_provider?: string | null;
  latest_enable_llm_tags?: boolean | null;
  latest_llm_tag_provider?: string | null;
  latest_ocr_fallback_provider?: string | null;
  latest_result: PipelineResult;
  extraction_text_snippet?: string | null;
  updated_at: string;
};

export type FileSearchItem = {
  id: number | string;
  source?: "sqlite" | "postgres";
  filename: string;
  compact_path: string;
  source_path: string;
  relative_path: string;
  extension?: string | null;
  source_collection?: string | null;
  content_class?: string | null;
  primary_tag?: string | null;
  secondary_tags: string[];
  route_status?: string | null;
  quality?: string | null;
  review_status?: string | null;
  placement_status?: string | null;
  text_snippet?: string | null;
  latest_run_id?: number | string | null;
  latest_run_key?: string | null;
  latest_run_preset_key?: string | null;
  latest_embedding_provider?: string | null;
  latest_enable_llm_tags?: boolean | null;
  latest_llm_tag_provider?: string | null;
  latest_ocr_fallback_provider?: string | null;
  updated_at?: string | null;
};

export type FileSearchResponse = {
  items: FileSearchItem[];
  next_cursor?: number | null;
  total_estimate: number;
  query: Record<string, string | number | boolean>;
};

export type FileFacets = Record<string, Record<string, number>>;

export type FileInspection = {
  file: {
    id: number | string;
    source?: "sqlite" | "postgres";
    filename: string;
    source_path: string;
    relative_path: string;
    sample_path?: string | null;
    extension?: string | null;
    mime_type?: string | null;
    size_bytes?: number | null;
    source_collection?: string | null;
    source_mtime?: string | null;
    content_class?: string | null;
    latest_run_id?: number | string | null;
    latest_run_key?: string | null;
    latest_run_preset_key?: string | null;
    latest_embedding_provider?: string | null;
    latest_enable_llm_tags?: boolean | null;
    latest_llm_tag_provider?: string | null;
    latest_ocr_fallback_provider?: string | null;
    created_at?: string | null;
    updated_at?: string | null;
  };
  latest_result: PipelineResult;
  review_item?: ReviewItem | null;
  golden_label?: GoldenLabel | null;
  ocr: Record<string, unknown>;
  text: { snippet?: string | null; text?: string | null; length: number };
  runs: PipelineRun[];
  actions: Record<string, string | null>;
  raw: Record<string, unknown>;
};

export type RunPreset = {
  preset_key: string;
  label: string;
  description: string;
  input_root: string;
  output_dir: string;
  embedding_provider: string;
  enable_llm_tags: boolean;
  llm_tag_provider: string;
  ocr_fallback_provider: string;
};

export type PipelineRun = {
  id: number | string;
  source?: "sqlite" | "postgres";
  postgres_id?: string | null;
  run_key: string;
  preset_key: string;
  run_role?: string | null;
  status: string;
  input_root?: string | null;
  output_dir?: string | null;
  command: string[];
  embedding_provider?: string | null;
  enable_llm_tags: boolean;
  llm_tag_provider?: string | null;
  ocr_fallback_provider?: string | null;
  semantic_index_path?: string | null;
  run_metadata?: Record<string, unknown>;
  execution_backend?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
  processed_count?: number | null;
  route_candidate_count?: number | null;
  review_required_count?: number | null;
  failed_count?: number | null;
  summary: Record<string, unknown>;
  error?: string | null;
  created_at: string;
  updated_at?: string | null;
};

export type PipelineRunEvent = {
  id: number;
  run_id: number;
  timestamp: string;
  level: string;
  node?: string | null;
  source_path?: string | null;
  relative_path?: string | null;
  message: string;
  payload: Record<string, unknown>;
};

export type PipelineRunResults = {
  run_id: number;
  output_dir: string;
  result_type: string;
  results: Array<Record<string, unknown>>;
};

export type PipelineRunProgress = {
  run_id: number;
  status: string;
  output_dir: string;
  processed_count?: number | null;
  total_count?: number | null;
  progress_ratio?: number | null;
  summary: Record<string, unknown>;
  error?: string | null;
  updated_at?: string | null;
};

export type PipelineRunComparison = {
  run_id: number;
  previous_run_id?: number | null;
  changed: Array<Record<string, unknown>>;
  added: Array<Record<string, unknown>>;
  removed: Array<Record<string, unknown>>;
  summary: Record<string, number>;
};

export type RunArtifact = {
  name: string;
  path: string;
  exists: boolean;
  size_bytes?: number | null;
  modified_at?: string | null;
  row_count?: number | null;
  sha256?: string | null;
};

export type RunModelUsageCall = {
  id?: number;
  run_id?: number;
  source_path?: string | null;
  relative_path?: string | null;
  node?: string | null;
  purpose: string;
  provider: string;
  model: string;
  host?: string | null;
  status: string;
  runtime_ms?: number | null;
  input_tokens?: number | null;
  output_tokens?: number | null;
  total_tokens?: number | null;
  estimated_cost_usd?: number | null;
  cost_basis?: string | null;
  error?: string | null;
};

export type RunModelUsageReport = {
  summary: {
    total_calls: number;
    failed_calls: number;
    external_calls: number;
    local_calls: number;
    runtime_ms: number;
    input_tokens: number;
    output_tokens: number;
    total_tokens: number;
    estimated_external_cost_usd: number;
  };
  by_provider_model: Record<string, Record<string, number>>;
  by_purpose: Record<string, Record<string, number>>;
  by_status: Record<string, number>;
  calls: RunModelUsageCall[];
};

export type RunReport = {
  run: PipelineRun;
  progress: PipelineRunProgress;
  overview: Record<string, unknown>;
  status_buckets?: Record<string, number>;
  distributions: Record<string, Record<string, number>>;
  files: Array<Record<string, unknown>>;
  review_queue: {
    count: number;
    items: Array<Record<string, unknown>>;
    by_status?: Record<string, number>;
    links?: Record<string, string>;
  };
  ocr: { document_count: number; page_count: number; documents: Array<Record<string, unknown>>; pages: Array<Record<string, unknown>> };
  extraction: { count: number; items: Array<Record<string, unknown>> };
  provider_attempts: {
    count: number;
    by_provider: Record<string, number>;
    by_status: Record<string, number>;
    items: Array<Record<string, unknown>>;
  };
  tags: Record<string, Record<string, number>>;
  placement: Record<string, Record<string, number>>;
  model_usage: RunModelUsageReport;
  artifacts: RunArtifact[];
  diff: PipelineRunComparison;
  training_cycle: Record<string, unknown>;
};

export type PostgresRunReport = {
  ok: boolean;
  run: Record<string, unknown>;
  summary: {
    result_count: number;
    review_item_count: number;
    open_review_item_count: number;
    model_usage_count: number;
    model_call_count: number;
    local_model_call_count: number;
    nonlocal_model_call_count: number;
    provider_attempt_count: number;
    parser_result_count?: number;
    parser_review_required_count?: number;
    run_event_count: number;
    failed_run_event_count: number;
    document_segment_count: number;
    segment_review_count: number;
    route_status: Record<string, number>;
    quality: Record<string, number>;
    primary_tag: Record<string, number>;
    segment_type: Record<string, number>;
    provider_attempt_status: Record<string, number>;
    parser_status?: Record<string, number>;
    parser_quality?: Record<string, number>;
    parser_provider?: Record<string, number>;
    run_event_status: Record<string, number>;
    model_provider: Record<string, number>;
    execution_backend?: string | null;
    graph_runtime?: Record<string, unknown>;
  };
  results: Array<Record<string, unknown>>;
  review_items: Array<Record<string, unknown>>;
  model_usage: Array<Record<string, unknown>>;
  provider_attempts: Array<Record<string, unknown>>;
  parser_results?: Array<Record<string, unknown>>;
  document_segments: Array<Record<string, unknown>>;
  run_events: Array<Record<string, unknown>>;
};

export type GoldenLabel = {
  id: number | string;
  source?: "sqlite" | "postgres";
  review_item_id?: number | string | null;
  run_id?: number | string | null;
  run_key?: string | null;
  run_preset_key?: string | null;
  segment_id?: string | null;
  source_path: string;
  relative_path: string;
  sample_path?: string | null;
  extracted_text_snippet?: string | null;
  content_class?: string | null;
  correct_primary_tag: string;
  correct_secondary_tags: string[];
  ocr_quality_label?: string | null;
  expected_review_required?: boolean | null;
  sensitive_record?: boolean;
  correct_destination_path?: string | null;
  correct_placement_year?: string | null;
  correct_privacy?: string | null;
  reviewer?: string | null;
  notes?: string | null;
  proposed_tag?: string | null;
  proposed_secondary_tags?: string[];
  proposed_confidence?: number | null;
  reviewed_at?: string | null;
  created_at: string;
  updated_at: string;
};

export type GoldenLabelSummary = {
  db_path: string;
  total_golden_labels: number;
  golden_by_primary_tag: Record<string, number>;
  golden_by_secondary_tag: Record<string, number>;
  taxonomy_primary_tags?: string[];
  missing_primary_tags?: string[];
  primary_coverage_rate?: number | null;
};

export type SemanticIndexStatus = {
  index_db: string;
  exists: boolean;
  indexed: number;
  updated_at?: string | null;
  embedding_provider?: string | null;
  embedding_model?: string | null;
  embedding_dimensions?: number | null;
  semantic_quality?: boolean | null;
  error?: string;
};

export type SemanticEvalReport = {
  labels_db: string;
  total_golden_labels: number;
  evaluated_predictions: number;
  missing_latest_pipeline_result: number;
  primary_accuracy: number | null;
  secondary_precision: number | null;
  secondary_recall: number | null;
  review_rate: number | null;
  auto_accept_precision: number | null;
  correct_primary: number;
  incorrect_primary: number;
  manual_review_required: number;
  confusion: Record<string, Record<string, number>>;
  mismatches: Array<Record<string, unknown>>;
  files_requiring_manual_review: Array<Record<string, unknown>>;
};

export type PipelineEvalRun = {
  id: number;
  eval_key: string;
  labels_db?: string | null;
  output_dir: string;
  status: string;
  total_golden_labels?: number | null;
  evaluated_predictions?: number | null;
  primary_accuracy?: number | null;
  content_class_accuracy?: number | null;
  secondary_precision?: number | null;
  secondary_recall?: number | null;
  ocr_quality_accuracy?: number | null;
  ocr_acceptable_rate?: number | null;
  review_routing_accuracy?: number | null;
  review_false_accepts?: number | null;
  embedding_success_rate?: number | null;
  semantic_same_family_top5_rate?: number | null;
  placement_destination_accuracy?: number | null;
  source_file_mutations?: number | null;
  acceptance_gate_status?: string | null;
  production_readiness_status?: string | null;
  failure_count?: number | null;
  model_usage: Record<string, unknown>;
  summary: PipelineEvalSummary;
  run_metadata?: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

export type PipelineEvalSummary = {
  labels_db?: string;
  output_dir?: string;
  total_golden_labels?: number;
  evaluated_predictions?: number;
  primary_accuracy?: number | null;
  content_class_accuracy?: number | null;
  secondary_precision?: number | null;
  secondary_recall?: number | null;
  ocr_quality_accuracy?: number | null;
  ocr_acceptable_rate?: number | null;
  review_routing_accuracy?: number | null;
  review_routing_precision?: number | null;
  review_routing_recall?: number | null;
  review_false_accepts?: number;
  review_false_reviews?: number;
  ocr_fallback_rate?: number | null;
  ocr_fallback_failed_count?: number;
  llm_structured_output_validity_rate?: number | null;
  placement_destination_accuracy?: number | null;
  placement_year_accuracy?: number | null;
  unsafe_placement_proposal_count?: number;
  privacy_accuracy?: number | null;
  sensitive_false_accepts?: number;
  sensitive_medium_low_confidence_accepts?: number;
  source_file_mutations?: number;
  high_confidence_primary_accuracy?: number | null;
  high_confidence_false_accepts?: number;
  low_confidence_false_accepts?: number;
  low_confidence_accepted_count?: number;
  medium_confidence_unexplained_count?: number;
  invalid_primary_tag_count?: number;
  tag_evidence_presence_rate?: number | null;
  embedding_success_rate?: number | null;
  semantic_same_family_top5_rate?: number | null;
  high_risk_primary_accuracy_min?: number | null;
  failure_count?: number;
  review_required_count?: number;
  route_candidate_count?: number;
  primary_tag_metrics?: Record<string, {
    total: number;
    correct: number;
    accuracy: number | null;
    review_required: number;
    accepted?: number;
    review_required_rate: number | null;
    false_accepts?: number;
    false_reviews?: number;
    secondary_true_positive?: number;
    secondary_false_positive?: number;
    secondary_false_negative?: number;
    secondary_precision?: number | null;
    secondary_recall?: number | null;
  }>;
  high_risk_primary_tag_metrics?: Record<string, {
    total: number;
    correct: number;
    accuracy: number | null;
    review_required: number;
    accepted?: number;
    review_required_rate: number | null;
    false_accepts?: number;
    false_reviews?: number;
    secondary_precision?: number | null;
    secondary_recall?: number | null;
  }>;
  confidence_bucket_metrics?: Record<string, {
    total: number;
    primary_correct: number;
    primary_accuracy: number | null;
    review_required: number;
    accepted: number;
    review_required_rate: number | null;
    false_accepts: number;
    false_reviews: number;
  }>;
  golden_label_readiness?: {
    ready: boolean;
    minimum_label_count: number;
    total_golden_labels: number;
    label_count_ready: boolean;
    taxonomy_primary_count: number;
    covered_primary_count: number;
    primary_coverage_rate: number | null;
    missing_primary_tags: string[];
    minimum_high_risk_labels_per_category: number;
    high_risk_label_counts: Record<string, number>;
    underrepresented_high_risk_tags: string[];
    primary_label_counts: Record<string, number>;
  };
  by_failure_reason?: Record<string, number>;
  by_quality?: Record<string, number>;
  by_llm_status?: Record<string, number>;
  model_usage?: Record<string, unknown>;
  run_metadata?: Record<string, unknown>;
  run_warnings?: string[];
  artifacts?: Record<string, string>;
  acceptance_gate?: {
    status: string;
    checks: Array<{ name: string; value: number | null; threshold: number; status: string; operator: string }>;
    blocking_checks: Array<{ name: string; value: number | null; threshold: number; status: string; operator: string }>;
  };
  production_readiness?: {
    status: string;
    larger_batch_allowed: boolean;
    customer_claims_allowed: boolean;
    summary: string;
    blocking_reasons: string[];
    required_next_actions: string[];
    reliable_categories: Array<{ tag: string; total: number; correct: number; accuracy: number | null }>;
    unreliable_categories: Array<{ tag: string; total: number; correct: number; accuracy: number | null; reason?: string }>;
    underrepresented_categories: Array<{ tag: string; total: number; correct: number; accuracy: number | null; reason?: string }>;
    status_counts: Record<string, number>;
    category_min_examples: number;
    category_accuracy_threshold: number;
  };
  production_status_counts?: Record<string, number>;
};

export type PipelineEvalRunResponse = {
  ok: boolean;
  output_dir: string;
  eval_run: PipelineEvalRun;
  report: PipelineEvalSummary;
};

export type PipelineEvalDrilldown = {
  eval_run: PipelineEvalRun;
  result_type: string;
  path: string;
  count: number;
  items: Array<Record<string, unknown>>;
};

export type PipelineEvalComparison = {
  baseline_eval_run: PipelineEvalRun;
  current_eval_run: PipelineEvalRun;
  shared_file_count: number;
  baseline_only_count: number;
  current_only_count: number;
  metric_deltas: Record<string, { baseline: number | null; current: number | null; delta: number | null }>;
  changed_prediction_count: number;
  changed_secondary_tag_count?: number;
  fixed_failure_count: number;
  regressed_failure_count: number;
  changed_failure_reason_count?: number;
  changed_review_route_count: number;
  changed_predictions: Array<Record<string, unknown>>;
  changed_secondary_tags?: Array<Record<string, unknown>>;
  fixed_failures: Array<Record<string, unknown>>;
  regressed_failures: Array<Record<string, unknown>>;
  changed_failure_reasons?: Array<Record<string, unknown>>;
  changed_review_routes: Array<Record<string, unknown>>;
};

export type PlacementReport = {
  db_path: string;
  total_results: number;
  placement_resolution_rate: number | null;
  corrected_placement_decisions: number;
  by_placement_status: Record<string, number>;
  by_privacy: Record<string, number>;
  missing_date_queue: ReviewItem[];
};
