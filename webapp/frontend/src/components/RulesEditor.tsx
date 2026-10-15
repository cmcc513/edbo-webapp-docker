import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { Rule, RuleClause } from "../api/types";
import { Spinner } from "./ui";

const OPS: { value: RuleClause["op"]; label: string; kind: "eq" | "num" | "set" }[] = [
  { value: "eq", label: "=", kind: "eq" },
  { value: "ne", label: "≠", kind: "eq" },
  { value: "in", label: "属于", kind: "set" },
  { value: "nin", label: "不属于", kind: "set" },
  { value: "ge", label: "≥", kind: "num" },
  { value: "le", label: "≤", kind: "num" },
  { value: "gt", label: ">", kind: "num" },
  { value: "lt", label: "<", kind: "num" },
];

export default function RulesEditor({
  projectId,
  options,
}: {
  projectId: string;
  options: Record<string, (string | number)[]>;
}) {
  const keys = Object.keys(options);
  const [rules, setRules] = useState<Rule[]>([]);
  const [excluded, setExcluded] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    api.getRules(projectId).then((r) => {
      setRules(r.rules);
      setExcluded(r.excluded_count ?? null);
      setLoaded(true);
    });
  }, [projectId]);

  const addRule = () =>
    setRules((rs) => [
      ...rs,
      { name: `规则 ${rs.length + 1}`, active: true, clauses: [newClause()] },
    ]);
  const newClause = (): RuleClause => ({ component: keys[0], op: "eq", value: String(options[keys[0]][0]) });

  const save = async () => {
    setBusy(true);
    try {
      const res = await api.setRules(projectId, rules);
      setRules(res.rules);
      setExcluded(res.excluded_count ?? null);
    } finally {
      setBusy(false);
    }
  };

  const update = (ri: number, patch: Partial<Rule>) =>
    setRules((rs) => rs.map((r, i) => (i === ri ? { ...r, ...patch } : r)));
  const updateClause = (ri: number, ci: number, patch: Partial<RuleClause>) =>
    setRules((rs) =>
      rs.map((r, i) =>
        i === ri
          ? { ...r, clauses: r.clauses.map((c, j) => (j === ci ? { ...c, ...patch } : c)) }
          : r
      )
    );

  if (!loaded) return <div className="py-4 text-slate-400"><Spinner /></div>;

  return (
    <div className="space-y-3">
      <p className="text-sm text-slate-500">
        通过规则否掉化学上不可能发生的条件组合。候选条件只要命中任一<b>启用</b>规则的<b>全部</b>子条件即被排除，不会出现在推荐榜单中。
        {excluded != null && (
          <span className="ml-1 text-rose-600">当前规则排除了 {excluded} 个空间点。</span>
        )}
      </p>

      {rules.map((rule, ri) => (
        <div key={ri} className="rounded-lg border border-slate-200 p-3">
          <div className="mb-2 flex items-center gap-2">
            <input
              className="input max-w-[220px]"
              value={rule.name}
              onChange={(e) => update(ri, { name: e.target.value })}
              placeholder="规则名称"
            />
            <label className="flex items-center gap-1 text-sm text-slate-600">
              <input
                type="checkbox"
                checked={rule.active}
                onChange={(e) => update(ri, { active: e.target.checked })}
              />
              启用
            </label>
            <div className="flex-1" />
            <button
              className="text-sm text-rose-500 hover:text-rose-600"
              onClick={() => setRules((rs) => rs.filter((_, i) => i !== ri))}
            >
              删除规则
            </button>
          </div>

          <div className="space-y-2">
            {rule.clauses.map((c, ci) => {
              const kind = OPS.find((o) => o.value === c.op)?.kind ?? "eq";
              return (
                <div key={ci} className="flex flex-wrap items-center gap-2 text-sm">
                  {ci > 0 && <span className="text-xs text-slate-400">且</span>}
                  <select
                    className="input max-w-[180px]"
                    value={c.component}
                    onChange={(e) =>
                      updateClause(ri, ci, {
                        component: e.target.value,
                        value: String(options[e.target.value][0]),
                      })
                    }
                  >
                    {keys.map((k) => (
                      <option key={k} value={k}>{k}</option>
                    ))}
                  </select>
                  <select
                    className="input w-24"
                    value={c.op}
                    onChange={(e) => updateClause(ri, ci, { op: e.target.value as RuleClause["op"] })}
                  >
                    {OPS.map((o) => (
                      <option key={o.value} value={o.value}>{o.label}</option>
                    ))}
                  </select>
                  {kind === "eq" ? (
                    <select
                      className="input max-w-[220px]"
                      value={String(c.value)}
                      onChange={(e) => updateClause(ri, ci, { value: e.target.value })}
                    >
                      {options[c.component]?.map((o) => (
                        <option key={String(o)} value={String(o)}>{String(o)}</option>
                      ))}
                    </select>
                  ) : kind === "num" ? (
                    <input
                      type="number"
                      className="input w-28"
                      value={String(c.value ?? "")}
                      onChange={(e) => updateClause(ri, ci, { value: Number(e.target.value) })}
                    />
                  ) : (
                    <input
                      className="input max-w-[260px]"
                      placeholder="逗号分隔多个取值"
                      value={Array.isArray(c.value) ? c.value.join(",") : String(c.value ?? "")}
                      onChange={(e) =>
                        updateClause(ri, ci, {
                          value: e.target.value.split(",").map((s) => s.trim()).filter(Boolean),
                        })
                      }
                    />
                  )}
                  {rule.clauses.length > 1 && (
                    <button
                      className="text-slate-400 hover:text-rose-500"
                      onClick={() =>
                        update(ri, { clauses: rule.clauses.filter((_, j) => j !== ci) })
                      }
                    >
                      ×
                    </button>
                  )}
                </div>
              );
            })}
            <button
              className="text-xs text-brand-600 hover:text-brand-700"
              onClick={() => update(ri, { clauses: [...rule.clauses, newClause()] })}
            >
              + 添加子条件（且）
            </button>
          </div>
        </div>
      ))}

      <div className="flex items-center gap-2">
        <button className="btn-ghost" onClick={addRule}>+ 新增规则</button>
        <div className="flex-1" />
        <button className="btn-primary" onClick={save} disabled={busy}>
          {busy && <Spinner />} 保存规则
        </button>
      </div>
    </div>
  );
}
