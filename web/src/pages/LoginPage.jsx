import React, { useState } from 'react';
import { Navigate, useNavigate } from 'react-router-dom';
import { useAuth } from '../auth';

export default function LoginPage() {
  const { user, login, register } = useAuth();
  const navigate = useNavigate();
  const [mode, setMode] = useState('login');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);

  if (user) return <Navigate to="/" replace />;

  async function handleSubmit(event) {
    event.preventDefault();
    setError('');
    if (!username.trim()) {
      setError('请输入用户名');
      return;
    }
    if (username.trim().length < 2) {
      setError('用户名至少 2 个字符');
      return;
    }
    if (password.length < 8) {
      setError('密码至少 8 位');
      return;
    }
    setSubmitting(true);
    try {
      if (mode === 'login') await login(username.trim(), password);
      else await register(username.trim(), password);
      navigate('/', { replace: true });
    } catch (err) {
      setError(err.message || '操作失败，请稍后重试');
    } finally {
      setSubmitting(false);
    }
  }

  function switchMode(next) {
    setMode(next);
    setError('');
  }

  return (
    <div className="auth-layout">
      <section className="auth-brand">
        <div className="auth-brand-top">
          <span className="brand-mark">CM</span>
          <span className="auth-brand-name">CourseMate</span>
        </div>
        <h1>
          把课程资料
          <br />
          变成可追溯的知识库
        </h1>
        <p>
          上传讲义、PPT 和作业说明，围绕资料提问、复习和练习。每个回答都带页码出处。
        </p>
        <ul>
          <li>只在当前课程内检索，不跨课程串数据</li>
          <li>回答附文件名、页码与原文片段</li>
          <li>资料不足时明确说不知道，而不是编造</li>
        </ul>
      </section>

      <section className="auth-panel">
        <div className="auth-tabs" role="tablist">
          <button
            type="button"
            className={mode === 'login' ? 'active' : ''}
            onClick={() => switchMode('login')}
          >
            登录
          </button>
          <button
            type="button"
            className={mode === 'register' ? 'active' : ''}
            onClick={() => switchMode('register')}
          >
            注册
          </button>
        </div>

        <h2>{mode === 'login' ? '欢迎回来' : '创建账户'}</h2>
        <p className="auth-sub">
          {mode === 'login'
            ? '继续你的课程复习。'
            : '一个用户名即可开始，资料与记录只属于你。'}
        </p>

        <form className="form" onSubmit={handleSubmit}>
          <label>
            用户名
            <input
              type="text"
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              placeholder={mode === 'register' ? '例如：xiaoming 或 小明' : '输入用户名'}
              autoComplete="username"
            />
          </label>
          <label>
            密码
            <input
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              placeholder={mode === 'register' ? '至少 8 位' : '输入密码'}
              autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
            />
          </label>

          {error && <div className="form-error">{error}</div>}

          <button className="primary-btn block" type="submit" disabled={submitting}>
            {submitting ? '请稍候…' : mode === 'login' ? '登录' : '注册并登录'}
          </button>
        </form>

        <p className="auth-foot">回答仅基于你上传的资料，并在资料不足时拒答。</p>
      </section>
    </div>
  );
}
