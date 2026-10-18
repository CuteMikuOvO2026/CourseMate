import React from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '../auth';

export default function TopBar() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  async function handleLogout() {
    await logout();
    navigate('/login', { replace: true });
  }

  return (
    <header className="topbar">
      <Link to="/" className="brand-link">
        <span className="brand-mark small">CM</span>
        <span className="brand-text">
          <strong>CourseMate</strong>
          <small>课程资料学习助手</small>
        </span>
      </Link>
      {user && (
        <div className="topbar-user">
          <span className="user-name" title={user.username}>
            {user.username}
          </span>
          <button type="button" className="ghost-btn small" onClick={handleLogout}>
            退出
          </button>
        </div>
      )}
    </header>
  );
}
