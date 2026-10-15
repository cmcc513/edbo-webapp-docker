import { useState } from "react";
import { api } from "../api/client";
import type { ImportPreview, PriorExperiment } from "../api/types";
import { Spinner } from "./ui";

export default function ImportPanel({
  projectId,
  options,
  target,
  onSubmit,
  busy,
}: {
  projectId: string;
  options: Record<string, (string | number)[]>;
  target: string;
  onSubmit: (prior: PriorExperiment[]) => void;
  busy: boolean;
}) {
  const keys = Object.keys(options);
  const [mode, setMode] = useState<"csv" | "manual">("csv");

  return (
    <div>
      <div className="mb-3 flex gap-2">
        <ModeBtn active={mode === "csv"} onClick={() => setMode("csv")}>CSV 上传</ModeBtn>
        <ModeBtn active={mode === "manual"} onClick={() => setMode("manual")}>手动录入</ModeBtn>
      </div>
      {mode === "csv" ? (
        <CsvImport projectId={projectId} keys={keys} target={target} onSubmit={onSubmit} busy={busy} />
      ) : (
        <ManualImport options={options} target={target} onSubmit={onSubmit} busy={busy} />
      )}
    </div>
  );
}

function ModeBtn({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      className={`rounded-lg px-3 py-1.5 text-sm ${active ? "bg-brand-600 text-white" : "bg-white border border-slate-200 text-slate-600"}`}
      onClick={onClick}
    >
      {children}
    </button>
  );
}

function CsvImport({
  projectId,
  keys,
  target,
  onSubmit,
  busy,
}: {
  projectId: string;
  keys: string[];
  target: string;
  onSubmit: (prior: PriorExperiment[]) => void;
  busy: boolean;
}) {
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [map, setMap] = useState<Record<string, string>>({});
  const [yieldCol, setYieldCol] = useState("");

  const onFile = async (file: File) => {
    const p = await api.importPreview(projectId, file);
    setPreview(p);
    // auto-map by name similarity
    const auto: Record<string, string> = {};
    keys.forEach((k) => {
      const hit = p.columns.find((c) => c.toLowerCase() === k.toLowerCase());
      if (hit) auto[k] = hit;
    });
    setMap(auto);
    const yc = p.columns.find((c) => /yield|产率|目标|target/i.test(c));
    if (yc) setYieldCol(yc);
  };

  const doImport = () => {
    if (!preview) return;
    const prior: PriorExperiment[] = [];
    for (const row of preview.rows) {
      if (yieldCol === "" || row[yieldCol] == null || row[yieldCol] === "") continue;
      const comps: Record<string, string | number> = {};
      let ok = true;
      for (const k of keys) {
        const col = map[k];
        if (!col || row[col] == null) { ok = false; break; }
        comps[k] = row[col] as string | number;
      }
      if (!ok) continue;
      const val = Number(row[yieldCol]);
      if (Number.isNaN(val)) continue;
      prior.push({ components: comps, observed_value: val });
    }
    if (prior.length === 0) {
      alert("没有可导入的行：请检查列映射与产率列。");
      return;
    }
    onSubmit(prior);
  };

  return (
    <div>
      <input
        type="file"
        accept=".csv"
        className="mb-3 block text-sm"
        onChange={(e) => e.target.files?.[0] && onFile(e.target.files[0])}
      />
      {preview && (
        <>
          <div className="mb-3 text-xs text-slate-500">
            共 {preview.n_rows} 行。请把 CSV 列映射到反应组分与产率列：
          </div>
          <div className="grid grid-cols-2 gap-3">
            {keys.map((k) => (
              <div key={k}>
                <label className="label">{k}</label>
                <select
                  className="input"
                  value={map[k] ?? ""}
                  onChange={(e) => setMap((m) => ({ ...m, [k]: e.target.value }))}
                >
                  <option value="">选择列…</option>
                  {preview.columns.map((c) => (
                    <option key={c} value={c}>{c}</option>
                  ))}
                </select>
              </div>
            ))}
            <div>
              <label className="label">{target}（产率列）</label>
              <select className="input" value={yieldCol} onChange={(e) => setYieldCol(e.target.value)}>
                <option value="">选择列…</option>
                {preview.columns.map((c) => (
                  <option key={c} value={c}>{c}</option>
                ))}
              </select>
            </div>
          </div>
          <button className="btn-primary mt-4" onClick={doImport} disabled={busy}>
            {busy && <Spinner />} 导入并训练模型
          </button>
        </>
      )}
    </div>
  );
}

function ManualImport({
  options,
  target,
  onSubmit,
  busy,
}: {
  options: Record<string, (string | number)[]>;
  target: string;
  onSubmit: (prior: PriorExperiment[]) => void;
  busy: boolean;
}) {
  const keys = Object.keys(options);
  const emptyRow = () => ({ ...Object.fromEntries(keys.map((k) => [k, ""])), __v: "" }) as Record<string, string>;
  const [rows, setRows] = useState<Record<string, string>[]>([emptyRow(), emptyRow()]);

  const doImport = () => {
    const prior: PriorExperiment[] = [];
    for (const r of rows) {
      if (keys.some((k) => r[k] === "") || r.__v.trim() === "") continue;
      const comps: Record<string, string | number> = {};
      keys.forEach((k) => {
        const opt = options[k].find((o) => String(o) === r[k]);
        comps[k] = opt ?? r[k];
      });
      prior.push({ components: comps, observed_value: Number(r.__v) });
    }
    if (prior.length === 0) { alert("请至少完整填写一行。"); return; }
    onSubmit(prior);
  };

  return (
    <div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-xs text-slate-500">
            <tr>
              {keys.map((k) => <th key={k} className="px-2 py-1 text-left">{k}</th>)}
              <th className="px-2 py-1 text-left">{target}</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row, ri) => (
              <tr key={ri} className="border-t border-slate-100">
                {keys.map((k) => (
                  <td key={k} className="px-2 py-1">
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
                <td className="px-2 py-1">
                  <input
                    className="input w-24"
                    value={row.__v}
                    onChange={(e) => setRows((rs) => rs.map((r, j) => (j === ri ? { ...r, __v: e.target.value } : r)))}
                  />
                </td>
                <td className="px-1">
                  {rows.length > 1 && (
                    <button className="text-slate-400 hover:text-rose-500" onClick={() => setRows((rs) => rs.filter((_, j) => j !== ri))}>×</button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="mt-3 flex justify-between">
        <button className="btn-ghost" onClick={() => setRows((rs) => [...rs, emptyRow()])}>+ 新增行</button>
        <button className="btn-primary" onClick={doImport} disabled={busy}>
          {busy && <Spinner />} 导入并训练模型
        </button>
      </div>
    </div>
  );
}
