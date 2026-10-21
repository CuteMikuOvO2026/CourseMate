import React from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '../auth';

const ICONS = {
  files: (
    <>
      <path d="M4 5.5A1.5 1.5 0 0 1 5.5 4h3.2c.4 0 .8.2 1.1.4l1.2 1.2h6.5A1.5 1.5 0 0 1 19 7.1v9.4a1.5 1.5 0 0 1-1.5 1.5h-12A1.5 1.5 0 0 1 4 16.5Z" />
      <path d="M4 9.5h15" />
    </>
  ),
  chat: (
    <>
      <path d="M17 11.5a7 7 0 0 1-7 7H6.5L3 21l1-4.5A7 7 0 0 1 10 4.5a7 7 0 0 1 7 7Z" />
      <path d="M9.5 10h5M9.5 13h3" />
    </>
  ),
  quiz: (
    <>
      <rect x="4" y="4" width="16" height="16" rx="2.5" />
      <path d="m8.5 12 2.2 2.2 4.8-4.8" />
    </>
  ),
  cards: (
    <>
      <rect x="3.5" y="6" width="13" height="12" rx="2" />
      <path d="M7 4.5h11a2 2 0 0 1 2 2v9" />
    </>
  ),
  tasks: (
    <>
      <circle cx="12" cy="12" r="8" />
      <path d="M12 8v4l2.8 2" />
    </>
  ),
  courses: (
    <>
      <rect x="4" y="4" width="7" height="7" rx="1.8" />
      <rect x="13" y="4" width="7" height="7" rx="1.8" />
      <rect x="4" y="13" width="7" height="7" rx="1.8" />
      <rect x="13" y="13" width="7" height="7" rx="1.8" />
    </>
  ),
  logout: <path d="M15 4h3a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-3M10 8l-4 4 4 4M6 12h10" />,
};

function Icon({ name }) {
  return (
    <svg
      className="nav-icon"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {ICONS[name]}
    </svg>
  );
}

export default function AppShell({ course = null, activeTab, onTabChange, children }) {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  async function handleLogout() {
    await logout();
    navigate('/login', { replace: true });
  }

  const navItems = course
    ? [
        { id: 'files', label: '资料', icon: 'files', badge: course.file_count || 0 },
        { id: 'chat', label: '问答', icon: 'chat' },
        { id: 'quiz', label: '练习', icon: 'quiz' },
        { id: 'cards', label: '复习卡', icon: 'cards' },
        { id: 'tasks', label: '待办', icon: 'tasks' },
      ]
    : [{ id: 'courses', label: '我的课程', icon: 'courses', to: '/' }];

  return (
    <div className="shell">
      <aside className="shell-side">
        <Link to="/" className="shell-brand" title="CourseMate">
          <span className="brand-mark small">CM</span>
          <span className="shell-brand-text">
            <strong>CourseMate</strong>
            <small>课程资料学习助手</small>
          </span>
        </Link>

        {course && (
          <Link to="/" className="shell-course" style={{ '--course-color': course.color }}>
            <span className="course-dot" />
            <span className="shell-course-text">
              <strong title={course.name}>{course.name}</strong>
              <small>{course.semester || '未填写学期'}</small>
            </span>
          </Link>
        )}

        <nav className="shell-nav" aria-label="主导航">
          {navItems.map((item) =>
            item.to ? (
              <Link key={item.id} to={item.to} className="shell-nav-item">
                <Icon name={item.icon} />
                <span className="shell-nav-label">{item.label}</span>
              </Link>
            ) : (
              <button
                key={item.id}
                type="button"
                className={`shell-nav-item${activeTab === item.id ? ' active' : ''}`}
                onClick={() => onTabChange(item.id)}
                title={item.label}
                aria-current={activeTab === item.id ? 'page' : undefined}
              >
                <Icon name={item.icon} />
                <span className="shell-nav-label">{item.label}</span>
                {item.badge ? <em className="shell-nav-badge">{item.badge}</em> : null}
              </button>
            ),
          )}
        </nav>

        {course && (
          <Link to="/" className="shell-back" title="返回课程列表">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="M14 6l-6 6 6 6" />
            </svg>
            <span className="shell-nav-label">所有课程</span>
          </Link>
        )}

        <div className="shell-user">
          <span className="shell-avatar" title={user?.username}>
            {(user?.username || '?').slice(0, 1).toUpperCase()}
          </span>
          <span className="shell-user-text">
            <strong title={user?.username}>{user?.username}</strong>
            <small>个人学习空间</small>
          </span>
          <button
            type="button"
            className="icon-btn"
            onClick={handleLogout}
            title="退出登录"
            aria-label="退出登录"
          >
            <Icon name="logout" />
          </button>
        </div>
      </aside>

      <div className="shell-main">{children}</div>
    </div>
  );
}
