const BASE = '/api/v1';

export class ApiError extends Error {
  constructor(status, message) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

async function request(path, options = {}) {
  const { method = 'GET', body, headers = {} } = options;
  const init = { method, credentials: 'include', headers: { ...headers } };
  if (body instanceof FormData) {
    init.body = body;
  } else if (body !== undefined) {
    init.headers['Content-Type'] = 'application/json';
    init.body = JSON.stringify(body);
  }

  let response;
  try {
    response = await fetch(BASE + path, init);
  } catch {
    throw new ApiError(0, '无法连接服务器，请确认后端已启动');
  }

  if (response.status === 204) return null;
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = data && data.detail;
    let message = '请求失败，请稍后重试';
    if (typeof detail === 'string') message = detail;
    else if (Array.isArray(detail) && detail.length) message = detail[0].msg || message;
    throw new ApiError(response.status, message);
  }
  return data;
}

export const api = {
  me: () => request('/auth/me'),
  login: (username, password) =>
    request('/auth/login', { method: 'POST', body: { username, password } }),
  register: (username, password) =>
    request('/auth/register', { method: 'POST', body: { username, password } }),
  logout: () => request('/auth/logout', { method: 'POST' }),

  courses: () => request('/courses'),
  createCourse: (data) => request('/courses', { method: 'POST', body: data }),
  course: (id) => request(`/courses/${id}`),
  updateCourse: (id, data) => request(`/courses/${id}`, { method: 'PATCH', body: data }),
  deleteCourse: (id) => request(`/courses/${id}`, { method: 'DELETE' }),

  files: (courseId) => request(`/courses/${courseId}/files`),
  uploadFile: (courseId, file) => {
    const form = new FormData();
    form.append('file', file);
    return request(`/courses/${courseId}/files`, { method: 'POST', body: form });
  },
  pages: (fileId) => request(`/files/${fileId}/pages`),
  page: (fileId, ord) => request(`/files/${fileId}/pages/${ord}`),
  reprocessFile: (fileId) => request(`/files/${fileId}/reprocess`, { method: 'POST' }),
  deleteFile: (id) => request(`/files/${id}`, { method: 'DELETE' }),

  query: (courseId, question, conversationId = null) =>
    request(`/courses/${courseId}/query`, {
      method: 'POST',
      body: { question, ...(conversationId ? { conversation_id: conversationId } : {}) },
    }),
  conversations: (courseId) => request(`/courses/${courseId}/conversations`),
  messages: (conversationId) => request(`/conversations/${conversationId}/messages`),
};
