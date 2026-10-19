import React, { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { api } from '../api';
import FileDrop from '../components/FileDrop';
import ChatPanel from '../components/ChatPanel';
import QuizPanel from '../components/QuizPanel';
import FlashcardsPanel from '../components/FlashcardsPanel';
import TasksPanel from '../components/TasksPanel';
import Modal from '../components/Modal';
import StatusBadge from '../components/StatusBadge';
import TopBar from '../components/TopBar';
import { fileExtension, formatBytes, formatDate } from '../utils';

const TABS = [
  { id: 'files', label: '资料' },
  { id: 'chat', label: '问答' },
  { id: 'quiz', label: '练习' },
  { id: 'cards', label: '复习卡' },
  { id: 'tasks', label: '待办' },
];

const ACTIVE_STATUSES = new Set(['queued', 'processing']);

export default function CoursePage() {
  const { courseId } = useParams();
  const [course, setCourse] = useState(null);
  const [files, setFiles] = useState([]);
  const [loading, setLoading] = useState(true);
  const [notFound, setNotFound] = useState(false);
  const [error, setError] = useState('');
  const [tab, setTab] = useState('files');
  const [uploading, setUploading] = useState(false);
  const [uploadMessage, setUploadMessage] = useState('');
  const [uploadErrors, setUploadErrors] = useState([]);

  const [previewFile, setPreviewFile] = useState(null);
  const [previewPages, setPreviewPages] = useState([]);
  const [previewOrd, setPreviewOrd] = useState(null);
  const [previewDetail, setPreviewDetail] = useState(null);
  const [previewError, setPreviewError] = useState('');
  const [previewLoading, setPreviewLoading] = useState(false);

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [courseId]);

  useEffect(() => {
    if (!files.some((file) => ACTIVE_STATUSES.has(file.status))) return undefined;
    const timer = setInterval(async () => {
      try {
        setFiles(await api.files(courseId));
      } catch {
        // 轮询失败时保持当前列表，下一次再试
      }
    }, 2000);
    return () => clearInterval(timer);
  }, [files, courseId]);

  async function load(options = {}) {
    const { silent = false } = options;
    if (!silent) setLoading(true);
    setError('');
    setNotFound(false);
    try {
      const [courseData, fileData] = await Promise.all([
        api.course(courseId),
        api.files(courseId),
      ]);
      setCourse(courseData);
      setFiles(fileData);
    } catch (err) {
      if (err.status === 404) setNotFound(true);
      else setError(err.message);
    } finally {
      if (!silent) setLoading(false);
    }
  }

  async function handleFiles(list) {
    const allowed = list.filter((file) =>
      /\.(pdf|pptx|docx|md|markdown|txt)$/i.test(file.name),
    );
    const errors = list
      .filter((file) => !allowed.includes(file))
      .map((file) => `${file.name}：不支持的文件类型`);

    if (!allowed.length) {
      setUploadErrors(errors);
      return;
    }

    setUploading(true);
    setUploadErrors([]);
    setError('');
    let done = 0;
    setUploadMessage(`正在上传 0/${allowed.length}`);
    for (const file of allowed) {
      try {
        await api.uploadFile(courseId, file);
      } catch (err) {
        errors.push(`${file.name}：${err.message}`);
      }
      done += 1;
      setUploadMessage(`正在上传 ${done}/${allowed.length}`);
    }
    setUploading(false);
    setUploadMessage('');
    setUploadErrors(errors);
    await load({ silent: true });
  }

  async function handleDeleteFile(file) {
    if (!window.confirm(`删除「${file.name}」？`)) return;
    try {
      await api.deleteFile(file.id);
      setFiles((prev) => prev.filter((item) => item.id !== file.id));
      setCourse((prev) =>
        prev ? { ...prev, file_count: Math.max(0, prev.file_count - 1) } : prev,
      );
    } catch (err) {
      setError(err.message);
    }
  }

  async function handleReprocess(file) {
    try {
      await api.reprocessFile(file.id);
      await load({ silent: true });
    } catch (err) {
      setError(err.message);
    }
  }

  function closePreview() {
    setPreviewFile(null);
    setPreviewPages([]);
    setPreviewOrd(null);
    setPreviewDetail(null);
    setPreviewError('');
    setPreviewLoading(false);
  }

  async function selectPreviewPage(fileId, ord) {
    setPreviewOrd(ord);
    setPreviewDetail(null);
    try {
      setPreviewDetail(await api.page(fileId, ord));
    } catch (err) {
      setPreviewError(err.message);
    }
  }

  async function openPreview(file) {
    setPreviewFile(file);
    setPreviewPages([]);
    setPreviewOrd(null);
    setPreviewDetail(null);
    setPreviewError('');
    setPreviewLoading(true);
    try {
      const pages = await api.pages(file.id);
      setPreviewPages(pages);
      if (pages.length) await selectPreviewPage(file.id, pages[0].ord);
    } catch (err) {
      setPreviewError(err.message);
    } finally {
      setPreviewLoading(false);
    }
  }

  if (loading) {
    return (
      <div className="page">
        <TopBar />
        <div className="boot">
          <span className="spinner large" />
          <p>正在加载课程…</p>
        </div>
      </div>
    );
  }

  if (notFound) {
    return (
      <div className="page">
        <TopBar />
        <main className="container">
          <section className="empty">
            <div className="empty-mark">🔍</div>
            <h2>课程不存在或无权访问</h2>
            <p>它可能已被删除，或者属于其他账户。</p>
            <Link className="primary-btn" to="/">
              返回课程列表
            </Link>
          </section>
        </main>
      </div>
    );
  }

  if (!course) return null;

  return (
    <div className="page">
      <TopBar />
      <main className="container">
        <Link to="/" className="back-link">
          ← 返回课程列表
        </Link>

        <header className="course-head" style={{ '--course-color': course.color }}>
          <div className="course-head-main">
            <span className="course-dot large" />
            <div>
              <h1>{course.name}</h1>
              <p>
                {course.semester || '未填写学期'} · {course.file_count} 份资料
              </p>
            </div>
          </div>
        </header>

        <nav className="tabs">
          {TABS.map((item) => (
            <button
              key={item.id}
              type="button"
              className={`tab${tab === item.id ? ' active' : ''}`}
              onClick={() => setTab(item.id)}
            >
              {item.label}
              {item.hint && <em>{item.hint}</em>}
            </button>
          ))}
        </nav>

        {error && <div className="alert error">{error}</div>}
        {uploadErrors.length > 0 && (
          <div className="alert error">
            <strong>部分文件上传失败</strong>
            <ul>
              {uploadErrors.map((message) => (
                <li key={message}>{message}</li>
              ))}
            </ul>
          </div>
        )}

        {tab === 'chat' ? (
          <ChatPanel
            courseId={courseId}
            readyFileCount={files.filter((file) => file.status === 'ready').length}
          />
        ) : tab === 'quiz' ? (
          <QuizPanel courseId={courseId} files={files} />
        ) : tab === 'cards' ? (
          <FlashcardsPanel courseId={courseId} files={files} />
        ) : tab === 'tasks' ? (
          <TasksPanel courseId={courseId} files={files} />
        ) : (
          <>
            <div className="phase-note">
              资料、带引用问答、小测、复习卡与待办均已开放；所有学习记录按课程隔离。
            </div>

            <FileDrop onFiles={handleFiles} busy={uploading} />
            {uploading && (
              <div className="upload-progress">
                <span className="spinner" />
                {uploadMessage}
              </div>
            )}

            <section className="file-panel">
              <header className="panel-head">
                <h2>课程资料</h2>
                <span>{files.length} 个文件</span>
              </header>

              {files.length === 0 ? (
                <div className="empty compact">
                  <p>还没有资料，上传第一份讲义或作业说明吧。</p>
                </div>
              ) : (
                <ul className="file-list">
                  {files.map((file) => (
                    <li key={file.id} className="file-row">
                      <span className={`file-type type-${fileExtension(file.name).toLowerCase()}`}>
                        {fileExtension(file.name)}
                      </span>
                      <div className="file-main">
                        <strong title={file.name}>{file.name}</strong>
                        <span className="file-meta">
                          {formatBytes(file.size_bytes)} · 上传于 {formatDate(file.created_at)}
                        </span>
                        {file.status === 'ready' && (
                          <span className="file-meta">
                            {file.page_count} 页/节 · {file.chunk_count} 个文本块
                          </span>
                        )}
                        {file.warning && <span className="file-warning">{file.warning}</span>}
                        {file.error_message && (
                          <span className="file-error">{file.error_message}</span>
                        )}
                      </div>
                      <StatusBadge status={file.status} />
                      <div className="file-actions">
                        {file.status === 'ready' && (
                          <button
                            type="button"
                            className="ghost-btn small"
                            onClick={() => openPreview(file)}
                          >
                            预览
                          </button>
                        )}
                        {file.status === 'failed' && (
                          <button
                            type="button"
                            className="ghost-btn small"
                            onClick={() => handleReprocess(file)}
                          >
                            重新解析
                          </button>
                        )}
                        <a
                          className="ghost-btn small"
                          href={`/api/v1/files/${file.id}/download`}
                        >
                          下载
                        </a>
                        <button
                          type="button"
                          className="danger-ghost small"
                          onClick={() => handleDeleteFile(file)}
                        >
                          删除
                        </button>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          </>
        )}
      </main>

      {previewFile && (
        <Modal
          title={previewFile.name}
          subtitle={`${previewPages.length} 个可定位单元`}
          width={780}
          onClose={closePreview}
        >
          {previewError && <div className="alert error">{previewError}</div>}
          {previewLoading ? (
            <div className="boot compact">
              <span className="spinner" />
              <span>正在读取原文…</span>
            </div>
          ) : previewPages.length === 0 ? (
            <p className="muted">暂无可预览的文本。</p>
          ) : (
            <div className="preview-layout">
              <div className="preview-list">
                {previewPages.map((page) => (
                  <button
                    key={page.ord}
                    type="button"
                    className={`preview-item${page.ord === previewOrd ? ' active' : ''}`}
                    onClick={() => selectPreviewPage(previewFile.id, page.ord)}
                  >
                    <strong>
                      {page.page_no ? `第 ${page.page_no} 页` : `第 ${page.ord} 节`}
                    </strong>
                    <span>
                      {page.heading || '未命名章节'} · {page.char_count} 字
                    </span>
                  </button>
                ))}
              </div>
              <div className="preview-text">
                {previewDetail ? (
                  <>
                    <p className="preview-heading">
                      {previewDetail.heading ||
                        (previewDetail.page_no
                          ? `第 ${previewDetail.page_no} 页`
                          : '正文')}
                    </p>
                    <pre>{previewDetail.text}</pre>
                  </>
                ) : (
                  <p className="muted">选择左侧段落查看原文。</p>
                )}
              </div>
            </div>
          )}
        </Modal>
      )}
    </div>
  );
}
