import { useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import type {
  DescriptorTool,
  DescriptorComputeResult,
  DerivedFeature,
} from "../api/types";
import { Spinner } from "./ui";

/**
 * Feature-composition panel: pick a tool, compute features for a component's
 * values, select a subset, add derived features, optionally standardize / PCA,
 * then save as a custom descriptor CSV (unified with the import path).
 */
export default function DescriptorBuilder({
  projectId,
  componentName,
  identifiers,
  onSaved,
  onClose,
}: {
  projectId: string;
  componentName: string;
  identifiers: string[];
  onSaved: (filename: string, idColumn: string) => void;
  onClose: () => void;
}) {
  const [tools, setTools] = useState<DescriptorTool[]>([]);
  const [toolId, setToolId] = useState("");
  const [computing, setComputing] = useState(false);
  const [res, setRes] = useState<DescriptorComputeResult | null>(null);
  const [sourceFile, setSourceFile] = useState<string | null>(null);
  const [sel, setSel] = useState<Set<string>>(new Set());
  const [search, setSearch] = useState("");
  const [derived, setDerived] = useState<DerivedFeature[]>([]);
  const [standardize, setStandardize] = useState(true);
  const [usePca, setUsePca] = useState(false);
  const [pcaN, setPcaN] = useState(3);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    api.getDescriptorTools().then((r) => {
      const avail = r.tools.filter((t) => t.available);
      setTools(r.tools);
      if (avail[0]) setToolId(avail[0].id);
    });
  }, []);

  const tool = tools.find((t) => t.id === toolId);
  const isImport = tool?.kind === "import";

  const resetResult = () => {
    setRes(null);
    setSourceFile(null);
    setSel(new Set());
    setDerived([]);
    setErr(null);
    setSearch("");
  };

  const compute = async () => {
    setComputing(true);
    resetResult();
    try {
      const r = await api.computeDescriptors(projectId, {
        tool_id: toolId,
        identifiers,
      });
      setRes(r);
      if (!r.ok) setErr(r.error ?? "计算失败");
    } catch (e) {
      setErr(String(e));
    } finally {
      setComputing(false);
    }
  };

  const doImport = async (file: File) => {
    setComputing(true);
    resetResult();
    try {
      const r = await api.importDescriptors(projectId, file, identifiers);
      setRes(r);
      setSourceFile(r.source_file ?? null);
      if (!r.ok) setErr(r.error ?? "导入失败");
    } catch (e) {
      setErr(String(e));
    } finally {
      setComputing(false);
    }
  };

  const columns = res?.columns ?? [];
  const sortedCols = useMemo(() => {
    const stats = res?.stats ?? {};
    return [...columns].sort(
      (a, b) => (stats[b]?.variance ?? 0) - (stats[a]?.variance ?? 0)
    );
  }, [columns, res]);
  const filtered = sortedCols.filter((c) =>
    c.toLowerCase().includes(search.toLowerCase())
  );

  const toggle = (c: string) =>
    setSel((s) => {
      const n = new Set(s);
      n.has(c) ? n.delete(c) : n.add(c);
      return n;
    });

  const derivedCount = derived.length;
  const totalFeatures = usePca ? pcaN : sel.size + derivedCount;

  const save = async () => {
    setSaving(true);
    setErr(null);
    try {
      const r = await api.composeDescriptors(projectId, {
        tool_id: toolId,
        identifiers,
        selected: [...sel],
        derived,
        standardize,
        pca_n: usePca ? pcaN : null,
        out_name: componentName || "descriptor",
        source_file: sourceFile,
      });
      if (!r.ok || !r.filename) {
        setErr(r.error ?? "保存失败");
        return;
      }
      onSaved(r.filename, r.id_column);
    } catch (e) {
      setErr(String(e));
    } finally {
      setSaving(false);
    }
  };

  const selArr = [...sel];

  return (
    <div className="fixed inset-0 z-30 flex items-center justify-center bg-black/40 p-4" onClick={onClose}>
      <div
        className="card flex max-h-[90vh] w-full max-w-4xl flex-col overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-slate-100 px-5 py-3">
          <div>
            <h2 className="font-semibold text-slate-800">描述符定制 · {componentName || "组分"}</h2>
            <p className="text-xs text-slate-500">
              用工具计算特征，勾选/组合成该组分的描述符（{identifiers.length} 个取值）
            </p>
          </div>
          <button className="text-slate-400 hover:text-slate-600" onClick={onClose}>✕</button>
        </div>

        <div className="flex items-end gap-3 border-b border-slate-100 px-5 py-3">
          <div>
            <label className="label">描述符来源</label>
            <select
              className="input w-56"
              value={toolId}
              onChange={(e) => {
                setToolId(e.target.value);
                resetResult();
              }}
            >
              {tools.map((t) => (
                <option key={t.id} value={t.id} disabled={!t.available}>
                  {t.name}{t.available ? "" : "（不可用）"}
                </option>
              ))}
            </select>
          </div>
          {isImport ? (
            <>
              <label className="btn-primary cursor-pointer">
                {computing ? <Spinner /> : "选择 CSV 文件"}
                <input
                  type="file"
                  accept=".csv"
                  className="hidden"
                  onChange={(e) => e.target.files?.[0] && doImport(e.target.files[0])}
                />
              </label>
              <span className="text-xs text-slate-400">
                首列为标识符（需与取值一致），其余列为数值特征
              </span>
            </>
          ) : (
            <>
              <button className="btn-primary" onClick={compute} disabled={!toolId || computing}>
                {computing && <Spinner />} 计算特征
              </button>
              <span className="text-xs text-slate-400">工具仅支持 SMILES 类组分</span>
            </>
          )}
        </div>

        {err && <div className="mx-5 mt-3 rounded-md bg-rose-50 px-3 py-2 text-xs text-rose-600">{err}</div>}
        {res?.invalid && res.invalid.length > 0 && (
          <div className="mx-5 mt-3 rounded-md bg-amber-50 px-3 py-2 text-xs text-amber-700">
            {res.invalid.length} 个取值{isImport ? "在 CSV 中缺失或无数值特征" : "无法解析为分子"}（保存前需修正）：{res.invalid.slice(0, 6).join(", ")}
          </div>
        )}

        {res?.ok && (
          <div className="grid flex-1 grid-cols-2 gap-0 overflow-hidden">
            {/* feature picker */}
            <div className="flex flex-col overflow-hidden border-r border-slate-100">
              <div className="px-5 py-2">
                <input
                  className="input"
                  placeholder={`搜索 ${columns.length} 个特征（按方差排序）`}
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                />
              </div>
              <div className="flex-1 overflow-y-auto px-5 pb-3">
                {filtered.map((c) => (
                  <label key={c} className="flex items-center gap-2 py-1 text-sm hover:bg-slate-50">
                    <input type="checkbox" checked={sel.has(c)} onChange={() => toggle(c)} />
                    <span className="flex-1 truncate">{c}</span>
                    <span className="text-[11px] text-slate-400">
                      σ²={(res.stats[c]?.variance ?? 0).toPrecision(3)}
                    </span>
                  </label>
                ))}
              </div>
            </div>

            {/* composition */}
            <div className="flex flex-col overflow-y-auto px-5 py-3">
              <div className="text-xs font-semibold text-slate-500">已选特征（{sel.size}）</div>
              <div className="mt-1 flex flex-wrap gap-1">
                {selArr.length === 0 && <span className="text-xs text-slate-400">从左侧勾选特征</span>}
                {selArr.map((c) => (
                  <span key={c} className="badge bg-brand-50 text-brand-700 gap-1">
                    {c}
                    <button className="text-brand-400 hover:text-rose-500" onClick={() => toggle(c)}>×</button>
                  </span>
                ))}
              </div>

              <DerivedEditor columns={columns} derived={derived} setDerived={setDerived} />

              <div className="mt-4 space-y-2 border-t border-slate-100 pt-3 text-sm">
                <label className="flex items-center gap-2">
                  <input type="checkbox" checked={standardize} onChange={(e) => setStandardize(e.target.checked)} />
                  标准化（z-score）
                </label>
                <label className="flex items-center gap-2">
                  <input type="checkbox" checked={usePca} onChange={(e) => setUsePca(e.target.checked)} />
                  PCA 降维到
                  <input
                    type="number"
                    className="input w-16"
                    value={pcaN}
                    disabled={!usePca}
                    min={1}
                    onChange={(e) => setPcaN(Math.max(1, Number(e.target.value)))}
                  />
                  维
                </label>
              </div>

              <div className="mt-4 rounded-md bg-slate-50 px-3 py-2 text-xs text-slate-500">
                最终描述符维度：约 {totalFeatures} 列 × {identifiers.length} 行
                {usePca && "（PCA 会覆盖所选/派生特征）"}
              </div>
            </div>
          </div>
        )}

        <div className="flex items-center justify-end gap-2 border-t border-slate-100 px-5 py-3">
          <button className="btn-ghost" onClick={onClose}>取消</button>
          <button
            className="btn-primary"
            onClick={save}
            disabled={saving || !res?.ok || (sel.size === 0 && derived.length === 0) || (res?.invalid?.length ?? 0) > 0}
          >
            {saving && <Spinner />} 保存为描述符
          </button>
        </div>
      </div>
    </div>
  );
}

