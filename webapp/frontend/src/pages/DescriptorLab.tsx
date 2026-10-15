import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  ScatterChart, Scatter, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, ReferenceLine,
} from "recharts";
import { api, pollTask } from "../api/client";
import type {
  ComponentSpec, EncodingType, Project, WhatIfResult, RegressionData,
} from "../api/types";
import { Spinner, EmptyState } from "../components/ui";
import DescriptorBuilder from "../components/DescriptorBuilder";

type CompType = "categorical" | "smiles" | "numeric";

interface LabComponent {
  name: string;
  type: CompType;
  values: (string | number)[];
  encoding: EncodingType;
  descriptor_file?: string | null;
  id_column?: string | null;
}

const ENCODINGS_FOR: Record<CompType, EncodingType[]> = {
  categorical: ["ohe", "descriptor"],
  smiles: ["mordred", "ohe", "descriptor"],
  numeric: ["numeric"],
};
const ENC_LABEL: Record<EncodingType, string> = {
  ohe: "独热 (ohe)",
  numeric: "数值 (numeric)",
  mordred: "Mordred",
  resolve: "名称解析",
  descriptor: "描述符",
};
function inferType(encoding: EncodingType): CompType {
  if (encoding === "numeric") return "numeric";
  if (encoding === "mordred" || encoding === "resolve" || encoding === "descriptor") return "smiles";
  return "categorical";
}

