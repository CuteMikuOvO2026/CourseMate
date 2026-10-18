import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api';
import Modal from '../components/Modal';
import TopBar from '../components/TopBar';
import { COURSE_COLORS, formatDate } from '../utils';

const EMPTY_FORM = { name: '', semester: '', color: COURSE_COLORS[0] };

export default function CoursesPage() {
  const [courses, setCourses] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [creating, setCreating] = useState(false);
  const [form, setForm] = useState(EMPTY_FORM);
  const [formError, setFormError] = useState('');
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    load();
  }, []);

  async function load() {
    setLoading(true);
    try {
      setCourses(await api.courses());
      setError('');
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  function openCreate() {
    setForm(EMPTY_FORM);
    setFormError('');
    setCreating(true);
  }

  async function handleCreate(event) {
    event.preventDefault();
    if (!form.name.trim()) {
      setFormError('请输入课程名称');
      return;
    }
    setSaving(true);
    setFormError('');
    try {
      const course = await api.createCourse({
        name: form.name.trim(),
        semester: form.semester.trim() || null,
        color: form.color,
      });
      setCourses((prev) => [course, ...prev]);
      setCreating(false);
      setForm(EMPTY_FORM);
    } catch (err) {
      setFormError(err.message);
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete(course) {
    const confirmed = window.confirm(
      `删除课程「${course.name}」？其中的资料与学习记录都会一并删除。`,
    );
    if (!confirmed) return;
    try {
      await api.deleteCourse(course.id);
      setCourses((prev) => prev.filter((item) => item.id !== course.id));
    } catch (err) {
      setError(err.message);
    }
  }

  return (
    <div className="page">
      <TopBar />
      <main className="container">
        <header className="page-head">
          <div>
            <p className="eyebrow">我的课程</p>
            <h1>把资料收进一门课</h1>
            <p className="lede">每门课程独立存放资料与学习记录，互不干扰。</p>
          </div>
          <button type="button" className="primary-btn" onClick={openCreate}>
            + 新建课程
          </button>
        </header>

        {error && <div className="alert error">{error}</div>}

        {loading ? (
          <div className="course-grid">
            {[0, 1, 2].map((key) => (
              <div key={key} className="course-card skeleton" />
            ))}
          </div>
        ) : courses.length === 0 ? (
          <section className="empty">
            <div className="empty-mark">📚</div>
            <h2>还没有课程</h2>
            <p>先创建一门课，再上传讲义、PPT 或作业说明。</p>
            <button type="button" className="primary-btn" onClick={openCreate}>
              创建第一门课程
            </button>
          </section>
        ) : (
          <div className="course-grid">
            {courses.map((course) => (
              <article
                key={course.id}
                className="course-card"
                style={{ '--course-color': course.color }}
              >
                <Link to={`/courses/${course.id}`} className="course-link">
                  <span className="course-dot" />
                  <h2>{course.name}</h2>
                  <p>{course.semester || '未填写学期'}</p>
                  <div className="course-meta">
                    <span>{course.file_count} 份资料</span>
                    <span>{formatDate(course.created_at)}</span>
                  </div>
                </Link>
                <div className="course-actions">
                  <Link to={`/courses/${course.id}`} className="ghost-btn small">
                    进入
                  </Link>
                  <button
                    type="button"
                    className="danger-ghost small"
                    onClick={() => handleDelete(course)}
                  >
                    删除
                  </button>
                </div>
              </article>
            ))}
          </div>
        )}
      </main>

      {creating && (
        <Modal
          title="新建课程"
          subtitle="同一门课的资料、小测和复习卡会放在一起。"
          onClose={() => setCreating(false)}
          footer={
            <>
              <button type="button" className="ghost-btn" onClick={() => setCreating(false)}>
                取消
              </button>
              <button
                type="submit"
                form="create-course"
                className="primary-btn"
                disabled={saving}
              >
                {saving ? '创建中…' : '创建课程'}
              </button>
            </>
          }
        >
          <form id="create-course" className="form" onSubmit={handleCreate}>
            <label>
              课程名称
              <input
                value={form.name}
                onChange={(event) => setForm({ ...form, name: event.target.value })}
                placeholder="例如：计算机网络"
                autoFocus
              />
            </label>
            <label>
              学期（可选）
              <input
                value={form.semester}
                onChange={(event) => setForm({ ...form, semester: event.target.value })}
                placeholder="例如：2026 秋"
              />
            </label>
            <div className="field">
              <span>课程颜色</span>
              <div className="swatches">
                {COURSE_COLORS.map((color) => (
                  <button
                    key={color}
                    type="button"
                    className={`swatch${form.color === color ? ' active' : ''}`}
                    style={{ background: color }}
                    onClick={() => setForm({ ...form, color })}
                    aria-label={`课程颜色 ${color}`}
                  />
                ))}
              </div>
            </div>
            {formError && <div className="form-error">{formError}</div>}
          </form>
        </Modal>
      )}
    </div>
  );
}
