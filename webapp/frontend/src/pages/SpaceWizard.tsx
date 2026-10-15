import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api, pollTask } from "../api/client";
import type { ComponentSpec, EncodingType, Project, SpaceValidateResult } from "../api/types";
import { Spinner } from "../components/ui";
import DescriptorBuilder from "../components/DescriptorBuilder";

type CompType = "categorical" | "smiles" | "numeric";

interface DraftComponent {
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

function inferType(encoding: EncodingType): CompType {
  if (encoding === "numeric") return "numeric";
  if (encoding === "mordred" || encoding === "resolve" || encoding === "descriptor") return "smiles";
  return "categorical";
}

export default function SpaceWizard({ rebuild = false }: { rebuild?: boolean }) {
  const { id } = useParams();
  const nav = useNavigate();
  const [project, setProject] = useState<Project | null>(null);
  const [comps, setComps] = useState<DraftComponent[]>([]);
  const [model, setModel] = useState("GP");
  const [initMethod, setInitMethod] = useState("rand");
  const [validation, setValidation] = useState<SpaceValidateResult | null>(null);
  const [building, setBuilding] = useState(false);
  const [buildMsg, setBuildMsg] = useState("");
  // Rebuild-only: new project name + whether to carry over completed results.
  const [newName, setNewName] = useState("");
  const [copyData, setCopyData] = useState(true);

  useEffect(() => {
    if (!id) return;
    api.getProject(id).then((p) => {
      setProject(p);
      if (rebuild) setNewName((n) => n || `${p.name} (重建)`);
    });
    // Prefill from an existing/cloned configuration (e.g. after "重建").
    api.getConfig(id).then((cfg) => {
      if (cfg.components.length === 0) return;
      setComps(
        cfg.components.map((c) => ({
          name: c.name,
          type: inferType(c.encoding),
          values: c.values,
          encoding: c.encoding,
          descriptor_file: c.descriptor_file,
          id_column: c.id_column,
        }))
      );
      setModel(cfg.model);
      setInitMethod(cfg.init_method);
    }).catch(() => {});
  }, [id, rebuild]);

  const toSpec = (): ComponentSpec[] =>
    comps.map((c) => ({
      name: c.name,
      values: c.values,
      encoding: c.encoding,
      descriptor_file: c.descriptor_file,
      id_column: c.id_column,
    }));

  const spaceSize = comps.reduce((acc, c) => acc * Math.max(1, c.values.length), 1);

  const validate = async () => {
    if (!id) return;
    const r = await api.validateSpace(id, toSpec(), { model, init_method: initMethod });
    setValidation(r);
  };

  const build = async () => {
    if (!id) return;
    const r = await api.validateSpace(id, toSpec(), { model, init_method: initMethod });
    setValidation(r);
    if (!r.ok) return;
    setBuilding(true);
    try {
      const { task_id } = await api.buildSpace(id, toSpec(), { model, init_method: initMethod });
      const t = await pollTask(id, task_id, (t) => setBuildMsg(t.message ?? ""));
      if (t.status === "done") nav(`/projects/${id}`);
      else setBuildMsg(t.error ?? "构建失败");
    } finally {
      setBuilding(false);
    }
  };

  const confirmRebuild = async () => {
    if (!id) return;
    const r = await api.validateSpace(id, toSpec(), { model, init_method: initMethod });
    setValidation(r);
    if (!r.ok) return;
    setBuilding(true);
    try {
      setBuildMsg("正在创建重建项目…");
      const { project_id, task_id } = await api.rebuildProject(id, {
        name: newName.trim() || undefined,
        copy_data: copyData,
        components: toSpec(),
        model_config_: { model, init_method: initMethod },
      });
      const t = await pollTask(project_id, task_id, (t) => setBuildMsg(t.message ?? ""));
      if (t.status === "done") nav(`/projects/${project_id}`);
      else setBuildMsg(t.error ?? "重建失败");
    } catch (e) {
      setBuildMsg(String(e));
    } finally {
      setBuilding(false);
    }
  };

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-slate-900">
          {rebuild ? "重建项目" : "配置反应空间"}
        </h1>
        <p className="text-sm text-slate-500">
          {rebuild
            ? `基于「${project?.name ?? ""}」的配置，修改反应空间 / 模型 / 描述符后确认重建（原项目不受影响）`
            : `${project?.name} · 逐个添加反应组分的取值与编码方式`}
        </p>
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <div className="lg:col-span-2 space-y-4">
          {comps.map((c, i) => (
            <ComponentEditor
              key={i}
              projectId={id!}
              comp={c}
              onChange={(nc) => setComps((cs) => cs.map((x, j) => (j === i ? nc : x)))}
              onRemove={() => setComps((cs) => cs.filter((_, j) => j !== i))}
            />
          ))}
          <button
            className="btn-ghost w-full border-dashed"
            onClick={() =>
              setComps((cs) => [
                ...cs,
                { name: "", type: "categorical", values: [], encoding: "ohe" },
              ])
            }
          >
            + 添加反应组分
          </button>
        </div>

        <div className="space-y-4">
          {rebuild && (
            <div className="card p-5">
              <h3 className="font-semibold mb-3">重建设置</h3>
              <div className="space-y-3">
                <div>
                  <label className="label">新项目名称</label>
                  <input
                    className="input"
                    value={newName}
                    onChange={(e) => setNewName(e.target.value)}
                    placeholder="新项目名称"
                  />
                </div>
                <label className="flex items-center gap-2 text-sm text-slate-600">
                  <input
                    type="checkbox"
                    checked={copyData}
                    onChange={(e) => setCopyData(e.target.checked)}
                  />
                  复制原项目的已完成实验数据（构建后作为先前结果导入）
                </label>
              </div>
            </div>
          )}
          <div className="card p-5">
            <h3 className="font-semibold mb-3">优化设置</h3>
            <div className="space-y-3">
              <div>
                <label className="label">代理模型</label>
                <select className="input" value={model} onChange={(e) => setModel(e.target.value)}>
                  <option value="GP">高斯过程 (GP)</option>
                  <option value="RF">随机森林 (RF)</option>
                  <option value="Bayesian_Linear">贝叶斯线性</option>
                </select>
              </div>
              <div>
                <label className="label">初始化方法</label>
                <select className="input" value={initMethod} onChange={(e) => setInitMethod(e.target.value)}>
                  <option value="rand">随机 (rand)</option>
                  <option value="pam">k-medoids (pam)</option>
                  <option value="kmeans">k-means</option>
                </select>
              </div>
            </div>
          </div>

          <div className="card p-5">
            <h3 className="font-semibold mb-2">搜索空间</h3>
            <div className="text-3xl font-bold text-brand-600">
              {spaceSize.toLocaleString()}
            </div>
            <div className="text-xs text-slate-400 mb-3">
              {comps.map((c) => c.values.length || "?").join(" × ") || "尚无组分"} 种组合
            </div>
            {validation && (
              <div className="space-y-1 text-xs">
                {validation.errors.map((e, i) => (
                  <div key={i} className="text-rose-600">✗ {e}</div>
                ))}
                {validation.warnings.map((w, i) => (
                  <div key={i} className="text-amber-600">⚠ {w}</div>
                ))}
                {validation.ok && <div className="text-emerald-600">✓ 空间可构建</div>}
              </div>
            )}
            <div className="mt-4 flex flex-col gap-2">
              <button className="btn-ghost" onClick={validate} disabled={comps.length === 0}>
                校验
              </button>
              <button
                className="btn-primary"
                onClick={rebuild ? confirmRebuild : build}
                disabled={building || comps.length === 0}
              >
                {building && <Spinner />} {rebuild ? "确认重建" : "构建空间"}
              </button>
              {building && <div className="text-xs text-slate-500">{buildMsg}</div>}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function ComponentEditor({
  projectId,
  comp,
  onChange,
  onRemove,
}: {
  projectId: string;
  comp: DraftComponent;
  onChange: (c: DraftComponent) => void;
  onRemove: () => void;
}) {
  const [raw, setRaw] = useState("");
  const [numStart, setNumStart] = useState("");
  const [numEnd, setNumEnd] = useState("");
  const [numStep, setNumStep] = useState("");
  const [builderOpen, setBuilderOpen] = useState(false);

  const setType = (type: CompType) =>
    onChange({ ...comp, type, encoding: ENCODINGS_FOR[type][0], values: [] });

  const addRawValues = () => {
    const parts = raw
      .split(/[\n,]/)
      .map((s) => s.trim())
      .filter(Boolean);
    const parsed = comp.type === "numeric" ? parts.map(Number).filter((n) => !isNaN(n)) : parts;
    onChange({ ...comp, values: dedupe([...comp.values, ...parsed]) });
    setRaw("");
  };

  const generateNumeric = () => {
    const s = Number(numStart), e = Number(numEnd), st = Number(numStep);
    if (isNaN(s) || isNaN(e) || isNaN(st) || st === 0) return;
    const out: number[] = [];
    for (let v = s; v <= e + 1e-9; v += st) out.push(Math.round(v * 1e6) / 1e6);
    onChange({ ...comp, values: dedupe([...comp.values, ...out]) });
    setNumStart(""); setNumEnd(""); setNumStep("");
  };

  return (
    <div className="card p-5">
      <div className="flex items-center gap-3">
        <input
          className="input flex-1 font-medium"
          placeholder="组分名 (如 base / ligand / temperature)"
          value={comp.name}
          onChange={(e) => onChange({ ...comp, name: e.target.value })}
        />
        <button className="text-slate-400 hover:text-rose-500 text-sm" onClick={onRemove}>
          删除
        </button>
      </div>

      <div className="mt-3 flex gap-2">
        {(["categorical", "smiles", "numeric"] as CompType[]).map((t) => (
          <button
            key={t}
            className={`badge px-3 py-1 ${
              comp.type === t ? "bg-brand-600 text-white" : "bg-slate-100 text-slate-600"
            }`}
            onClick={() => setType(t)}
          >
            {t === "categorical" ? "分类值" : t === "smiles" ? "SMILES 分子" : "连续数值"}
          </button>
        ))}
      </div>

      {/* value entry */}
      <div className="mt-3">
        {comp.type === "numeric" ? (
          <div className="flex flex-wrap items-end gap-2">
            <div className="flex gap-2">
              <div>
                <label className="label">起</label>
                <input className="input w-20" value={numStart} onChange={(e) => setNumStart(e.target.value)} />
              </div>
              <div>
                <label className="label">止</label>
                <input className="input w-20" value={numEnd} onChange={(e) => setNumEnd(e.target.value)} />
              </div>
              <div>
                <label className="label">步长</label>
                <input className="input w-20" value={numStep} onChange={(e) => setNumStep(e.target.value)} />
              </div>
            </div>
            <button className="btn-ghost" onClick={generateNumeric}>等差生成</button>
            <span className="text-xs text-slate-400">或直接输入：</span>
            <input
              className="input flex-1 min-w-[120px]"
              placeholder="20, 30, 40"
              value={raw}
              onChange={(e) => setRaw(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && addRawValues()}
            />
            <button className="btn-ghost" onClick={addRawValues}>添加</button>
          </div>
        ) : (
          <div className="flex gap-2">
            <input
              className="input flex-1"
              placeholder={comp.type === "smiles" ? "粘贴 SMILES，逗号或换行分隔" : "输入取值，逗号或换行分隔"}
              value={raw}
              onChange={(e) => setRaw(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && addRawValues()}
            />
            <button className="btn-ghost" onClick={addRawValues}>添加</button>
          </div>
        )}
      </div>

      {/* chips */}
      {comp.values.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-1.5">
          {comp.values.map((v, i) => (
            <span key={i} className="badge bg-slate-100 text-slate-700 gap-1">
              {String(v)}
              <button
                className="text-slate-400 hover:text-rose-500"
                onClick={() => onChange({ ...comp, values: comp.values.filter((_, j) => j !== i) })}
              >
                ×
              </button>
            </span>
          ))}
          <span className="text-xs text-slate-400 self-center ml-1">共 {comp.values.length} 项</span>
        </div>
      )}

      {/* encoding */}
      <div className="mt-4 flex items-center gap-3 border-t border-slate-100 pt-3">
        <label className="label mb-0">编码方式</label>
        <select
          className="input w-48"
          value={comp.encoding}
          onChange={(e) => onChange({ ...comp, encoding: e.target.value as EncodingType })}
        >
          {ENCODINGS_FOR[comp.type].map((enc) => (
            <option key={enc} value={enc}>
              {ENC_LABEL[enc]}
            </option>
          ))}
        </select>

        {comp.encoding === "descriptor" && (
          <div className="flex items-center gap-2">
            <button
              className="btn-ghost"
              onClick={() => setBuilderOpen(true)}
              disabled={comp.values.length === 0}
              title={comp.values.length === 0 ? "先添加取值" : ""}
            >
              定制 / 导入描述符
            </button>
            {comp.descriptor_file && (
              <span className="text-xs text-emerald-600">
                ✓ {comp.descriptor_file.split("__").pop()}
              </span>
            )}
          </div>
        )}
      </div>
      {comp.encoding === "descriptor" && (
        <p className="mt-2 text-[11px] text-slate-400">
          描述符规范：CSV 首列为标识符（需与取值完全一致），其余列为数值特征，每个取值一行、需全覆盖。
        </p>
      )}

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

const ENC_LABEL: Record<EncodingType, string> = {
  ohe: "独热编码 (ohe)",
  numeric: "数值 (numeric)",
  mordred: "Mordred 描述符",
  resolve: "名称解析 (resolve)",
  descriptor: "自定义描述符 (DFT)",
};

function dedupe<T>(arr: T[]): T[] {
  return Array.from(new Set(arr.map((x) => JSON.stringify(x)))).map((s) => JSON.parse(s));
}
