import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  ScatterChart, Scatter, ReferenceLine, ZAxis, Legend,
} from "recharts";
import { api } from "../api/client";
import type { Analytics as AnalyticsData, PredictResult } from "../api/types";
import { Spinner, EmptyState } from "../components/ui";

export default function Analytics() {
  const { id } = useParams();
  const [data, setData] = useState<AnalyticsData | null>(null);
  const [options, setOptions] = useState<Record<string, (string | number)[]>>({});

  useEffect(() => {
    if (id) {
      api.getAnalytics(id).then(setData);
      api.getComponents(id).then((r) => setOptions(r.components)).catch(() => {});
    }
  }, [id]);

  if (!data)
    return (
      <div className="flex justify-center py-20 text-slate-400">
        <Spinner className="h-6 w-6" />
      </div>
    );

  if (data.n_experiments === 0)
    return <EmptyState title="还没有实验数据" hint="完成一轮实验后即可查看分析" />;

  const roundScatter = data.rounds.flatMap((r) =>
    r.values.map((v) => ({ round: r.round_index, value: v }))
  );
  const reg = data.regression;
  const regPoints = reg
    ? reg.predicted.map((p, i) => ({ x: p, y: reg.observed[i] }))
    : [];
  const regMin = reg ? Math.min(...reg.predicted, ...reg.observed) : 0;
  const regMax = reg ? Math.max(...reg.predicted, ...reg.observed) : 1;

  return (
    <div>
      <div className="mb-6 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <h1 className="text-2xl font-bold text-slate-900">分析面板</h1>
          <Link className="btn-ghost" to={`/projects/${id}`}>工作台</Link>
          <Link className="btn-ghost" to={`/projects/${id}/history`}>历史与修正</Link>
        </div>
        <div className="flex gap-6 text-sm">
          <Metric label="实验总数" value={data.n_experiments} />
          <Metric
            label={`最优 ${data.target}`}
            value={data.best_value != null ? data.best_value.toFixed(2) : "-"}
          />
          <Metric label="模型 R²" value={reg?.r2 != null ? reg.r2.toFixed(3) : "-"} />
        </div>
      </div>

      {id && Object.keys(options).length > 0 && (
        <PredictPanel projectId={id} options={options} target={data.target} />
      )}

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <Panel title="收敛曲线（按轮次 · 累计最优）">
          <ResponsiveContainer width="100%" height={280}>
            <LineChart data={data.convergence_rounds} margin={{ top: 10, right: 20, bottom: 10, left: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#eef2f7" />
              <XAxis dataKey="round_index" tick={{ fontSize: 12 }} allowDecimals={false}
                label={{ value: "轮次", position: "insideBottom", offset: -2, fontSize: 12 }} />
              <YAxis tick={{ fontSize: 12 }} />
              <Tooltip />
              <Legend wrapperStyle={{ fontSize: 12 }} />
              <Line type="stepAfter" dataKey="cumulative_best" stroke="#1a6bf0" strokeWidth={2} dot={{ r: 3 }} name="累计最优" />
            </LineChart>
          </ResponsiveContainer>
        </Panel>

        <Panel title="预测 vs 实测">
          {reg ? (
            <ResponsiveContainer width="100%" height={280}>
              <ScatterChart margin={{ top: 10, right: 20, bottom: 10, left: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#eef2f7" />
                <XAxis type="number" dataKey="x" name="预测" tick={{ fontSize: 12 }}
                  domain={[regMin, regMax]} label={{ value: "预测", position: "insideBottom", offset: -2, fontSize: 12 }} />
                <YAxis type="number" dataKey="y" name="实测" tick={{ fontSize: 12 }}
                  domain={[regMin, regMax]} />
                <ZAxis range={[50, 50]} />
                <Tooltip cursor={{ strokeDasharray: "3 3" }} />
                <ReferenceLine
                  segment={[{ x: regMin, y: regMin }, { x: regMax, y: regMax }]}
                  stroke="#94a3b8"
                  strokeDasharray="4 4"
                />
                <Scatter data={regPoints} fill="#1a6bf0" fillOpacity={0.6} />
              </ScatterChart>
            </ResponsiveContainer>
          ) : (
            <EmptyState title="模型尚未训练" hint="运行一轮 BO 后可见" />
          )}
        </Panel>

        <Panel title="各轮产率分布">
          <ResponsiveContainer width="100%" height={280}>
            <ScatterChart margin={{ top: 10, right: 20, bottom: 10, left: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#eef2f7" />
              <XAxis type="number" dataKey="round" name="轮次" tick={{ fontSize: 12 }}
                allowDecimals={false} label={{ value: "轮次", position: "insideBottom", offset: -2, fontSize: 12 }} />
              <YAxis type="number" dataKey="value" name={data.target} tick={{ fontSize: 12 }} />
              <Tooltip cursor={{ strokeDasharray: "3 3" }} />
              <Scatter data={roundScatter} fill="#7c3aed" fillOpacity={0.6} />
            </ScatterChart>
          </ResponsiveContainer>
        </Panel>

        <Panel title={`最优实验 Top ${Math.min(10, data.top.length)}`}>
          <div className="overflow-auto max-h-[280px]">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-xs text-slate-500 sticky top-0">
                <tr>
                  <th className="px-3 py-2 text-left">{data.target}</th>
                  <th className="px-3 py-2 text-left">来源</th>
                  {data.top[0] &&
                    Object.keys(data.top[0].components).map((k) => (
                      <th key={k} className="px-3 py-2 text-left">{k}</th>
                    ))}
                </tr>
              </thead>
              <tbody>
                {data.top.map((t, i) => (
                  <tr key={i} className="border-t border-slate-100">
                    <td className="px-3 py-2 font-semibold text-emerald-600">
                      {t.observed_value.toFixed(2)}
                    </td>
                    <td className="px-3 py-2 text-xs text-slate-500">
                      {t.source === "machine" ? "机器" : "人类"}
                    </td>
                    {Object.values(t.components).map((v, j) => (
                      <td key={j} className="px-3 py-2">{String(v)}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
      </div>
    </div>
  );
}

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="card p-5">
      <h3 className="mb-3 font-semibold text-slate-700">{title}</h3>
      {children}
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="text-center">
      <div className="text-xl font-bold text-slate-900">{value}</div>
      <div className="text-xs text-slate-400">{label}</div>
    </div>
  );
}

function PredictPanel({
  projectId,
  options,
  target,
}: {
  projectId: string;
  options: Record<string, (string | number)[]>;
  target: string;
}) {
  const keys = Object.keys(options);
  const [sel, setSel] = useState<Record<string, string>>(
    Object.fromEntries(keys.map((k) => [k, String(options[k][0])]))
  );
  const [result, setResult] = useState<PredictResult | null>(null);
  const [busy, setBusy] = useState(false);

  const predict = async () => {
    setBusy(true);
    setResult(null);
    try {
      const components = Object.fromEntries(
        keys.map((k) => {
          const opt = options[k].find((o) => String(o) === sel[k]);
          return [k, opt ?? sel[k]];
        })
      );
      setResult(await api.predict(projectId, components));
    } catch (e) {
      setResult({ ok: false, error: String(e) });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="card mb-6 p-5">
      <h3 className="mb-1 font-semibold text-slate-700">产率预测</h3>
      <p className="mb-4 text-sm text-slate-500">
        选择一组反应条件，调用已训练的模型预测 {target} 及置信度（±1σ）。
      </p>
      <div className="flex flex-wrap items-end gap-3">
        {keys.map((k) => (
          <div key={k}>
            <label className="label">{k}</label>
            <select
              className="input max-w-[220px]"
              value={sel[k]}
              onChange={(e) => setSel((s) => ({ ...s, [k]: e.target.value }))}
            >
              {options[k].map((o) => (
                <option key={String(o)} value={String(o)}>{String(o)}</option>
              ))}
            </select>
          </div>
        ))}
        <button className="btn-primary" onClick={predict} disabled={busy}>
          {busy && <Spinner />} 预测
        </button>
      </div>
      {result && (
        <div className="mt-4">
          {result.ok ? (
            <div className="flex items-baseline gap-4 rounded-lg bg-slate-50 px-4 py-3">
              <span className="text-sm text-slate-500">预测 {target}</span>
              <span className="text-2xl font-bold text-brand-700">
                {result.mean!.toFixed(2)}
              </span>
              <span className="text-slate-400">
                ± {result.std!.toFixed(2)}（1σ）
              </span>
              <span className="text-xs text-slate-400">
                95% 置信区间约 [{(result.mean! - 1.96 * result.std!).toFixed(1)},{" "}
                {(result.mean! + 1.96 * result.std!).toFixed(1)}]
              </span>
            </div>
          ) : (
            <div className="rounded-lg bg-rose-50 px-4 py-3 text-sm text-rose-600">
              {result.error}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
