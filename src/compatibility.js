// Status metadata establishes a reviewed source baseline, never behavioral certification.
export function validCompatibilityStatus(status, mode) {
  const sha = value => typeof value === "string" && /^[0-9a-f]{40}$/i.test(value);
  return status?.schema_version === 1 && status.mode === mode &&
    sha(status.luna_sha) && sha(status.tester_sha) &&
    typeof status.compatible === "boolean" &&
    (mode !== "build" || status.compatible === true) &&
    typeof status.checked_at === "string" && Number.isFinite(Date.parse(status.checked_at));
}
