import type {
  Project,
  ComponentSpec,
  ModelConfig,
  SpaceValidateResult,
  TaskStatus,
  Proposal,
  RoundSummary,
  Analytics,
  PredictResult,
  RecommendResult,
  Rule,
  RulesResult,
  ImportPreview,
  PriorExperiment,
  DescriptorTool,
  DescriptorComputeResult,
  DescriptorComposeResult,
  DerivedFeature,
  ProjectConfig,
  WhatIfResult,
  CsvImportResult,
} from "./types";

async function req<T>(url: string, options?: RequestInit): Promise<T> {
  const res = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? JSON.stringify(body);
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

const spacePayload = (components: ComponentSpec[], model_config_: ModelConfig) => ({
  components,
  model_config_,
});

export const api = {
  // projects
  listProjects: (archived = false) =>
    req<Project[]>(`/api/projects${archived ? "?archived=true" : ""}`),
  getProject: (id: string) => req<Project>(`/api/projects/${id}`),
  createProject: (data: { name: string; target: string; direction: string }) =>
    req<Project>("/api/projects", { method: "POST", body: JSON.stringify(data) }),
  archiveProject: (id: string) =>
    req<Project>(`/api/projects/${id}/archive`, { method: "POST" }),
  restoreProject: (id: string) =>
    req<Project>(`/api/projects/${id}/restore`, { method: "POST" }),
  rebuildProject: (
    id: string,
    data: {
      name?: string;
      copy_data?: boolean;
      components: ComponentSpec[];
      model_config_: ModelConfig;
    }
  ) =>
    req<{ project_id: string; task_id: string }>(`/api/projects/${id}/rebuild`, {
      method: "POST",
      body: JSON.stringify(data),
    }),
  getConfig: (id: string) => req<ProjectConfig>(`/api/projects/${id}/config`),
  getPendingPrior: (id: string) =>
    req<PriorExperiment[]>(`/api/projects/${id}/pending-prior`),
  deleteProject: (id: string) =>
    req<{ ok: boolean }>(`/api/projects/${id}`, { method: "DELETE" }),

  // space
  uploadDescriptor: async (projectId: string, file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    const res = await fetch(`/api/projects/${projectId}/descriptors`, {
      method: "POST",
      body: fd,
    });
    if (!res.ok) throw new Error((await res.json()).detail ?? "upload failed");
    return res.json() as Promise<{
      filename: string;
      columns: string[];
      id_column: string;
      n_rows: number;
      identifiers: string[];
    }>;
  },
  getDescriptorTools: () =>
    req<{ tools: DescriptorTool[] }>("/api/descriptor-tools"),
  computeDescriptors: (
    id: string,
    data: { tool_id: string; identifiers: string[] }
  ) =>
    req<DescriptorComputeResult>(`/api/projects/${id}/descriptors/compute`, {
      method: "POST",
      body: JSON.stringify(data),
    }),
  importDescriptors: async (
    id: string,
    file: File,
    identifiers: string[]
  ) => {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("identifiers", JSON.stringify(identifiers));
    const res = await fetch(`/api/projects/${id}/descriptors/import`, {
      method: "POST",
      body: fd,
    });
    if (!res.ok) throw new Error((await res.json()).detail ?? "import failed");
    return res.json() as Promise<DescriptorComputeResult>;
  },
  composeDescriptors: (
    id: string,
    data: {
      tool_id: string;
      identifiers: string[];
      selected: string[];
      derived: DerivedFeature[];
      standardize: boolean;
      pca_n: number | null;
      out_name: string;
      source_file?: string | null;
    }
  ) =>
    req<DescriptorComposeResult>(`/api/projects/${id}/descriptors/compose`, {
      method: "POST",
      body: JSON.stringify(data),
    }),
  whatifDescriptors: (id: string, components: ComponentSpec[], mc: ModelConfig) =>
    req<WhatIfResult>(`/api/projects/${id}/descriptors/whatif`, {
      method: "POST",
      body: JSON.stringify(spacePayload(components, mc)),
    }),
  applyDescriptors: (id: string, components: ComponentSpec[], mc: ModelConfig) =>
    req<{ task_id: string }>(`/api/projects/${id}/descriptors/apply`, {
      method: "POST",
      body: JSON.stringify(spacePayload(components, mc)),
    }),
  validateSpace: (id: string, components: ComponentSpec[], mc: ModelConfig) =>
    req<SpaceValidateResult>(`/api/projects/${id}/space/validate`, {
      method: "POST",
      body: JSON.stringify(spacePayload(components, mc)),
    }),
  buildSpace: (id: string, components: ComponentSpec[], mc: ModelConfig) =>
    req<{ task_id: string }>(`/api/projects/${id}/space`, {
      method: "POST",
      body: JSON.stringify(spacePayload(components, mc)),
    }),
  getComponents: (id: string) =>
    req<{ components: Record<string, (string | number)[]>; target: string }>(
      `/api/projects/${id}/components`
    ),

  // optimization
  init: (
    id: string,
    data: {
      seed?: number | null;
      batch_size: number;
      init_method: string;
      prior_experiments?: PriorExperiment[];
    }
  ) =>
    req<{ task_id: string }>(`/api/projects/${id}/init`, {
      method: "POST",
      body: JSON.stringify(data),
    }),
  run: (id: string, data: { acq_function: string; batch_size: number; acq_params?: object }) =>
    req<{ task_id: string }>(`/api/projects/${id}/run`, {
      method: "POST",
      body: JSON.stringify(data),
    }),
  getRecommendations: (
    id: string,
    data: { acq_function: string; top_n: number; jitter?: number }
  ) =>
    req<RecommendResult>(`/api/projects/${id}/recommendations`, {
      method: "POST",
      body: JSON.stringify(data),
    }),
  adopt: (
    id: string,
    round: number,
    items: { domain_index: number; rank?: number | null; acq_score?: number | null }[],
    ctx: { acq_function: string; acq_params?: Record<string, unknown>; adopted_by?: string }
  ) =>
    req<Proposal[]>(`/api/projects/${id}/rounds/${round}/adopt`, {
      method: "POST",
      body: JSON.stringify({
        items,
        domain_indices: items.map((it) => it.domain_index),
        acq_function: ctx.acq_function,
        acq_params: ctx.acq_params ?? {},
        adopted_by: ctx.adopted_by ?? "anonymous",
      }),
    }),
  newRound: (id: string) =>
    req<{ ok: boolean; round_index: number; skipped: number }>(
      `/api/projects/${id}/rounds/new`,
      { method: "POST", body: "{}" }
    ),
  getTask: (id: string, taskId: string) =>
    req<TaskStatus>(`/api/projects/${id}/tasks/${taskId}`),

  // experiments
  getProposals: (id: string) => req<Proposal[]>(`/api/projects/${id}/proposals`),
  getRoundExperiments: (id: string, round: number) =>
    req<Proposal[]>(`/api/projects/${id}/rounds/${round}/experiments`),
  submitMachineResults: (
    id: string,
    round: number,
    results: { experiment_id: string; observed_value: number | null; note?: string }[]
  ) =>
    req<{ ok: boolean; updated: number }>(
      `/api/projects/${id}/rounds/${round}/machine-results`,
      { method: "POST", body: JSON.stringify({ results }) }
    ),
  submitHumanExperiments: (
    id: string,
    round: number,
    experiments: {
      components: Record<string, string | number>;
      observed_value: number;
      note?: string;
    }[]
  ) =>
    req<{ ok: boolean; accepted: number; rejected: { components: object; reason: string }[] }>(
      `/api/projects/${id}/rounds/${round}/human-experiments`,
      { method: "POST", body: JSON.stringify({ experiments }) }
    ),
  addHumanConditions: (
    id: string,
    round: number,
    experiments: {
      components: Record<string, string | number>;
      observed_value?: number | null;
      note?: string;
    }[]
  ) =>
    req<{
      ok: boolean;
      accepted: number;
      rejected: { components: object; reason: string }[];
      warnings: { components: object; rules: string[] }[];
    }>(`/api/projects/${id}/rounds/${round}/human-conditions`, {
      method: "POST",
      body: JSON.stringify({ experiments }),
    }),
  uploadResultsCsv: async (id: string, round: number, file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    const res = await fetch(`/api/projects/${id}/rounds/${round}/results-csv`, {
      method: "POST",
      body: fd,
    });
    if (!res.ok) {
      let detail = res.statusText;
      try {
        detail = (await res.json()).detail ?? detail;
      } catch {
        /* ignore */
      }
      throw new Error(detail);
    }
    return res.json() as Promise<CsvImportResult>;
  },

  // rules
  getRules: (id: string) => req<RulesResult>(`/api/projects/${id}/rules`),
  setRules: (id: string, rules: Rule[]) =>
    req<RulesResult>(`/api/projects/${id}/rules`, {
      method: "PUT",
      body: JSON.stringify({ rules }),
    }),

  // import prior results
  importPreview: async (id: string, file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    const res = await fetch(`/api/projects/${id}/import/preview`, {
      method: "POST",
      body: fd,
    });
    if (!res.ok) throw new Error((await res.json()).detail ?? "parse failed");
    return res.json() as Promise<ImportPreview>;
  },

  editExperiment: (
    id: string,
    experimentId: string,
    data: { observed_value: number | null; note?: string }
  ) =>
    req<{ ok: boolean; retrained: boolean; experiment: Proposal }>(
      `/api/projects/${id}/experiments/${experimentId}`,
      { method: "PATCH", body: JSON.stringify(data) }
    ),
  deleteExperiment: (id: string, experimentId: string) =>
    req<{ ok: boolean }>(`/api/projects/${id}/experiments/${experimentId}`, {
      method: "DELETE",
    }),
  predict: (id: string, components: Record<string, string | number>) =>
    req<PredictResult>(`/api/projects/${id}/predict`, {
      method: "POST",
      body: JSON.stringify({ components }),
    }),

  // analytics
  getRounds: (id: string) => req<RoundSummary[]>(`/api/projects/${id}/rounds`),
  getRoundSummary: (id: string, round: number) =>
    req<RoundSummary>(`/api/projects/${id}/rounds/${round}/summary`),
  getAnalytics: (id: string) => req<Analytics>(`/api/projects/${id}/analytics`),
};

export async function pollTask(
  projectId: string,
  taskId: string,
  onProgress?: (t: TaskStatus) => void,
  intervalMs = 1200
): Promise<TaskStatus> {
  // eslint-disable-next-line no-constant-condition
  while (true) {
    const t = await api.getTask(projectId, taskId);
    onProgress?.(t);
    if (t.status === "done" || t.status === "error") return t;
    await new Promise((r) => setTimeout(r, intervalMs));
  }
}
