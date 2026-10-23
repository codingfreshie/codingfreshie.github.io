const fmt = new Intl.DateTimeFormat("en-US", {
  month: "short",
  day: "numeric",
  year: "numeric",
  timeZone: "UTC",
});

// Dates are stored as YYYY-MM-DD; format in UTC so the displayed day never shifts.
export const formatDate = (iso) => fmt.format(new Date(`${iso}T00:00:00Z`));

export const shortSha = (sha) => sha.slice(0, 7);

export const UPDATE_LABELS = {
  feature: "Feature",
  fix: "Fix",
  refactor: "Refactor",
  test: "Tests",
  docs: "Docs",
  performance: "Performance",
  other: "Update",
};
