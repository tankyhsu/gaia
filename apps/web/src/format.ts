/** Shared formatting used by more than one page. */
export function message(error: unknown): string {
  return error instanceof Error ? error.message : "请求失败";
}
