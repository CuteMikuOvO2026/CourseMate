import React, { useEffect, useMemo, useState } from 'react';
import { api } from '../api';
import { formatDate } from '../utils';

const MASTERY_LABELS = {
  new: '未学',
  mastered: '已掌握',
  unfamiliar: '不熟',
};

const FILTERS = [
  { id: 'all', label: '全部' },
  { id: 'new', label: '未学' },
  { id: 'unfamiliar', label: '不熟' },
  { id: 'mastered', label: '已掌握' },
];

export default function FlashcardsPanel({ courseId, files }) {
  const readyFiles = useMemo(
    () => files.filter((file) => file.status === 'ready'),
    [files],
  );
  const [cards, setCards] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [selected, setSelected] = useState([]);
  const [count, setCount] = useState(8);
  const [filter, setFilter] = useState('all');
  const [flipped, setFlipped] = useState({});
  const [showForm, setShowForm] = useState(false);
  const [front, setFront] = useState('');
  const [back, setBack] = useState('');

  useEffect(() => {
    loadCards();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [courseId]);

  async function loadCards() {
    setLoading(true);
    setError('');
    try {
      setCards(await api.flashcards(courseId));
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  function toggleFile(id) {
    setSelected((current) => (current.includes(id)
      ? current.filter((item) => item !== id)
      : [...current, id]));
  }

  function toggleFlip(id) {
    setFlipped((current) => ({ ...current, [id]: !current[id] }));
  }

  async function generate(event) {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setError('');
    try {
      const created = await api.generateFlashcards(courseId, {
        file_ids: selected,
        count: Number(count),
      });
      setCards((current) => [...created, ...current]);
      setFlipped({});
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function createManual(event) {
    event.preventDefault();
    if (busy || !front.trim() || !back.trim()) return;
    setBusy(true);
    setError('');
    try {
      const card = await api.createFlashcard(courseId, {
        front: front.trim(),
        back: back.trim(),
      });
      setCards((current) => [card, ...current]);
      setFront('');
      setBack('');
      setShowForm(false);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function review(card, mastery) {
    if (busy) return;
    setBusy(true);
    setError('');
    try {
      const updated = await api.reviewFlashcard(card.id, mastery);
      setCards((current) => current.map((item) => (item.id === card.id ? updated : item)));
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function remove(card) {
    if (!window.confirm(`删除复习卡「${card.front}」？`)) return;
    setBusy(true);
    setError('');
    try {
      await api.deleteFlashcard(card.id);
      setCards((current) => current.filter((item) => item.id !== card.id));
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  const counts = {
    all: cards.length,
    new: cards.filter((card) => card.mastery === 'new').length,
    unfamiliar: cards.filter((card) => card.mastery === 'unfamiliar').length,
    mastered: cards.filter((card) => card.mastery === 'mastered').length,
  };
  const visible = filter === 'all'
    ? cards
    : cards.filter((card) => card.mastery === filter);

  return (
    <div className="cards-layout">
      <section className="cards-main">
        <header className="cards-head">
          <div>
            <p className="eyebrow">REVIEW</p>
            <h2>复习卡</h2>
            <p className="muted">点击卡片翻面，用「掌握 / 不熟」记录这次复习的结果。</p>
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

        {showForm && (
          <form className="card-create" onSubmit={createManual}>
            <label className="field">
              问题
              <textarea
                rows="2"
                maxLength="300"
                placeholder="例如：三次握手的作用是什么？"
                value={front}
                onChange={(event) => setFront(event.target.value)}
              />
            </label>
            <label className="field">
              答案
              <textarea
                rows="3"
                maxLength="3000"
                placeholder="写下答案，或从资料中复制一段原文。"
                value={back}
                onChange={(event) => setBack(event.target.value)}
              />
            </label>
            <div className="card-create-actions">
              <button
                type="button"
                className="ghost-btn small"
                onClick={() => setShowForm(false)}
              >
                取消
              </button>
              <button
                type="submit"
                className="primary-btn small"
                disabled={busy || !front.trim() || !back.trim()}
              >
                {busy ? '保存中…' : '保存卡片'}
              </button>
            </div>
          </form>
        )}

        <div className="cards-toolbar">
          <div className="filter-chips">
            {FILTERS.map((item) => (
              <button
                key={item.id}
                type="button"
                className={`filter-chip${filter === item.id ? ' active' : ''}`}
                onClick={() => setFilter(item.id)}
              >
                {item.label}
                <span>{counts[item.id]}</span>
              </button>
            ))}
          </div>
          <span className="muted">{visible.length} 张</span>
        </div>

        {loading ? (
          <div className="boot compact">
            <span className="spinner" />
            <span>正在读取复习卡…</span>
          </div>
        ) : visible.length === 0 ? (
          <div className="empty compact">
            <div className="empty-mark">✦</div>
            <h3>{cards.length ? '这个分类还没有卡片' : '还没有复习卡'}</h3>
            <p>
              {cards.length
                ? '切换上方分类，或继续复习其他卡片。'
                : '从右侧选择资料生成，或手动添加一张。'}
            </p>
          </div>
        ) : (
          <div className="flashcard-grid">
            {visible.map((card) => (
              <article className={`flashcard ${card.mastery}`} key={card.id}>
                <button
                  type="button"
                  className="flashcard-flip"
                  onClick={() => toggleFlip(card.id)}
                  aria-label="翻转复习卡"
                >
                  <div className={`flashcard-inner${flipped[card.id] ? ' flipped' : ''}`}>
                    <div className="flashcard-face flashcard-front">
                      <span className="flashcard-kicker">问题</span>
                      <p>{card.front}</p>
                      <small>点击查看答案</small>
                    </div>
                    <div className="flashcard-face flashcard-back">
                      <span className="flashcard-kicker">答案</span>
                      <p>{card.back}</p>
                      <small>点击翻回问题</small>
                    </div>
                  </div>
                </button>

                <div className="flashcard-meta">
                  <span className={`mastery-badge ${card.mastery}`}>
                    {MASTERY_LABELS[card.mastery] || card.mastery}
                  </span>
                  <span>
                    {card.review_count ? `复习 ${card.review_count} 次` : '尚未复习'}
                  </span>
                  {card.last_reviewed_at && (
                    <span>最近 {formatDate(card.last_reviewed_at)}</span>
                  )}
                </div>

                {card.sources.length > 0 && (
                  <div className="flashcard-sources">
                    {card.sources.map((source) => (
                      <div className="flashcard-source" key={source.chunk_id}>
                        <span title={source.heading}>
                          {source.file_name} · {source.locator}
                        </span>
                        <blockquote>{source.snippet}</blockquote>
                        <a href={`/api/v1/files/${source.file_id}/download`}>
                          打开原文件
                        </a>
                      </div>
                    ))}
                  </div>
                )}

                <div className="flashcard-actions">
                  <button
                    type="button"
                    className="ghost-btn small"
                    disabled={busy}
                    onClick={() => review(card, 'mastered')}
                  >
                    已掌握
                  </button>
                  <button
                    type="button"
                    className="ghost-btn small"
                    disabled={busy}
                    onClick={() => review(card, 'unfamiliar')}
                  >
                    不熟
                  </button>
                  <button
                    type="button"
                    className="danger-ghost small"
                    disabled={busy}
                    onClick={() => remove(card)}
                  >
                    删除
                  </button>
                </div>
              </article>
            ))}
          </div>
        )}
      </section>

      <aside className="cards-side">
        <section className="cards-side-card">
          <h3>复习概览</h3>
          <div className="cards-stats">
            {FILTERS.map((item) => (
              <div key={item.id}>
                <strong>{counts[item.id]}</strong>
                <span>{item.label}</span>
              </div>
            ))}
          </div>
          <p className="muted">掌握度只保存在当前课程，不会影响其他课程。</p>
        </section>

        <form className="cards-side-card" onSubmit={generate}>
          <h3>从资料生成</h3>
          <p className="muted">选择资料范围；重复生成会自动跳过已有卡片。</p>
          <fieldset className="card-files">
            <legend>资料范围</legend>
            {readyFiles.map((file) => (
              <label className="card-file-option" key={file.id}>
                <input
                  type="checkbox"
                  checked={selected.includes(file.id)}
                  onChange={() => toggleFile(file.id)}
                />
                <span>{file.name}</span>
              </label>
            ))}
            {!readyFiles.length && <p className="muted">暂无已解析资料。</p>}
            {readyFiles.length > 0 && <small>不选择时使用全部已解析资料</small>}
          </fieldset>
          <label className="field">
            数量
            <select value={count} onChange={(event) => setCount(event.target.value)}>
              {[5, 8, 10, 15, 20].map((value) => (
                <option key={value} value={value}>{value} 张</option>
              ))}
            </select>
          </label>
          <button
            type="submit"
            className="primary-btn block"
            disabled={busy || !readyFiles.length}
          >
            {busy ? '生成中…' : '生成复习卡'}
          </button>
        </form>
      </aside>
    </div>
  );
}
