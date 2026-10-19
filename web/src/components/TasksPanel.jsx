import React, { useEffect, useMemo, useState } from 'react';
import { api } from '../api';
import { formatDate } from '../utils';

function toLocalInput(value) {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  const pad = (number) => String(number).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function toIso(value) {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date.toISOString();
}

export default function TasksPanel({ courseId, files }) {
  const readyFiles = useMemo(
    () => files.filter((file) => file.status === 'ready'),
    [files],
  );
  const [tasks, setTasks] = useState([]);
  const [candidates, setCandidates] = useState([]);
  const [drafts, setDrafts] = useState({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [scanning, setScanning] = useState(false);
  const [scanNotice, setScanNotice] = useState('');
  const [showDone, setShowDone] = useState(false);
  const [showForm, setShowForm] = useState(false);
  const [title, setTitle] = useState('');
  const [due, setDue] = useState('');
  const [editingId, setEditingId] = useState(null);
  const [editTitle, setEditTitle] = useState('');
  const [editDue, setEditDue] = useState('');

  useEffect(() => {
    setCandidates([]);
    setDrafts({});
    setScanNotice('');
    loadTasks();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [courseId]);

  async function loadTasks() {
    setLoading(true);
    setError('');
    try {
      setTasks(await api.tasks(courseId));
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  async function scanCandidates() {
    if (scanning) return;
    setScanning(true);
    setError('');
    setScanNotice('');
    try {
      const result = await api.taskCandidates(courseId);
      const enriched = result.map((item, index) => ({
        ...item,
        key: `${item.source_file_id}-${item.due_at || 'none'}-${index}`,
      }));
      setCandidates(enriched);
      setDrafts(Object.fromEntries(
        enriched.map((item) => [item.key, toLocalInput(item.due_at)]),
      ));
      if (!enriched.length) {
        setScanNotice('没有在已解析资料中找到明确的截止日期。');
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setScanning(false);
    }
  }

  function updateDraft(key, value) {
    setDrafts((current) => ({ ...current, [key]: value }));
  }

  function dropCandidate(key) {
    setCandidates((current) => current.filter((item) => item.key !== key));
    setDrafts((current) => {
      const next = { ...current };
      delete next[key];
      return next;
    });
  }

  async function confirmCandidate(candidate) {
    if (busy) return;
    setBusy(true);
    setError('');
    try {
      await api.createTask(courseId, {
        title: candidate.title,
        due_at: toIso(drafts[candidate.key]),
        source_file_id: candidate.source_file_id,
        source_snippet: candidate.snippet,
      });
      dropCandidate(candidate.key);
      await loadTasks();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function addTask(event) {
    event.preventDefault();
    if (busy || !title.trim()) return;
    setBusy(true);
    setError('');
    try {
      await api.createTask(courseId, {
        title: title.trim(),
        due_at: toIso(due),
      });
      setTitle('');
      setDue('');
      setShowForm(false);
      await loadTasks();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function toggleDone(task) {
    if (busy) return;
    setBusy(true);
    setError('');
    try {
      const updated = await api.updateTask(task.id, { done: !task.done });
      setTasks((current) => current.map((item) => (item.id === task.id ? updated : item)));
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  function startEdit(task) {
    setEditingId(task.id);
    setEditTitle(task.title);
    setEditDue(toLocalInput(task.due_at));
  }

  async function saveEdit(task) {
    if (busy || !editTitle.trim()) return;
    setBusy(true);
    setError('');
    try {
      const updated = await api.updateTask(task.id, {
        title: editTitle.trim(),
        due_at: toIso(editDue),
      });
      setTasks((current) => current.map((item) => (item.id === task.id ? updated : item)));
      setEditingId(null);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function removeTask(task) {
    if (!window.confirm(`删除待办「${task.title}」？`)) return;
    setBusy(true);
    setError('');
    try {
      await api.deleteTask(task.id);
      setTasks((current) => current.filter((item) => item.id !== task.id));
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  const activeTasks = tasks.filter((task) => !task.done);
  const doneTasks = tasks.filter((task) => task.done);
  const now = Date.now();
  const overdue = activeTasks.filter(
    (task) => task.due_at && new Date(task.due_at).getTime() < now,
  ).length;
  const upcoming = activeTasks.filter(
    (task) => task.due_at && new Date(task.due_at).getTime() >= now,
  ).length;
  const completion = tasks.length ? Math.round((doneTasks.length / tasks.length) * 100) : 0;
  const visible = showDone ? tasks : activeTasks;

  return (
    <div className="tasks-layout">
      <section className="tasks-main">
        <header className="tasks-head">
          <div>
            <p className="eyebrow">DEADLINES</p>
            <h2>待办</h2>
            <p className="muted">从作业说明里提取候选截止时间，确认后才会加入清单。</p>
          </div>
          <button
            type="button"
            className="ghost-btn small"
            onClick={() => setShowForm((value) => !value)}
          >
            {showForm ? '收起' : '+ 手动添加'}
          </button>
        </header>

        {error && <div className="alert error">{error}</div>}
        {scanNotice && <div className="phase-note">{scanNotice}</div>}

        {showForm && (
          <form className="task-create" onSubmit={addTask}>
            <label className="field">
              待办标题
              <input
                maxLength="200"
                placeholder="例如：提交实验一报告"
                value={title}
                onChange={(event) => setTitle(event.target.value)}
              />
            </label>
            <label className="field">
              截止时间（可选）
              <input
                type="datetime-local"
                value={due}
                onChange={(event) => setDue(event.target.value)}
              />
            </label>
            <div className="task-create-actions">
              <button type="button" className="ghost-btn small" onClick={() => setShowForm(false)}>
                取消
              </button>
              <button
                type="submit"
                className="primary-btn small"
                disabled={busy || !title.trim()}
              >
                {busy ? '保存中…' : '保存待办'}
              </button>
            </div>
          </form>
        )}

        {candidates.length > 0 && (
          <section className="candidate-panel">
            <header className="candidate-panel-head">
              <div>
                <h3>候选截止日期</h3>
                <p className="muted">确认前不会写入待办；可以按需修改日期时间。</p>
              </div>
              <button
                type="button"
                className="ghost-btn small"
                onClick={() => {
                  setCandidates([]);
                  setDrafts({});
                }}
              >
                全部忽略
              </button>
            </header>
            <div className="candidate-list">
              {candidates.map((candidate) => (
                <article className="candidate-row" key={candidate.key}>
                  <div className="candidate-main">
                    <div className="candidate-head">
                      <strong>{candidate.title}</strong>
                      {candidate.needs_confirmation && (
                        <span className="candidate-flag">待确认</span>
                      )}
                    </div>
                    <p className="candidate-meta">
                      {candidate.due_text} · {candidate.source_file_name} · {candidate.locator}
                    </p>
                    {candidate.confirmation_reason && (
                      <p className="candidate-reason">{candidate.confirmation_reason}</p>
                    )}
                    <blockquote>{candidate.snippet}</blockquote>
                  </div>
                  <div className="candidate-actions">
                    <label className="field compact-field">
                      截止时间
                      <input
                        type="datetime-local"
                        value={drafts[candidate.key] || ''}
                        onChange={(event) => updateDraft(candidate.key, event.target.value)}
                      />
                    </label>
                    <div className="candidate-buttons">
                      <button
                        type="button"
                        className="primary-btn small"
                        disabled={busy}
                        onClick={() => confirmCandidate(candidate)}
                      >
                        确认添加
                      </button>
                      <button
                        type="button"
                        className="ghost-btn small"
                        disabled={busy}
                        onClick={() => dropCandidate(candidate.key)}
                      >
                        忽略
                      </button>
                    </div>
                  </div>
                </article>
              ))}
            </div>
          </section>
        )}

        <div className="tasks-toolbar">
          <div className="filter-chips">
            <button
              type="button"
              className={`filter-chip${!showDone ? ' active' : ''}`}
              onClick={() => setShowDone(false)}
            >
              未完成<span>{activeTasks.length}</span>
            </button>
            <button
              type="button"
              className={`filter-chip${showDone ? ' active' : ''}`}
              onClick={() => setShowDone(true)}
            >
              全部<span>{tasks.length}</span>
            </button>
          </div>
          {overdue > 0 && <span className="overdue-note">{overdue} 项已逾期</span>}
        </div>

        {loading ? (
          <div className="boot compact">
            <span className="spinner" />
            <span>正在读取待办…</span>
          </div>
        ) : visible.length === 0 ? (
          <div className="empty compact">
            <div className="empty-mark">✓</div>
            <h3>{activeTasks.length === 0 && tasks.length > 0 ? '待办都完成了' : '还没有待办'}</h3>
            <p>
              {tasks.length
                ? '可以在右侧扫描资料里的截止日期，或手动添加。'
                : '从右侧扫描资料中的截止日期，确认后就会出现在这里。'}
            </p>
            {doneTasks.length > 0 && !showDone && (
              <button type="button" className="ghost-btn small" onClick={() => setShowDone(true)}>
                查看已完成
              </button>
            )}
          </div>
        ) : (
          <div className="task-list">
            {visible.map((task) => {
              const isOverdue = !task.done
                && task.due_at
                && new Date(task.due_at).getTime() < now;
              if (editingId === task.id) {
                return (
                  <article className="task-row editing" key={task.id}>
                    <div className="task-edit-form">
                      <label className="field">
                        标题
                        <input
                          maxLength="200"
                          value={editTitle}
                          onChange={(event) => setEditTitle(event.target.value)}
                        />
                      </label>
                      <label className="field">
                        截止时间
                        <input
                          type="datetime-local"
                          value={editDue}
                          onChange={(event) => setEditDue(event.target.value)}
                        />
                      </label>
                      <div className="task-create-actions">
                        <button
                          type="button"
                          className="ghost-btn small"
                          onClick={() => setEditingId(null)}
                        >
                          取消
                        </button>
                        <button
                          type="button"
                          className="primary-btn small"
                          disabled={busy || !editTitle.trim()}
                          onClick={() => saveEdit(task)}
                        >
                          保存
                        </button>
                      </div>
                    </div>
                  </article>
                );
              }
              return (
                <article
                  className={`task-row${task.done ? ' done' : ''}${isOverdue ? ' overdue' : ''}`}
                  key={task.id}
                >
                  <label className="task-check">
                    <input
                      type="checkbox"
                      checked={task.done}
                      disabled={busy}
                      onChange={() => toggleDone(task)}
                    />
                    <span className="task-checkmark" />
                  </label>
                  <div className="task-main">
                    <strong>{task.title}</strong>
                    <div className="task-meta">
                      {task.due_at ? (
                        <span className={`task-due${isOverdue ? ' overdue' : ''}`}>
                          {isOverdue ? '已逾期 · ' : ''}截止 {formatDate(task.due_at)}
                        </span>
                      ) : (
                        <span className="task-due">未设置截止时间</span>
                      )}
                      {task.source_file_name && (
                        <span>来源：{task.source_file_name}</span>
                      )}
                      {task.done && <span className="task-done-flag">已完成</span>}
                    </div>
                    {task.source_snippet && (
                      <blockquote className="task-snippet">{task.source_snippet}</blockquote>
                    )}
                  </div>
                  <div className="task-actions">
                    <button
                      type="button"
                      className="ghost-btn small"
                      disabled={busy}
                      onClick={() => startEdit(task)}
                    >
                      编辑
                    </button>
                    <button
                      type="button"
                      className="danger-ghost small"
                      disabled={busy}
                      onClick={() => removeTask(task)}
                    >
                      删除
                    </button>
                  </div>
                </article>
              );
            })}
          </div>
        )}
      </section>

      <aside className="tasks-side">
        <section className="tasks-side-card">
          <h3>进度</h3>
          <div className="task-stats">
            <div><strong>{activeTasks.length}</strong><span>未完成</span></div>
            <div><strong className={overdue ? 'danger-text' : ''}>{overdue}</strong><span>已逾期</span></div>
            <div><strong>{upcoming}</strong><span>待到期</span></div>
            <div><strong>{doneTasks.length}</strong><span>已完成</span></div>
          </div>
          <div className="progress-track">
            <span style={{ width: `${completion}%` }} />
          </div>
          <p className="muted">完成度 {completion}%</p>
        </section>

        <section className="tasks-side-card">
          <h3>从资料提取</h3>
          <p className="muted">扫描已解析资料中的“截止 / 提交 / deadline”等表述。</p>
          <button
            type="button"
            className="primary-btn block"
            disabled={scanning || !readyFiles.length}
            onClick={scanCandidates}
          >
            {scanning ? '扫描中…' : '扫描截止日期'}
          </button>
          {!readyFiles.length && (
            <p className="muted">请先在「资料」页上传并等待解析完成。</p>
          )}
          <small>扫描结果只是候选，确认后才会创建待办。</small>
        </section>
      </aside>
    </div>
  );
}
