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

function parseSseBlock(raw, handlers) {
  let event = 'message';
  const dataLines = [];
  for (const line of raw.split('\n')) {
    if (line.startsWith('event:')) event = line.slice(6).trim();
    else if (line.startsWith('data:')) dataLines.push(line.slice(5).trim());
  }
  if (!dataLines.length) return;
  let payload;
  try {
    payload = JSON.parse(dataLines.join('\n'));
  } catch {
    return;
  }
  if (handlers[event]) handlers[event](payload);
}

async function queryStream(courseId, question, conversationId = null, useLlm = null, handlers = {}) {
  let response;
  try {
    response = await fetch(`${BASE}/courses/${courseId}/query/stream`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        question,
        ...(conversationId ? { conversation_id: conversationId } : {}),
        ...(useLlm === null ? {} : { use_llm: useLlm }),
      }),
    });
  } catch {
    throw new ApiError(0, '无法连接服务器，请确认后端已启动');
  }
  // SSE 开始前的错误（如未配置模型的 409）仍是常规 JSON 响应
  if (!response.ok || !response.body) {
    const data = await response.json().catch(() => null);
    const detail = data && data.detail;
    throw new ApiError(
      response.status,
      typeof detail === 'string' ? detail : '请求失败，请稍后重试',
    );
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let boundary = buffer.indexOf('\n\n');
    while (boundary >= 0) {
      parseSseBlock(buffer.slice(0, boundary), handlers);
      buffer = buffer.slice(boundary + 2);
      boundary = buffer.indexOf('\n\n');
    }
  }
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

  query: (courseId, question, conversationId = null, useLlm = null) =>
    request(`/courses/${courseId}/query`, {
      method: 'POST',
      body: {
        question,
        ...(conversationId ? { conversation_id: conversationId } : {}),
        ...(useLlm === null ? {} : { use_llm: useLlm }),
      },
    }),
  queryStream,
  answerConfig: () => request('/answer/config'),
  conversations: (courseId) => request(`/courses/${courseId}/conversations`),
  messages: (conversationId) => request(`/conversations/${conversationId}/messages`),

  createQuiz: (courseId, data) =>
    request(`/courses/${courseId}/quizzes`, { method: 'POST', body: data }),
  quiz: (quizId) => request(`/quizzes/${quizId}`),
  submitQuiz: (quizId, answers) =>
    request(`/quizzes/${quizId}/attempts`, { method: 'POST', body: { answers } }),
  attempts: (courseId) => request(`/courses/${courseId}/attempts`),
  regradeAttempt: (attemptId, questionId, correct) =>
    request(`/attempts/${attemptId}/regrade`, {
      method: 'PATCH', body: { question_id: questionId, correct },
    }),

  flashcards: (courseId) => request(`/courses/${courseId}/flashcards`),
  createFlashcard: (courseId, data) =>
    request(`/courses/${courseId}/flashcards`, { method: 'POST', body: data }),
  generateFlashcards: (courseId, data) =>
    request(`/courses/${courseId}/flashcards/generate`, { method: 'POST', body: data }),
  reviewFlashcard: (cardId, mastery) =>
    request(`/flashcards/${cardId}/reviews`, { method: 'POST', body: { mastery } }),
  deleteFlashcard: (cardId) => request(`/flashcards/${cardId}`, { method: 'DELETE' }),

  tasks: (courseId) => request(`/courses/${courseId}/tasks`),
  createTask: (courseId, data) =>
    request(`/courses/${courseId}/tasks`, { method: 'POST', body: data }),
  taskCandidates: (courseId, data = {}) =>
    request(`/courses/${courseId}/tasks/candidates`, { method: 'POST', body: data }),
  updateTask: (taskId, data) =>
    request(`/tasks/${taskId}`, { method: 'PATCH', body: data }),
  deleteTask: (taskId) => request(`/tasks/${taskId}`, { method: 'DELETE' }),
};