export default function DescriptorLab() {
  const { id } = useParams();
  const [project, setProject] = useState<Project | null>(null);
  const [comps, setComps] = useState<LabComponent[]>([]);
  const [model, setModel] = useState("GP");
  const [initMethod, setInitMethod] = useState("rand");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<WhatIfResult | null>(null);
  const [applyMsg, setApplyMsg] = useState("");

  useEffect(() => {
    if (!id) return;
    api.getProject(id).then(setProject);
    api.getConfig(id).then((cfg) => {
      setComps(cfg.components.map((c) => ({
        name: c.name, type: inferType(c.encoding), values: c.values,
        encoding: c.encoding, descriptor_file: c.descriptor_file, id_column: c.id_column,
      })));
      setModel(cfg.model);
      setInitMethod(cfg.init_method);
    });
  }, [id]);

  const toSpec = (): ComponentSpec[] =>
    comps.map((c) => ({
      name: c.name, values: c.values, encoding: c.encoding,
      descriptor_file: c.descriptor_file, id_column: c.id_column,
    }));

  // Signature of the current config so the live preview re-runs on any change.
  const specSig = JSON.stringify({ comps, model });

  useEffect(() => {
    if (!id || comps.length === 0) return;
    let cancelled = false;
    setBusy(true);
    const handle = setTimeout(async () => {
      try {
        const r = await api.whatifDescriptors(id, toSpec(), { model, init_method: initMethod });
        if (!cancelled) setResult(r);
      } catch (e) {
        if (!cancelled) setResult({ ok: false, n_obs: 0, error: String(e) });
      } finally {
        if (!cancelled) setBusy(false);
      }
    }, 600);
    return () => {
      cancelled = true;
      clearTimeout(handle);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id, specSig, initMethod]);

  const apply = async () => {
    if (!id) return;
    if (!confirm("将当前描述符配置永久应用到该项目并重新训练？历史实验与推荐会保留。")) return;
    setBusy(true);
    try {
      const { task_id } = await api.applyDescriptors(id, toSpec(), { model, init_method: initMethod });
      const t = await pollTask(id, task_id, (t) => setApplyMsg(t.message ?? ""));
      setApplyMsg(t.status === "done" ? "已应用。" : t.error ?? "应用失败");
      api.getProject(id).then(setProject);
    } finally {
      setBusy(false);
      setTimeout(() => setApplyMsg(""), 3000);
    }
  };

  if (!project) {
    return <div className="flex justify-center py-20 text-slate-400"><Spinner className="h-6 w-6" /></div>;
  }
  if (comps.length === 0) {
    return <EmptyState title="尚未配置反应空间" hint="请先构建空间后再来做描述符实验" />;
  }

  return (
    <div>
      <div className="mb-6 flex items-center gap-3">
        <h1 className="text-2xl font-bold text-slate-900">修改配置</h1>
        <Link className="btn-ghost" to={`/projects/${id}`}>工作台</Link>
        <Link className="btn-ghost" to={`/projects/${id}/analytics`}>分析面板</Link>
      </div>
      <p className="mb-4 text-sm text-slate-500">
        修改各组分的编码/描述符，右侧会实时显示对模型拟合（R² 与预测-实测图）的影响。
        确认满意后点「应用」，会重建空间并用已有结果重新训练，历史实验与推荐保持不变。
      </p>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <div className="space-y-3 lg:col-span-2">
          {comps.map((c, i) => (
            <CompRow
              key={i}
              projectId={id!}
              comp={c}
              onChange={(nc) => setComps((cs) => cs.map((x, j) => (j === i ? nc : x)))}
            />
          ))}
          <div className="card flex items-center gap-3 p-4">
            <div>
              <label className="label">代理模型</label>
              <select className="input w-44" value={model} onChange={(e) => setModel(e.target.value)}>
                <option value="GP">高斯过程 (GP)</option>
                <option value="RF">随机森林 (RF)</option>
                <option value="Bayesian_Linear">贝叶斯线性</option>
              </select>
            </div>
            <div className="flex-1" />
            {busy && <span className="flex items-center gap-1 text-xs text-slate-400"><Spinner className="h-3 w-3" /> 实时计算中…</span>}
            <button className="btn-primary" onClick={apply} disabled={busy}>
              应用
            </button>
          </div>
          {applyMsg && <div className="text-sm text-slate-500">{applyMsg}</div>}
        </div>

        <div className="space-y-4">
          <ResultCard result={result} busy={busy} />
        </div>
      </div>
    </div>
  );
}

function CompRow({
  projectId,
  comp,
  onChange,
}: {
  projectId: string;
  comp: LabComponent;
  onChange: (c: LabComponent) => void;
}) {
  const [builderOpen, setBuilderOpen] = useState(false);

  return (
    <div className="card p-4">
      <div className="flex items-center justify-between">
        <div className="font-medium text-slate-800">{comp.name}</div>
        <span className="text-xs text-slate-400">{comp.values.length} 个取值 · {comp.type}</span>
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-3">
        <div>
          <label className="label">编码方式</label>
          <select
            className="input w-40"
            value={comp.encoding}
            onChange={(e) => onChange({ ...comp, encoding: e.target.value as EncodingType })}
          >
            {ENCODINGS_FOR[comp.type].map((enc) => (
              <option key={enc} value={enc}>{ENC_LABEL[enc]}</option>
            ))}
          </select>
        </div>
        {comp.encoding === "descriptor" && (
          <div className="flex items-center gap-2 pt-5">
            <button className="btn-ghost" onClick={() => setBuilderOpen(true)}>定制 / 导入描述符</button>
            {comp.descriptor_file && (
              <span className="text-xs text-emerald-600">✓ {comp.descriptor_file.split("__").pop()}</span>
            )}
          </div>
        )}
      </div>

      {builderOpen && (
        <DescriptorBuilder
          projectId={projectId}
          componentName={comp.name}
          identifiers={comp.values.map((v) => String(v))}
          onSaved={(filename, idColumn) => {
            onChange({ ...comp, descriptor_file: filename, id_column: idColumn, encoding: "descriptor" });
            setBuilderOpen(false);
          }}
          onClose={() => setBuilderOpen(false)}
        />
      )}
    </div>
  );
}

function pack(reg: RegressionData | null | undefined) {
  return (reg?.observed ?? []).map((o, i) => ({ observed: o, predicted: reg!.predicted[i] }));
}

function ParityChart({
  title, points, color, lo, hi, r2,
}: {
  title: string;
  points: { observed: number; predicted: number }[];
  color: string;
  lo: number;
  hi: number;
  r2: number | null | undefined;
}) {
  return (
    <div>
      <div className="mb-1 flex items-baseline justify-between">
        <span className="text-sm font-medium text-slate-600">{title}</span>
        <span className="text-sm font-semibold text-slate-700">R² = {r2 != null ? r2.toFixed(3) : "-"}</span>
      </div>
      <div className="h-56">
        <ResponsiveContainer width="100%" height="100%">
          <ScatterChart margin={{ top: 5, right: 10, bottom: 15, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis type="number" dataKey="observed" name="实测" domain={[lo, hi]}
              tick={{ fontSize: 11 }} label={{ value: "实测", position: "insideBottom", offset: -8, fontSize: 11 }} />
            <YAxis type="number" dataKey="predicted" name="预测" domain={[lo, hi]}
              tick={{ fontSize: 11 }} label={{ value: "预测", angle: -90, position: "insideLeft", fontSize: 11 }} />
            <Tooltip />
            <ReferenceLine segment={[{ x: lo, y: lo }, { x: hi, y: hi }]} stroke="#cbd5e1" />
            <Scatter name={title} data={points} fill={color} />
          </ScatterChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

function ResultCard({ result, busy }: { result: WhatIfResult | null; busy: boolean }) {
  const data = useMemo(() => {
    if (!result?.ok) return { before: [], after: [] };
    return { before: pack(result.current), after: pack(result.whatif) };
  }, [result]);

  if (!result && busy) return <div className="card p-6"><div className="flex justify-center text-slate-400"><Spinner className="h-6 w-6" /></div></div>;
  if (!result) return <div className="card p-6 text-sm text-slate-400">修改左侧配置，这里会实时显示对模型拟合的影响。</div>;
  if (!result.ok) return <div className="card p-6 text-sm text-rose-600">{result.error}</div>;

  const curR2 = result.current?.r2;
  const wR2 = result.whatif?.r2;
  const allPts = [...data.before, ...data.after];
  const lo = allPts.length ? Math.min(...allPts.map((p) => p.observed)) : 0;
  const hi = allPts.length ? Math.max(...allPts.map((p) => p.observed)) : 100;

  return (
    <div className="card space-y-4 p-5">
      <div>
        <h3 className="font-semibold text-slate-700">拟合对比</h3>
        <p className="text-xs text-slate-400">基于 {result.n_obs} 个已完成实验 · 新空间 {result.space_size} 点</p>
      </div>
      {wR2 != null && curR2 != null && (
        <div className={`text-center text-sm ${wR2 >= curR2 ? "text-emerald-600" : "text-amber-600"}`}>
          {wR2 >= curR2 ? "↑ 拟合提升" : "↓ 拟合下降"} ΔR² = {(wR2 - curR2).toFixed(3)}
        </div>
      )}
      <ParityChart title="修改前" points={data.before} color="#94a3b8" lo={lo} hi={hi} r2={curR2} />
      <div className="border-t border-slate-100" />
      <ParityChart title="修改后" points={data.after} color="#6366f1" lo={lo} hi={hi} r2={wR2} />
    </div>
  );
}
