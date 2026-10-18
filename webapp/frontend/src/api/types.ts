export type ProjectStatus =
  | "created"
  | "building"
  | "ready"
  | "sampling"
  | "awaiting_results"
  | "training"
  | "error";

export interface Project {
  id: string;
  name: string;
  target: string;
  direction: "max" | "min";
  status: ProjectStatus;
  current_round: number;
  space_size?: number | null;
  created_by?: string | null;
  n_experiments: number;
  best_value?: number | null;
  archived?: boolean;
  pending_prior?: number;
}

export interface ProjectConfig {
  components: {
    name: string;
    values: (string | number)[];
    encoding: EncodingType;
    descriptor_file?: string | null;
    id_column?: string | null;
  }[];
  model: string;
  init_method: string;
}

export interface RegressionData {
  predicted: number[];
  observed: number[];
  r2: number | null;
}

export interface WhatIfResult {
  ok: boolean;
  n_obs: number;
  space_size?: number | null;
  current?: RegressionData | null;
  whatif?: RegressionData | null;
  error?: string | null;
}

export type EncodingType = "ohe" | "numeric" | "mordred" | "resolve" | "descriptor";

export interface ComponentSpec {
  name: string;
  values: (string | number)[];
  encoding: EncodingType;
  descriptor_file?: string | null;
  id_column?: string | null;
}

export interface ModelConfig {
  model: string;
  init_method: string;
}

export interface SpaceValidateResult {
  ok: boolean;
  space_size: number;
  warnings: string[];
  errors: string[];
}

export interface TaskStatus {
  id: string;
  kind: string;
  status: "pending" | "running" | "done" | "error";
  progress: number;
  message?: string | null;
  error?: string | null;
}

export type ExperimentSource = "machine" | "human" | "prior";
export type ExperimentStatus = "proposed" | "done" | "skipped" | "excluded";

export interface Provenance {
  source?: string;
  adopted_from?: string;   // leaderboard | manual | init | import | batch
  acq_function?: string | null;
  acq_params?: Record<string, unknown>;
  rank?: number | null;
  acq_score?: number | null;
  init_method?: string | null;
  seed?: number | null;
  encoding?: Record<string, string>;
  descriptors?: Record<string, string | null>;
  model?: string | null;
  by?: string | null;
  at?: string | null;
  rule_overrides?: string[];
}

export interface Proposal {
  id: string;
  domain_index: number;
  source: ExperimentSource;
  status: ExperimentStatus;
  components: Record<string, string | number>;
  predicted_mean?: number | null;
  predicted_var?: number | null;
  observed_value?: number | null;
  note?: string | null;
  provenance?: Provenance | null;
}

export interface RoundSummary {
  round_index: number;
  kind: string;
  acq_function?: string | null;
  batch_size?: number | null;
  n_machine: number;
  n_human: number;
  n_done: number;
  n_skipped: number;
  best_value?: number | null;
  experiments: Proposal[];
}

export interface RecommendItem {
  domain_index: number;
  components: Record<string, string | number>;
  predicted_mean?: number | null;
  predicted_var?: number | null;
  acq_score?: number | null;
}

export interface RecommendResult {
  ok: boolean;
  reason?: string | null;
  acq_function: string;
  items: RecommendItem[];
}

export interface RuleClause {
  component: string;
  op: "eq" | "ne" | "in" | "nin" | "ge" | "le" | "gt" | "lt";
  value: string | number | (string | number)[];
}

export interface Rule {
  id?: string | null;
  name: string;
  active: boolean;
  clauses: RuleClause[];
}

export interface RulesResult {
  rules: Rule[];
  excluded_count?: number | null;
}

export interface ImportPreview {
  columns: string[];
  rows: Record<string, string | number | null>[];
  n_rows: number;
}

export type CsvRowAction = "updated" | "added" | "skipped" | "rejected";

export interface CsvRowResult {
  row: number;
  action: CsvRowAction;
  reason?: string | null;
  components?: Record<string, string | number> | null;
  observed_value?: number | null;
  experiment_id?: string | null;
  warnings: string[];
}

export interface CsvImportResult {
  ok: boolean;
  round_index: number;
  target: string;
  updated: number;
  added: number;
  skipped: number;
  rejected: number;
  retrained: boolean;
  rows: CsvRowResult[];
}

export interface PriorExperiment {
  components: Record<string, string | number>;
  observed_value: number;
}

export interface DescriptorTool {
  id: string;
  name: string;
  input_kind: string;
  available: boolean;
  kind?: "compute" | "import";
}

export interface DescriptorComputeResult {
  ok: boolean;
  id_column: string;
  columns: string[];
  rows: Record<string, number | string | null>[];
  stats: Record<string, { variance: number }>;
  invalid: string[];
  source_file?: string | null;
  error?: string | null;
}

export interface DerivedFeature {
  a: string;
  b: string;
  op: "add" | "sub" | "mul" | "div";
  name?: string;
}

export interface DescriptorComposeResult {
  ok: boolean;
  filename?: string | null;
  id_column: string;
  columns: string[];
  n_rows: number;
  preview: Record<string, number | string | null>[];
  invalid: string[];
  error?: string | null;
}

export interface ConvergenceRound {
  round_index: number;
  kind: string;
  n_done: number;
  round_best: number | null;
  round_mean: number | null;
  cumulative_best: number | null;
}

export interface PredictResult {
  ok: boolean;
  mean?: number | null;
  std?: number | null;
  domain_index?: number | null;
  error?: string | null;
}

export interface Analytics {
  target: string;
  direction: "max" | "min";
  n_experiments: number;
  best_value?: number | null;
  convergence: { n: number; value: number; best: number }[];
  convergence_rounds: ConvergenceRound[];
  rounds: { round_index: number; kind: string; values: number[]; best: number | null }[];
  top: {
    domain_index: number;
    components: Record<string, string | number>;
    observed_value: number;
    source: string;
  }[];
  regression?: { predicted: number[]; observed: number[]; r2: number | null } | null;
}
