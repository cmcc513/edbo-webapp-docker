import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import type { Project } from "../api/types";
import { StatusBadge, EmptyState, Spinner } from "../components/ui";

export default function Dashboard() {
  const [projects, setProjects] = useState<Project[] | null>(null);
  const [creating, setCreating] = useState(false);
  const [view, setView] = useState<"active" | "archived">("active");
  const nav = useNavigate();

  const load = () => api.listProjects(view === "archived").then(setProjects);
  useEffect(() => {
    setProjects(null);
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [view]);

  return (
    <div>
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">项目</h1>
          <p className="text-sm text-slate-500">反应条件的贝叶斯优化实验管理</p>
        </div>
        <div className="flex items-center gap-3">
          <div className="flex rounded-lg bg-slate-100 p-0.5 text-sm">
            <button
              className={`rounded-md px-3 py-1 ${view === "active" ? "bg-white shadow-sm text-slate-800" : "text-slate-500"}`}
              onClick={() => setView("active")}
            >
              进行中
            </button>
            <button
              className={`rounded-md px-3 py-1 ${view === "archived" ? "bg-white shadow-sm text-slate-800" : "text-slate-500"}`}
              onClick={() => setView("archived")}
            >
              已归档
            </button>
          </div>
          {view === "active" && (
            <button className="btn-primary" onClick={() => setCreating(true)}>
              + 新建项目
            </button>
          )}
        </div>
      </div>

      {projects === null ? (
        <div className="flex justify-center py-20 text-slate-400">
          <Spinner className="h-6 w-6" />
        </div>
      ) : projects.length === 0 ? (
        <EmptyState
          title={view === "archived" ? "没有已归档的项目" : "还没有项目"}
          hint={view === "archived" ? "归档的项目会出现在这里，可随时恢复" : "点击右上角新建一个优化项目"}
        />
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {projects.map((p) => (
            <ProjectCard
              key={p.id}
              project={p}
              archivedView={view === "archived"}
              onOpen={() => openProject(p, nav)}
              onChanged={load}
            />
          ))}
        </div>
      )}

      {creating && (
        <CreateModal
          onClose={() => setCreating(false)}
          onCreated={(p) => {
            setCreating(false);
            nav(`/projects/${p.id}/space`);
          }}
        />
      )}
    </div>
  );
}

function openProject(p: Project, nav: ReturnType<typeof useNavigate>) {
  if (p.status === "created") nav(`/projects/${p.id}/space`);
  else nav(`/projects/${p.id}`);
}

function ProjectCard({
  project,
  archivedView,
  onOpen,
  onChanged,
}: {
  project: Project;
  archivedView: boolean;
  onOpen: () => void;
  onChanged: () => void;
}) {
  const nav = useNavigate();
  return (
    <div
      className={`card p-5 transition ${archivedView ? "opacity-80" : "hover:shadow-md cursor-pointer"}`}
      onClick={archivedView ? undefined : onOpen}
    >
      <div className="flex items-start justify-between">
        <h3 className="font-semibold text-slate-900">{project.name}</h3>
        <StatusBadge status={project.status} />
      </div>
      <div className="mt-4 grid grid-cols-3 gap-2 text-center">
        <Stat label="轮次" value={project.current_round < 0 ? "-" : project.current_round} />
        <Stat label="实验数" value={project.n_experiments} />
        <Stat
          label={`最优 ${project.target}`}
          value={project.best_value != null ? project.best_value.toFixed(1) : "-"}
        />
      </div>
      <div className="mt-4 flex items-center justify-between text-xs text-slate-400">
        <span>{project.space_size != null ? `${project.space_size} 点空间` : "空间未构建"}</span>
        <div className="flex gap-3">
          {archivedView ? (
            <>
              <button
                className="hover:text-emerald-600"
                onClick={(e) => {
                  e.stopPropagation();
                  api.restoreProject(project.id).then(onChanged);
                }}
              >
                恢复
              </button>
              <button
                className="hover:text-rose-500"
                onClick={(e) => {
                  e.stopPropagation();
                  if (confirm(`彻底删除项目 "${project.name}"？此操作不可恢复。`))
                    api.deleteProject(project.id).then(onChanged);
                }}
              >
                删除
              </button>
            </>
          ) : (
            <>
              <button
                className="hover:text-brand-600"
                onClick={(e) => {
                  e.stopPropagation();
                  nav(`/projects/${project.id}/rebuild`);
                }}
              >
                重建
              </button>
              <button
                className="hover:text-amber-600"
                onClick={(e) => {
                  e.stopPropagation();
                  if (confirm(`归档项目 "${project.name}"？数据会保留，可随时恢复。`))
                    api.archiveProject(project.id).then(onChanged);
                }}
              >
                归档
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded-lg bg-slate-50 py-2">
      <div className="text-lg font-semibold text-slate-800">{value}</div>
      <div className="text-[11px] text-slate-400">{label}</div>
    </div>
  );
}

function CreateModal({
  onClose,
  onCreated,
}: {
  onClose: () => void;
  onCreated: (p: Project) => void;
}) {
  const [name, setName] = useState("");
  const [target, setTarget] = useState("yield");
  const [direction, setDirection] = useState("max");
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    if (!name.trim()) return;
    setBusy(true);
    try {
      const p = await api.createProject({ name, target, direction });
      onCreated(p);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-20 flex items-center justify-center bg-black/30 p-4" onClick={onClose}>
      <div className="card w-full max-w-md p-6" onClick={(e) => e.stopPropagation()}>
        <h2 className="text-lg font-semibold mb-4">新建优化项目</h2>
        <div className="space-y-4">
          <div>
            <label className="label">项目名称</label>
            <input className="input" value={name} onChange={(e) => setName(e.target.value)}
              placeholder="如：Suzuki 偶联优化" autoFocus />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="label">优化目标名</label>
              <input className="input" value={target} onChange={(e) => setTarget(e.target.value)} />
            </div>
            <div>
              <label className="label">优化方向</label>
              <select className="input" value={direction} onChange={(e) => setDirection(e.target.value)}>
                <option value="max">最大化</option>
                <option value="min">最小化</option>
              </select>
            </div>
          </div>
        </div>
        <div className="mt-6 flex justify-end gap-2">
          <button className="btn-ghost" onClick={onClose}>取消</button>
          <button className="btn-primary" onClick={submit} disabled={busy || !name.trim()}>
            {busy && <Spinner />} 创建并配置空间
          </button>
        </div>
      </div>
    </div>
  );
}
