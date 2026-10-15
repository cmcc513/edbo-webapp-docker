import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, pollTask } from "../api/client";
import type { Project, Proposal, RecommendItem, PriorExperiment } from "../api/types";
import { Spinner, StatusBadge, SourceBadge, ExpStatusBadge, EmptyState, ProvenanceInfo } from "../components/ui";
import RulesEditor from "../components/RulesEditor";
import ImportPanel from "../components/ImportPanel";

export default function Workbench() {
  const { id } = useParams();
  const [project, setProject] = useState<Project | null>(null);
  const [proposals, setProposals] = useState<Proposal[]>([]);
  const [options, setOptions] = useState<Record<string, (string | number)[]>>({});
  const [busyMsg, setBusyMsg] = useState("");
  const [showRules, setShowRules] = useState(false);

  const refresh = useCallback(async () => {
    if (!id) return;
    const p = await api.getProject(id);
    setProject(p);
    if (p.current_round >= 0) {
      setProposals(await api.getProposals(id));
      try {
        setOptions((await api.getComponents(id)).components);
      } catch {
        /* space not built */
      }
    }
  }, [id]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  if (!project) {
    return (
      <div className="flex justify-center py-20 text-slate-400">
        <Spinner className="h-6 w-6" />
      </div>
    );
  }

  const busy = ["building", "training", "sampling"].includes(project.status);

  return (
    <div>
      <div className="mb-6 flex items-center justify-between">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-bold text-slate-900">{project.name}</h1>
            <StatusBadge status={project.status} />
          </div>
          <p className="text-sm text-slate-500">
            {project.current_round < 0
              ? "尚未初始化"
              : `第 ${project.current_round} 轮 · 目标 ${project.target}（${
                  project.direction === "max" ? "最大化" : "最小化"
                }）· 已实验 ${project.n_experiments} 个`}
          </p>
        </div>
        <div className="flex gap-2">
          <Link className="btn-ghost" to={`/projects/${project.id}/history`}>历史与修正</Link>
          <Link className="btn-ghost" to={`/projects/${project.id}/descriptors`}>修改配置</Link>
          <Link className="btn-ghost" to={`/projects/${project.id}/analytics`}>分析面板</Link>
        </div>
      </div>

      {busy && (
        <div className="card mb-6 flex items-center gap-3 border-amber-200 bg-amber-50 p-4 text-amber-700">
          <Spinner /> 正在处理（{project.status}）… {busyMsg}
        </div>
      )}

      {project.current_round < 0 ? (
        <InitPanel projectId={project.id} target={project.target} pendingPrior={project.pending_prior ?? 0} onDone={refresh} setBusyMsg={setBusyMsg} />
      ) : (
        <div className="space-y-6">
          <RunList
            projectId={project.id}
            round={project.current_round}
            experiments={proposals}
            target={project.target}
            busy={busy}
            onChanged={refresh}
            setBusyMsg={setBusyMsg}
          />

          <Leaderboard
            projectId={project.id}
            round={project.current_round}
            inList={new Set(proposals.map((p) => p.domain_index))}
            onAdopted={refresh}
          />

          <HumanDecision
            projectId={project.id}
            round={project.current_round}
            options={options}
            target={project.target}
            onAdded={refresh}
          />

          <div className="card p-5">
            <button
              className="flex w-full items-center justify-between text-left"
              onClick={() => setShowRules((s) => !s)}
            >
              <h3 className="font-semibold text-slate-700">条件排除规则</h3>
              <span className="text-slate-400">{showRules ? "▲" : "▼ 展开设置"}</span>
            </button>
            {showRules && Object.keys(options).length > 0 && (
              <div className="mt-4">
                <RulesEditor projectId={project.id} options={options} />
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

// ----------------------------------------------------------------- Init panel
function InitPanel({
  projectId,
  target,
  pendingPrior,
  onDone,
  setBusyMsg,
}: {
  projectId: string;
  target: string;
  pendingPrior: number;
  onDone: () => void;
  setBusyMsg: (s: string) => void;
}) {
  const [tab, setTab] = useState<"sample" | "import">(pendingPrior > 0 ? "import" : "sample");
  const [seed, setSeed] = useState("0");
  const [batch, setBatch] = useState(5);
  const [method, setMethod] = useState("rand");
  const [busy, setBusy] = useState(false);
  const [options, setOptions] = useState<Record<string, (string | number)[]>>({});

  useEffect(() => {
    api.getComponents(projectId).then((r) => setOptions(r.components)).catch(() => {});
  }, [projectId]);

  const runInit = async (payload: Parameters<typeof api.init>[1]) => {
    setBusy(true);
    try {
      const { task_id } = await api.init(projectId, payload);
      const t = await pollTask(projectId, task_id, (t) => setBusyMsg(t.message ?? ""));
      if (t.status === "error") alert(t.error);
      else if (t.message) setBusyMsg("");
      onDone();
    } finally {
      setBusy(false);
      setBusyMsg("");
    }
  };

  const sampleInit = () =>
    runInit({ seed: seed === "" ? null : Number(seed), batch_size: batch, init_method: method });
  const importInit = (prior: PriorExperiment[]) =>
    runInit({ seed: 0, batch_size: 0, init_method: "import", prior_experiments: prior });

  const importPending = async () => {
    const prior = await api.getPendingPrior(projectId);
    if (prior.length === 0) {
      alert("没有可导入的原项目结果。");
      return;
    }
    importInit(prior);
  };

  return (
    <div className="card max-w-2xl p-6">
      <h3 className="font-semibold mb-1">初始化优化</h3>
      <p className="text-sm text-slate-500 mb-4">
        选择起点：用采样方法生成首批待做实验，或导入已有的前置实验结果直接训练模型。
      </p>

      {pendingPrior > 0 && (
        <div className="mb-4 flex items-center justify-between rounded-lg border border-brand-200 bg-brand-50 px-4 py-3">
          <div className="text-sm text-brand-800">
            检测到从原项目复制的 <b>{pendingPrior}</b> 条实验结果，可一键导入并训练模型。
            <span className="text-brand-500">（不在新空间内的条件会自动跳过）</span>
          </div>
          <button className="btn-primary" onClick={importPending} disabled={busy}>
            {busy && <Spinner />} 一键导入
          </button>
        </div>
      )}
      <div className="mb-4 flex gap-2">
        <TabBtn active={tab === "sample"} onClick={() => setTab("sample")}>采样生成首批</TabBtn>
        <TabBtn active={tab === "import"} onClick={() => setTab("import")}>导入前置实验结果</TabBtn>
      </div>

      {tab === "sample" ? (
        <div>
          <div className="grid grid-cols-3 gap-3">
            <div>
              <label className="label">批次大小</label>
              <input type="number" className="input" value={batch} onChange={(e) => setBatch(Number(e.target.value))} />
            </div>
            <div>
              <label className="label">初始化方法</label>
              <select className="input" value={method} onChange={(e) => setMethod(e.target.value)}>
                <option value="rand">随机</option>
                <option value="pam">pam</option>
                <option value="kmeans">kmeans</option>
              </select>
            </div>
            <div>
              <label className="label">随机种子</label>
              <input className="input" value={seed} onChange={(e) => setSeed(e.target.value)} />
            </div>
          </div>
          <button className="btn-primary mt-5" onClick={sampleInit} disabled={busy}>
            {busy && <Spinner />} 生成初始实验
          </button>
        </div>
      ) : Object.keys(options).length > 0 ? (
        <ImportPanel projectId={projectId} options={options} target={target} onSubmit={importInit} busy={busy} />
      ) : (
        <EmptyState title="组分信息加载中…" />
      )}
    </div>
  );
}

// -------------------------------------------------------------- Run list
function RunList({
  projectId,
  round,
  experiments,
  target,
  busy,
  onChanged,
  setBusyMsg,
}: {
  projectId: string;
  round: number;
  experiments: Proposal[];
  target: string;
  busy: boolean;
  onChanged: () => void;
  setBusyMsg: (s: string) => void;
}) {
  const [values, setValues] = useState<Record<string, string>>({});
  const [working, setWorking] = useState(false);

  useEffect(() => {
    const init: Record<string, string> = {};
    experiments.forEach((e) => {
      init[e.id] = e.observed_value != null ? String(e.observed_value) : "";
    });
    setValues(init);
  }, [experiments]);

  const compKeys = experiments.length ? Object.keys(experiments[0].components) : [];

  const saveAll = async () => {
    setWorking(true);
    try {
      for (const e of experiments) {
        const v = values[e.id]?.trim() ?? "";
        const orig = e.observed_value != null ? String(e.observed_value) : "";
        if (v !== "" && v !== orig) {
          await api.editExperiment(projectId, e.id, { observed_value: Number(v) });
        }
      }
      onChanged();
    } finally {
      setWorking(false);
    }
  };

  const remove = async (e: Proposal) => {
    await api.deleteExperiment(projectId, e.id);
    onChanged();
  };
  const startNewRound = async () => {
    if (!confirm("结算本轮并开始新一轮？本轮未录入结果的实验将被标记为未实验。")) return;
    setWorking(true);
    try {
      const r = await api.newRound(projectId);
      setBusyMsg(`已进入第 ${r.round_index} 轮`);
      onChanged();
    } finally {
      setWorking(false);
      setTimeout(() => setBusyMsg(""), 1500);
    }
  };

  const nProposed = experiments.filter((e) => e.status === "proposed").length;
  const nDone = experiments.filter((e) => e.status === "done").length;

  return (
    <div className="card overflow-hidden">
      <div className="flex items-center justify-between border-b border-slate-100 px-5 py-3">
        <div>
          <h3 className="font-semibold text-slate-700">本轮实验列表（第 {round} 轮）</h3>
          <p className="text-xs text-slate-500">
            待实验 {nProposed} · 已实验 {nDone}。条件来自下方“推荐榜单采纳”与“人类决策”。做完填入产率并保存。
          </p>
        </div>
        <div className="flex gap-2">
          <button className="btn-ghost" onClick={saveAll} disabled={working || busy}>
            {working && <Spinner />} 保存产率
          </button>
          <button className="btn-primary" onClick={startNewRound} disabled={working || busy}>
            结算本轮 → 新一轮
          </button>
        </div>
      </div>

      {experiments.length === 0 ? (
        <EmptyState title="本轮还没有实验" hint="从下方推荐榜单采纳，或用人类决策添加" />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-xs text-slate-500">
              <tr>
                <th className="px-4 py-2 text-left">来源</th>
                {compKeys.map((k) => <th key={k} className="px-4 py-2 text-left">{k}</th>)}
                <th className="px-4 py-2 text-left">预测</th>
                <th className="px-4 py-2 text-left">状态</th>
                <th className="px-4 py-2 text-left">实测 {target}</th>
                <th className="px-4 py-2"></th>
              </tr>
            </thead>
            <tbody>
              {experiments.map((e) => (
                <tr key={e.id} className="border-t border-slate-100">
                  <td className="px-4 py-2">
                    <div className="flex items-center gap-1.5">
                      <SourceBadge source={e.source} />
                      <ProvenanceInfo prov={e.provenance} />
                    </div>
                  </td>
                  {compKeys.map((k) => <td key={k} className="px-4 py-2">{String(e.components[k])}</td>)}
                  <td className="px-4 py-2 text-slate-500">
                    {e.predicted_mean != null
                      ? `${e.predicted_mean.toFixed(1)}${e.predicted_var != null ? ` ±${Math.sqrt(e.predicted_var).toFixed(1)}` : ""}`
                      : "-"}
                  </td>
                  <td className="px-4 py-2"><ExpStatusBadge status={e.status} /></td>
                  <td className="px-4 py-2">
                    <input
                      className="input w-24"
                      placeholder="—"
                      value={values[e.id] ?? ""}
                      onChange={(ev) => setValues((v) => ({ ...v, [e.id]: ev.target.value }))}
                    />
                  </td>
                  <td className="px-4 py-2 text-right whitespace-nowrap">
                    {e.status === "proposed" && (
                      <button className="text-xs text-slate-400 hover:text-rose-500" onClick={() => remove(e)}>移除</button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// -------------------------------------------------------------- Leaderboard
const ACQ_OPTS = [
  { v: "EI", label: "EI 期望提升（平衡）" },
  { v: "PI", label: "PI 提升概率（偏利用）" },
  { v: "UCB", label: "UCB 置信上界（偏探索）" },
  { v: "MeanMax", label: "MeanMax 纯利用（最高预测）" },
  { v: "VarMax", label: "VarMax 纯探索（最高不确定）" },
];

function Leaderboard({
  projectId,
  round,
  inList,
  onAdopted,
}: {
  projectId: string;
  round: number;
  inList: Set<number>;
  onAdopted: () => void;
}) {
  const [acq, setAcq] = useState("EI");
  const [topN, setTopN] = useState(15);
  const [items, setItems] = useState<RecommendItem[]>([]);
  const [reason, setReason] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [sel, setSel] = useState<Set<number>>(new Set());

  const load = useCallback(async () => {
    setLoading(true);
    setSel(new Set());
    try {
      const r = await api.getRecommendations(projectId, { acq_function: acq, top_n: topN });
      setItems(r.items);
      setReason(r.ok ? null : r.reason ?? "无法生成推荐");
    } finally {
      setLoading(false);
    }
  }, [projectId, acq, topN]);

  useEffect(() => {
    load();
  }, [load]);

  const compKeys = items.length ? Object.keys(items[0].components) : [];
  const toggle = (di: number) =>
    setSel((s) => {
      const n = new Set(s);
      n.has(di) ? n.delete(di) : n.add(di);
      return n;
    });

  const adopt = async (indices: number[]) => {
    if (indices.length === 0) return;
    const chosen = indices.map((di) => {
      const i = items.findIndex((it) => it.domain_index === di);
      return {
        domain_index: di,
        rank: i >= 0 ? i + 1 : null,
        acq_score: i >= 0 ? items[i].acq_score ?? null : null,
      };
    });
    await api.adopt(projectId, round, chosen, { acq_function: acq });
    setItems((its) => its.filter((it) => !indices.includes(it.domain_index)));
    onAdopted();
  };

  return (
    <div className="card overflow-hidden">
      <div className="flex flex-wrap items-end gap-4 border-b border-slate-100 px-5 py-3">
        <div>
          <h3 className="font-semibold text-slate-700">推荐榜单</h3>
          <p className="text-xs text-slate-500">选择采集方法即实时刷新排名；从榜单采纳条件加入本轮。</p>
        </div>
        <div className="flex-1" />
        <div>
          <label className="label">采集方法</label>
          <select className="input w-56" value={acq} onChange={(e) => setAcq(e.target.value)}>
            {ACQ_OPTS.map((a) => <option key={a.v} value={a.v}>{a.label}</option>)}
          </select>
        </div>
        <div>
          <label className="label">数量</label>
          <input type="number" className="input w-20" value={topN} onChange={(e) => setTopN(Math.max(1, Number(e.target.value)))} />
        </div>
        <button className="btn-ghost" onClick={load} disabled={loading}>
          {loading && <Spinner />} 刷新
        </button>
        <button className="btn-primary" onClick={() => adopt([...sel])} disabled={sel.size === 0}>
          采纳选中（{sel.size}）
        </button>
      </div>

      {reason ? (
        <EmptyState title={reason} />
      ) : loading ? (
        <div className="flex justify-center py-10 text-slate-400"><Spinner className="h-6 w-6" /></div>
      ) : items.length === 0 ? (
        <EmptyState title="暂无可推荐条件" hint="可能都已在列表中或被规则排除" />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-xs text-slate-500">
              <tr>
                <th className="px-3 py-2"></th>
                <th className="px-3 py-2 text-left">#</th>
                {compKeys.map((k) => <th key={k} className="px-3 py-2 text-left">{k}</th>)}
                <th className="px-3 py-2 text-left">预测均值±σ</th>
                <th className="px-3 py-2 text-left">采集得分</th>
                <th className="px-3 py-2"></th>
              </tr>
            </thead>
            <tbody>
              {items.map((it, i) => {
                const already = inList.has(it.domain_index);
                return (
                  <tr key={it.domain_index} className="border-t border-slate-100">
                    <td className="px-3 py-2">
                      <input type="checkbox" checked={sel.has(it.domain_index)} onChange={() => toggle(it.domain_index)} disabled={already} />
                    </td>
                    <td className="px-3 py-2 text-slate-400">{i + 1}</td>
                    {compKeys.map((k) => <td key={k} className="px-3 py-2">{String(it.components[k])}</td>)}
                    <td className="px-3 py-2 font-medium text-brand-700">
                      {it.predicted_mean != null ? it.predicted_mean.toFixed(1) : "-"}
                      {it.predicted_var != null && <span className="text-slate-400"> ±{Math.sqrt(it.predicted_var).toFixed(1)}</span>}
                    </td>
                    <td className="px-3 py-2 text-slate-500">{it.acq_score != null ? it.acq_score.toFixed(3) : "-"}</td>
                    <td className="px-3 py-2 text-right">
                      {already ? (
                        <span className="text-xs text-slate-400">已在列表</span>
                      ) : (
                        <button className="text-xs font-medium text-brand-600 hover:text-brand-700" onClick={() => adopt([it.domain_index])}>采纳</button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// -------------------------------------------------------------- Human decision
function HumanDecision({
  projectId,
  round,
  options,
  target,
  onAdded,
}: {
  projectId: string;
  round: number;
  options: Record<string, (string | number)[]>;
  target: string;
  onAdded: () => void;
}) {
  const keys = Object.keys(options);
  const emptyRow = () => ({ ...Object.fromEntries(keys.map((k) => [k, ""])), __v: "" }) as Record<string, string>;
  const [rows, setRows] = useState<Record<string, string>[]>([emptyRow()]);
  const [busy, setBusy] = useState(false);

  if (keys.length === 0) return null;

  const submit = async () => {
    const payload = rows
      .filter((r) => keys.every((k) => r[k] !== ""))
      .map((r) => ({
        components: Object.fromEntries(
          keys.map((k) => {
            const opt = options[k].find((o) => String(o) === r[k]);
            return [k, opt ?? r[k]];
          })
        ),
        observed_value: r.__v.trim() === "" ? null : Number(r.__v),
      }));
    if (payload.length === 0) return;
    setBusy(true);
    try {
      const res = await api.addHumanConditions(projectId, round, payload);
      if (res.rejected.length > 0) alert(`${res.rejected.length} 条组合不在反应空间内，已拒绝。`);
      if (res.warnings.length > 0)
        alert(`注意：${res.warnings.length} 条命中排除规则（已按人工决策保留）。`);
      setRows([emptyRow()]);
      onAdded();
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="card overflow-hidden">
      <div className="border-b border-slate-100 px-5 py-3">
        <h3 className="font-semibold text-slate-700">人类决策</h3>
        <p className="text-xs text-slate-500">自行挑选反应条件加入本轮。产率可留空（做完后在上方列表录入）。</p>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-xs text-slate-500">
            <tr>
              {keys.map((k) => <th key={k} className="px-4 py-2 text-left">{k}</th>)}
              <th className="px-4 py-2 text-left">{target}（可选）</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row, ri) => (
              <tr key={ri} className="border-t border-slate-100">
                {keys.map((k) => (
                  <td key={k} className="px-4 py-2">
                    <select
                      className="input"
                      value={row[k]}
                      onChange={(e) => setRows((rs) => rs.map((r, j) => (j === ri ? { ...r, [k]: e.target.value } : r)))}
                    >
                      <option value="">选择…</option>
                      {options[k].map((o) => <option key={String(o)} value={String(o)}>{String(o)}</option>)}
                    </select>
                  </td>
                ))}
                <td className="px-4 py-2">
                  <input
                    className="input w-24"
                    value={row.__v}
                    onChange={(e) => setRows((rs) => rs.map((r, j) => (j === ri ? { ...r, __v: e.target.value } : r)))}
                  />
                </td>
                <td className="px-2">
                  {rows.length > 1 && (
                    <button className="text-slate-400 hover:text-rose-500" onClick={() => setRows((rs) => rs.filter((_, j) => j !== ri))}>×</button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="flex justify-between border-t border-slate-100 px-5 py-3">
        <button className="btn-ghost" onClick={() => setRows((rs) => [...rs, emptyRow()])}>+ 新增行</button>
        <button className="btn-primary" onClick={submit} disabled={busy}>
          {busy && <Spinner />} 加入本轮
        </button>
      </div>
    </div>
  );
}

function TabBtn({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      className={`rounded-lg px-4 py-2 text-sm font-medium ${
        active ? "bg-brand-600 text-white" : "bg-white border border-slate-200 text-slate-600"
      }`}
      onClick={onClick}
    >
      {children}
    </button>
  );
}
