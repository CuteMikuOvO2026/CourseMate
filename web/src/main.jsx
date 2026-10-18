import React, { useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import './styles.css';

function StatusPill({ health }) {
  if (health.state === 'checking') {
    return <span className="pill"><i className="dot" />正在检查后端…</span>;
  }
  if (health.state === 'error') {
    return <span className="pill"><i className="dot bad" />后端未响应</span>;
  }
  return (
    <span className="pill">
      <i className="dot ok" />
      后端在线 · v{health.data.version} · 数据库 {health.data.database}
    </span>
  );
}

function App() {
  const [health, setHealth] = useState({ state: 'checking' });

  useEffect(() => {
    let cancelled = false;
    fetch('/api/v1/health')
      .then((response) => response.json())
      .then((data) => { if (!cancelled) setHealth({ state: 'ok', data }); })
      .catch(() => { if (!cancelled) setHealth({ state: 'error' }); });
    return () => { cancelled = true; };
  }, []);

  return (
    <main className="stage">
      <section className="card">
        <div className="brand">
          <span className="brand-mark">CM</span>
          <div>
            <h1>CourseMate</h1>
            <p className="sub">课程资料学习助手</p>
          </div>
        </div>

        <h2>骨架已就绪</h2>
        <p className="lead">
          后端健康检查已通过，前端构建链可用。下一步将接入账户、课程与资料上传，
          再把解析、检索、问答、练习与复习逐个补齐。
        </p>

        <StatusPill health={health} />

        <div className="grid">
          <div className="step"><span>01</span>账户与课程隔离</div>
          <div className="step"><span>02</span>资料上传与解析</div>
          <div className="step"><span>03</span>带引用的资料问答</div>
          <div className="step"><span>04</span>小测、复习卡与待办</div>
        </div>

        <footer>
          健康检查 <code>/api/v1/health</code> · 接口文档 <code>/api/docs</code>
        </footer>
      </section>
    </main>
  );
}

createRoot(document.getElementById('root')).render(<App />);
