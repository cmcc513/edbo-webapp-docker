import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import type { RoundSummary, Proposal } from "../api/types";
import { Spinner, SourceBadge, ExpStatusBadge, EmptyState, ProvenanceInfo } from "../components/ui";

export default function History() {
  const { id } = useParams();
  const [rounds, setRounds] = useState<RoundSummary[] | null>(null);
  const [target, setTarget] = useState("yield");
  const [open, setOpen] = useState<Record<number, boolean>>({});

  const refresh = useCallback(async () => {
    if (!id) return;
    const [rs, p] = await Promise.all([api.getRounds(id), api.getProject(id)]);
    setRounds(rs);
    setTarget(p.target);
    setOpen((o) => (Object.keys(o).length ? o : { [rs.length - 1]: true }));
  }, [id]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  if (!rounds)
    return (
      <div className="flex justify-center py-20 text-slate-400">
        <Spinner className="h-6 w-6" />
      </div>
    );

  if (rounds.length === 0)
    return <EmptyState title="尚无轮次" hint="初始化项目后即可在此追溯历史" />;

  return (
    <div>
      <div className="mb-6 flex items-center gap-3">
        <h1 className="text-2xl font-bold text-slate-900">历史与修正</h1>
        <Link className="btn-ghost" to={`/projects/${id}`}>工作台</Link>
        <Link className="btn-ghost" to={`/projects/${id}/analytics`}>分析面板</Link>
      </div>
      <p className="mb-4 text-sm text-slate-500">
        逐轮回看每一批实验的推荐、来源与录入结果。如发现填写错误可直接修正产率，
        修正后模型会用更正后的数据重新训练（已完成的历史轮次保持不变，仅影响后续推荐）。
      </p>

      <div className="space-y-3">
        {rounds.map((r) => (
          <RoundCard
            key={r.round_index}
            projectId={id!}
            round={r}
            target={target}
            open={!!open[r.round_index]}
            toggle={() =>
              setOpen((o) => ({ ...o, [r.round_index]: !o[r.round_index] }))
            }
            onEdited={refresh}
          />
        ))}
      </div>
    </div>
  );
}

function RoundCard({
  projectId,
  round,
  target,
  open,
  toggle,
  onEdited,
}: {
  projectId: string;
  round: RoundSummary;
  target: string;
  open: boolean;
  toggle: () => void;
  onEdited: () => void;
}) {
  const kindLabel = round.kind === "init" ? "初始批次" : "贝叶斯优化";
  return (
    <div className="card overflow-hidden">
      <button
        className="flex w-full items-center justify-between px-5 py-3 text-left hover:bg-slate-50"
        onClick={toggle}
      >
        <div className="flex items-center gap-3">
          <span className="font-semibold text-slate-800">第 {round.round_index} 轮</span>
          <span className="badge bg-slate-100 text-slate-600">{kindLabel}</span>
          {round.acq_function && (
            <span className="badge bg-brand-50 text-brand-700">{round.acq_function}</span>
          )}
        </div>
        <div className="flex items-center gap-4 text-xs text-slate-500">
          <span>机器 {round.n_machine} · 人类 {round.n_human}</span>
          <span>已实验 {round.n_done} · 未实验 {round.n_skipped}</span>
          <span className="font-medium text-emerald-600">
            本轮最优 {round.best_value != null ? round.best_value.toFixed(2) : "-"}
          </span>
          <span className="text-slate-400">{open ? "▲" : "▼"}</span>
        </div>
      </button>

      {open && (
        <div className="overflow-x-auto border-t border-slate-100">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-xs text-slate-500">
              <tr>
                <th className="px-4 py-2 text-left">来源</th>
                {Object.keys(round.experiments[0]?.components ?? {}).map((k) => (
                  <th key={k} className="px-4 py-2 text-left">{k}</th>
                ))}
                <th className="px-4 py-2 text-left">预测</th>
                <th className="px-4 py-2 text-left">状态</th>
                <th className="px-4 py-2 text-left">{target}（可修正）</th>
              </tr>
            </thead>
            <tbody>
              {round.experiments.map((e) => (
                <EditableRow
                  key={e.id}
                  projectId={projectId}
                  exp={e}
                  onEdited={onEdited}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function EditableRow({
  projectId,
  exp,
  onEdited,
}: {
  projectId: string;
  exp: Proposal;
  onEdited: () => void;
}) {
  const [val, setVal] = useState(
    exp.observed_value != null ? String(exp.observed_value) : ""
  );
  const [busy, setBusy] = useState(false);
  const compKeys = Object.keys(exp.components);
  const dirty = (exp.observed_value != null ? String(exp.observed_value) : "") !== val.trim();

  const save = async () => {
    setBusy(true);
    try {
      const res = await api.editExperiment(projectId, exp.id, {
        observed_value: val.trim() === "" ? null : Number(val),
      });
      if (res.retrained) {
        // brief hint via title; refresh reloads everything
      }
      onEdited();
    } finally {
      setBusy(false);
    }
  };

  return (
    <tr className="border-t border-slate-100">
      <td className="px-4 py-2">
        <div className="flex items-center gap-1.5">
          <SourceBadge source={exp.source} />
          <ProvenanceInfo prov={exp.provenance} />
        </div>
      </td>
      {compKeys.map((k) => (
        <td key={k} className="px-4 py-2">{String(exp.components[k])}</td>
      ))}
      <td className="px-4 py-2 text-slate-500">
        {exp.predicted_mean != null
          ? `${exp.predicted_mean.toFixed(1)}${
              exp.predicted_var != null ? ` ±${Math.sqrt(exp.predicted_var).toFixed(1)}` : ""
            }`
          : "-"}
      </td>
      <td className="px-4 py-2"><ExpStatusBadge status={exp.status} /></td>
      <td className="px-4 py-2">
        <div className="flex items-center gap-2">
          <input
            className="input w-24"
            placeholder="—"
            value={val}
            onChange={(e) => setVal(e.target.value)}
          />
          {dirty && (
            <button
              className="text-xs font-medium text-brand-600 hover:text-brand-700"
              onClick={save}
              disabled={busy}
            >
              {busy ? <Spinner className="h-3 w-3" /> : "保存"}
            </button>
          )}
        </div>
      </td>
    </tr>
  );
}
