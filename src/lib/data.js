import categoriesFile from "../data/categories.json";
import projectsFile from "../data/projects.json";
import profile from "../data/profile.json";

export { profile };
export const categories = categoriesFile.categories;
export const categoryById = Object.fromEntries(categories.map((c) => [c.id, c]));

// Archived repositories stay in the data but are hidden from the public site.
export const projects = projectsFile.projects.filter((p) => p.status !== "archived");
export const projectById = Object.fromEntries(projects.map((p) => [p.id, p]));

export const allTech = [...new Set(projects.flatMap((p) => p.tech_stack))].sort((a, b) =>
  a.localeCompare(b)
);

// Every timeline entry across all projects, newest first.
export const allUpdates = projects
  .flatMap((project) => project.updates.map((update) => ({ project, update })))
  .sort((a, b) => b.update.date.localeCompare(a.update.date));
