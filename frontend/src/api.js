async function request(path, options = {}) {
  const response = await fetch(
    path,
    {
      headers: { "Content-Type": "application/json", ...(options.headers || {}) },
      ...options,
    },
  );
  const contentType = response.headers.get("content-type") || "";
  const data = contentType.includes("application/json") ? await response.json() : null;
  if (!response.ok) throw new Error(data?.error || `操作失败（${response.status}）`);
  return data;
}

export const api = {
  get: (path) => request(path),
  post: (path, body = {}) => request(path, { method: "POST", body: JSON.stringify(body) }),
  patch: (path, body = {}) => request(path, { method: "PATCH", body: JSON.stringify(body) }),
  delete: (path) => request(path, { method: "DELETE" }),
};
