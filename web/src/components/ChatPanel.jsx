import React, { useEffect, useState } from 'react';
import { api } from '../api';

function CitationList({ citations = [] }) {
  if (!citations.length) return null;
  return (
    <section className="citation-list" aria-label="引用来源">
      <p className="citation-label">引用来源</p>
      {citations.map((citation) => (
        <article className="citation-card" key={`${citation.chunk_id}-${citation.index}`}>
          <div className="citation-card-head">
            <strong>[{citation.index}] {citation.file_name}</strong>
            <span>{citation.locator}</span>
          </div>
          <p>{citation.heading}</p>
          <blockquote>{citation.snippet}</blockquote>
          <a href={`/api/v1/files/${citation.file_id}/download`}>打开原文件</a>
        </article>
      ))}
    </section>
  );
}

function MessageBubble({ message }) {
  const assistant = message.role === 'assistant';
  return (
    <article className={`chat-message ${assistant ? 'assistant' : 'user'}`}>
      <span className="chat-avatar" aria-hidden="true">{assistant ? 'CM' : '我'}</span>
      <div className="chat-bubble-wrap">
        <div className="chat-bubble">
          <div className="chat-message-content">{message.content}</div>
        </div>
        {assistant && (
          <div className="answer-meta">
            {message.abstained ? '资料不足，已拒答' : `置信度：${message.confidence === 'high' ? '高' : message.confidence === 'medium' ? '中' : '低'}`}
            {message.mode && <span>· {message.mode === 'openai' ? '模型生成' : '原文摘录'}</span>}
          </div>
        )}
        {assistant && <CitationList citations={message.citations} />}
      </div>
    </article>
  );
}

export default function ChatPanel({ courseId, readyFileCount }) {
  const [conversations, setConversations] = useState([]);
  const [conversationId, setConversationId] = useState(null);
  const [messages, setMessages] = useState([]);
  const [question, setQuestion] = useState('');
  const [loading, setLoading] = useState(true);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    loadConversations();
    // 课程切换时不沿用上一门课的聊天状态
    setConversationId(null);
    setMessages([]);
    setQuestion('');
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [courseId]);

  async function loadConversations() {
    setLoading(true);
    try {
      setConversations(await api.conversations(courseId));
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  async function selectConversation(id) {
    if (id === conversationId) return;
    setConversationId(id);
    setHistoryLoading(true);
    setError('');
    try {
      setMessages(await api.messages(id));
    } catch (err) {
      setError(err.message);
    } finally {
      setHistoryLoading(false);
    }
  }

  function newConversation() {
    setConversationId(null);
    setMessages([]);
    setQuestion('');
    setError('');
  }

  async function submit(event) {
    event.preventDefault();
    const trimmed = question.trim();
    if (!trimmed || sending) return;
    if (!readyFileCount) {
      setError('请先上传并等待至少一份资料解析完成，再开始提问。');
      return;
    }

    setSending(true);
    setError('');
    setQuestion('');
    const optimistic = {
      id: `local-${Date.now()}`,
      role: 'user',
      content: trimmed,
      citations: [],
    };
    setMessages((prev) => [...prev, optimistic]);
    try {
      const result = await api.query(courseId, trimmed, conversationId);
      setConversationId(result.conversation_id);
      setMessages((prev) => [
        ...prev,
        {
          id: `answer-${Date.now()}`,
          role: 'assistant',
          content: result.answer,
          citations: result.citations,
          confidence: result.confidence,
          abstained: result.abstained,
          mode: result.mode,
        },
      ]);
      const refreshed = await api.conversations(courseId);
      setConversations(refreshed);
    } catch (err) {
      setMessages((prev) => prev.filter((item) => item !== optimistic));
      setQuestion(trimmed);
      setError(err.message);
    } finally {
      setSending(false);
    }
  }

  if (loading) {
    return <div className="boot compact"><span className="spinner" /><span>正在读取问答历史…</span></div>;
  }

  return (
    <section className="chat-layout">
      <aside className="conversation-sidebar">
        <button type="button" className="primary-btn small block" onClick={newConversation}>
          + 新建对话
        </button>
        <div className="conversation-list">
          {conversations.length === 0 ? (
            <p className="conversation-empty">提问后，历史会保存在这里。</p>
          ) : conversations.map((conversation) => (
            <button
              type="button"
              className={`conversation-item${conversation.id === conversationId ? ' active' : ''}`}
              key={conversation.id}
              onClick={() => selectConversation(conversation.id)}
              title={conversation.title}
            >
              {conversation.title}
            </button>
          ))}
        </div>
      </aside>

      <div className="chat-panel">
        {!readyFileCount && (
          <div className="phase-note">请先在「资料」页上传文件，并等待解析状态变为「已解析」。</div>
        )}
        {error && <div className="alert error">{error}</div>}
        <div className="chat-stream" aria-live="polite">
          {historyLoading ? (
            <div className="boot compact"><span className="spinner" /><span>正在读取对话…</span></div>
          ) : messages.length === 0 ? (
            <div className="chat-welcome">
              <div className="empty-mark">✦</div>
              <h2>围绕当前课程资料提问</h2>
              <p>回答只基于已解析的资料；每个要点都会附带文件、定位和原文片段。</p>
            </div>
          ) : messages.map((message) => <MessageBubble key={message.id} message={message} />)}
          {sending && (
            <article className="chat-message assistant">
              <span className="chat-avatar">CM</span>
              <div className="chat-bubble loading-answer"><span className="spinner" />正在检索课程资料…</div>
            </article>
          )}
        </div>
        <form className="chat-composer" onSubmit={submit}>
          <textarea
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            placeholder={readyFileCount ? '例如：三次握手的作用是什么？' : '等待资料解析完成后即可提问'}
            disabled={sending || !readyFileCount}
            rows="3"
            maxLength="1000"
          />
          <div className="composer-foot">
            <span>只会检索当前课程 · 无依据时会明确拒答</span>
            <button className="primary-btn small" type="submit" disabled={sending || !question.trim() || !readyFileCount}>
              {sending ? '回答中…' : '发送'}
            </button>
          </div>
        </form>
      </div>
    </section>
  );
}