function DerivedEditor({
  columns,
  derived,
  setDerived,
}: {
  columns: string[];
  derived: DerivedFeature[];
  setDerived: (d: DerivedFeature[]) => void;
}) {
  const [a, setA] = useState("");
  const [b, setB] = useState("");
  const [op, setOp] = useState<DerivedFeature["op"]>("div");

  const OPS: { v: DerivedFeature["op"]; s: string }[] = [
    { v: "add", s: "+" },
    { v: "sub", s: "−" },
    { v: "mul", s: "×" },
    { v: "div", s: "÷" },
  ];

  const add = () => {
    if (!a || !b) return;
    const opStr = OPS.find((o) => o.v === op)?.s ?? op;
    setDerived([...derived, { a, b, op, name: `${a}${opStr}${b}` }]);
  };

  return (
    <div className="mt-4 border-t border-slate-100 pt-3">
      <div className="text-xs font-semibold text-slate-500">派生特征（两两运算）</div>
      <div className="mt-2 flex flex-wrap items-center gap-1">
        <select className="input w-32" value={a} onChange={(e) => setA(e.target.value)}>
          <option value="">特征A</option>
          {columns.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
        <select className="input w-16" value={op} onChange={(e) => setOp(e.target.value as DerivedFeature["op"])}>
          {OPS.map((o) => <option key={o.v} value={o.v}>{o.s}</option>)}
        </select>
        <select className="input w-32" value={b} onChange={(e) => setB(e.target.value)}>
          <option value="">特征B</option>
          {columns.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
        <button className="btn-ghost" onClick={add} disabled={!a || !b}>添加</button>
      </div>
      {derived.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1">
          {derived.map((d, i) => (
            <span key={i} className="badge bg-purple-100 text-purple-700 gap-1">
              {d.name}
              <button
                className="text-purple-400 hover:text-rose-500"
                onClick={() => setDerived(derived.filter((_, j) => j !== i))}
              >
                ×
              </button>
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
