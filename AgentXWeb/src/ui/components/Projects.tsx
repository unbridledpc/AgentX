import React, { useMemo, useState } from "react";
import { config } from "../../config";
import { createClientId } from "../clientId";

export type Project = { id: string; name: string; createdAt: number };

function safeParse<T>(raw: string | null, fallback: T): T {
  if (!raw) return fallback;
  try {
    return JSON.parse(raw) as T;
  } catch {
    return fallback;
  }
}

function loadProjects(): Project[] {
  return safeParse<Project[]>(localStorage.getItem(config.projectStorageKey), []);
}

function saveProjects(projects: Project[]) {
  localStorage.setItem(config.projectStorageKey, JSON.stringify(projects));
}

export function useProjects() {
  const [projects, setProjects] = useState<Project[]>(() => loadProjects());
  const [activeProjectId, setActiveProjectId] = useState<string | null>(null);

  const activeProject = useMemo(
    () => projects.find((p) => p.id === activeProjectId) ?? null,
    [projects, activeProjectId]
  );

  const createProject = (name?: string) => {
    const nextName = (name ?? window.prompt("Project name?") ?? "").trim();
    if (!nextName) return;
    const project: Project = { id: createClientId("project"), name: nextName, createdAt: Date.now() };
    const next = [project, ...projects];
    setProjects(next);
    saveProjects(next);
    setActiveProjectId(project.id);
  };

  return {
    projects,
    activeProjectId,
    activeProject,
    setActiveProjectId,
    createProject
  };
}

