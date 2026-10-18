import type { ProjectStatus, ExperimentStatus, ExperimentSource, Provenance } from "../api/types";

export function Spinner({ className = "" }: { className?: string }) {
  return (
    <svg
      className={`animate-spin h-4 w-4 ${className}`}
      viewBox="0 0 24 24"
      fill="none"
    >
      <circle
        className="opacity-25"
        cx="12"
        cy="12"
        r="10"
        stroke="currentColor"
        strokeWidth="4"
      />
      <path
        className="opacity-75"
        fill="currentColor"
        d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z"
      />
    </svg>
  );
}

const STATUS_LABEL: Record<ProjectStatus, string> = {
  created: "待配置空间",
  building: "构建空间中",
  ready: "待初始化",
  sampling: "初始化中",
  awaiting_results: "等待结果录入",
  training: "训练采集中",
  error: "错误",
};

const STATUS_COLOR: Record<ProjectStatus, string> = {
  created: "bg-slate-100 text-slate-600",
  building: "bg-amber-100 text-amber-700",
  ready: "bg-sky-100 text-sky-700",
  sampling: "bg-amber-100 text-amber-700",
  awaiting_results: "bg-emerald-100 text-emerald-700",
  training: "bg-amber-100 text-amber-700",
  error: "bg-rose-100 text-rose-700",
};

export function StatusBadge({ status }: { status: ProjectStatus }) {
  const busy = status === "building" || status === "training" || status === "sampling";
  return (
    <span className={`badge ${STATUS_COLOR[status]}`}>
      {busy && <Spinner className="mr-1 h-3 w-3" />}
      {STATUS_LABEL[status] ?? status}
    </span>
  );
}

export function SourceBadge({ source }: { source: ExperimentSource | string }) {
  const map: Record<string, [string, string]> = {
    machine: ["机器推荐", "bg-brand-50 text-brand-700"],
    human: ["人类决策", "bg-purple-100 text-purple-700"],
    prior: ["前置导入", "bg-amber-100 text-amber-700"],
  };
  const [label, cls] = map[source] ?? [source, "bg-slate-100 text-slate-600"];
  return <span className={`badge ${cls}`}>{label}</span>;
}

export function ExpStatusBadge({ status }: { status: ExperimentStatus | string }) {
  const map: Record<string, [string, string]> = {
    proposed: ["待实验", "bg-sky-100 text-sky-700"],
    done: ["已实验", "bg-emerald-100 text-emerald-700"],
    skipped: ["未实验", "bg-slate-100 text-slate-400"],
    excluded: ["排除", "bg-rose-100 text-rose-600"],
  };
  const [label, cls] = map[status] ?? [status, "bg-slate-100 text-slate-600"];
  return <span className={`badge ${cls}`}>{label}</span>;
}

const ADOPTED_FROM_LABEL: Record<string, string> = {
  leaderboard: "机器推荐（榜单采纳）",
  batch: "机器推荐（批次）",
  manual: "人类决策",
  init: "初始采样",
  import: "前置结果导入",
  csv_import: "CSV 结果导入",
};

function fmtDesc(prov: Provenance): string {
  const d = prov.descriptors ?? {};
  const enc = prov.encoding ?? {};
  const parts = Object.keys(enc).map((k) => {
    const file = d[k];
    const short = file ? file.split("__").pop() : null;
    return `${k}: ${enc[k]}${short ? `(${short})` : ""}`;
  });
  return parts.join("；");
}

/** Compact "来源" cell with an info icon revealing full adoption context. */
export function ProvenanceInfo({ prov }: { prov?: Provenance | null }) {
  if (!prov) return <span className="text-xs text-slate-300">—</span>;
  const from = ADOPTED_FROM_LABEL[prov.adopted_from ?? ""] ?? prov.adopted_from ?? "";
  const rows: [string, string][] = [];
  rows.push(["来源", from]);
  if (prov.acq_function) rows.push(["采集函数", prov.acq_function]);
  if (prov.rank != null) rows.push(["采纳时排名", `#${prov.rank}`]);
  if (prov.acq_score != null) rows.push(["采集得分", prov.acq_score.toFixed(4)]);
  if (prov.init_method) rows.push(["初始方法", prov.init_method]);
  if (prov.model) rows.push(["代理模型", prov.model]);
  const desc = fmtDesc(prov);
  if (desc) rows.push(["描述符", desc]);
  if (prov.rule_overrides?.length) rows.push(["规则覆盖", prov.rule_overrides.join(", ")]);
  if (prov.by) rows.push(["操作者", prov.by]);
  if (prov.at) rows.push(["时间", prov.at.replace("T", " ").slice(0, 19)]);

  return (
    <span className="group relative inline-flex items-center">
      <span className="flex h-4 w-4 cursor-help items-center justify-center rounded-full bg-slate-100 text-[10px] font-bold text-slate-500 hover:bg-slate-200">
        i
      </span>
      <div className="pointer-events-none absolute left-5 top-0 z-30 hidden w-72 rounded-lg border border-slate-200 bg-white p-3 text-xs shadow-lg group-hover:block">
        <div className="mb-1 font-semibold text-slate-700">采纳来源与背景</div>
        <table className="w-full">
          <tbody>
            {rows.map(([k, v]) => (
              <tr key={k} className="align-top">
                <td className="whitespace-nowrap py-0.5 pr-2 text-slate-400">{k}</td>
                <td className="py-0.5 text-slate-700 break-words">{v}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </span>
  );
}

export function EmptyState({ title, hint }: { title: string; hint?: string }) {
  return (
    <div className="flex flex-col items-center justify-center py-16 text-center">
      <div className="text-slate-400 text-sm font-medium">{title}</div>
      {hint && <div className="text-slate-300 text-xs mt-1">{hint}</div>}
    </div>
  );
}
