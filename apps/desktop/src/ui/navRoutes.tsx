import React from "react";
import { PlaceholderPage } from "./pages/PlaceholderPage";
import { SettingsPage } from "./pages/SettingsPage";

export type RouteDefinition = {
  id: string;
  label: string;
  section: string;
  description: string;
  component: React.ComponentType;
};

const placeholder = (title: string, description: string): React.FC =>
  function Placeholder() {
    return <PlaceholderPage title={title} description={description} />;
  };

export const routeRegistry: RouteDefinition[] = [
  {
    id: "chat",
    label: "Chat",
    section: "Workspace",
    description: "Conversations, threads, and chat history",
    component: placeholder("Chat", "Use the chat view to talk with Sol and manage threads."),
  },
  {
    id: "settings",
    label: "Settings",
    section: "Workspace",
    description: "Global preferences & configuration",
    component: SettingsPage,
  },
  {
    id: "projects",
    label: "Projects",
    section: "Management",
    description: "Organize chats and assets by project",
    component: placeholder("Projects", "Create, rename, and delete projects here."),
  },
  {
    id: "memory",
    label: "Memory",
    section: "Management",
    description: "View and edit stored memories and notes",
    component: placeholder("Memory", "Memory browsing will appear here."),
  },
  {
    id: "tools",
    label: "Tools",
    section: "Management",
    description: "Available tools and utilities",
    component: placeholder("Tools", "Tool runners and automation live here."),
  },
  {
    id: "insights",
    label: "Insights",
    section: "Analysis",
    description: "Logs, events, and operational telemetry",
    component: placeholder("Insights", "Diagnostic output will surface here."),
  },
];

export const defaultRouteId = routeRegistry[0].id;
