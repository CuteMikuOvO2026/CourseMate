import React, { useEffect, useState } from 'react';
import { api } from '../api';

export default function QuizPanel({ courseId, files }) {
  const [selected, setSelected] = useState([]);
  const [count, setCount] = useState(5);
  const [kinds, setKinds] = useState(['choice', 'short']);
  const [quiz, setQuiz] = useState(null);
  const [answers, setAnswers] = useState({});
  const [result, setResult] = useState(null);
  const [attempts, setAttempts] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    api.attempts(courseId).then(setAttempts).catch((err) => setError(err.message));
  }, [courseId]);

  function toggleFile(id) {
    setSelected((current) => current.includes(id)
      ? current.filter((item) => item !== id)
      : [...current, id]);
  }

  async function generate(event) {
    event.preventDefault();
    setBusy(true); setError(''); setResult(null); setAnswers({});
    try {
      setQuiz(await api.createQuiz(courseId, { file_ids: selected, count: Number(count), kinds }));
    } catch (err) { setError(err.message); }
    finally { setBusy(false); }
  }

  async function submit(event) {
    event.preventDefault();
    if (!quiz) return;
    if (quiz.questions.some((question) => !String(answers[question.id] || '').trim())) {
      setError('请先完成所有题目。'); return;
    }
    setBusy(true); setError('');
    try {
      const submitted = await api.submitQuiz(quiz.id, quiz.questions.map((question) => ({
        question_id: question.id, answer: answers[question.id],
      })));
      setResult(submitted);
      setAttempts(await api.attempts(courseId));
    } catch (err) { setError(err.message); }
    finally { setBusy(false); }
  }

  async function regrade(item, correct) {
    if (!result?.id || busy) return;
    setBusy(true); setError('');
    try {
      const updated = await api.regradeAttempt(result.id, item.question_id, correct);
      setResult(updated);
      setAttempts(await api.attempts(courseId));
    } catch (err) { setError(err.message); }
    finally { setBusy(false); }
  }

  return (
    <div className="quiz-layout">
      <section className="quiz-main">
        {error && <div className="alert error">{error}</div>}
        {!quiz && (
          <form className="quiz-setup" onSubmit={generate}>
            <div>
              <p className="eyebrow">PRACTICE</p>
              <h2>从课程资料生成小测</h2>
              <p className="muted">选择资料范围和题型；题目、答案与解析都能回溯到原文。</p>
            </div>
            <fieldset className="quiz-files">
              <legend>资料范围</legend>
              {files.filter((file) => file.status === 'ready').map((file) => (
                <label className="quiz-file-option" key={file.id}>
                  <input type="checkbox" checked={selected.includes(file.id)} onChange={() => toggleFile(file.id)} />
                  <span>{file.name}</span><small>{file.chunk_count} 个文本块</small>
                </label>
              ))}
              {!files.some((file) => file.status === 'ready') && <p className="muted">暂无已解析资料。</p>}
              <small>不选择时使用全部已解析资料</small>
            </fieldset>
            <div className="quiz-config-row">
              <label className="field">题量
                <select value={count} onChange={(event) => setCount(event.target.value)}>
                  {[3, 5, 8, 10, 15, 20].map((value) => <option key={value}>{value}</option>)}
                </select>
              </label>
              <fieldset className="quiz-kind-options"><legend>题型</legend>
                {[['choice', '选择题'], ['short', '简答题']].map(([value, label]) => (
                  <label key={value}><input type="checkbox" checked={kinds.includes(value)} onChange={() => setKinds((current) => current.includes(value) ? current.filter((item) => item !== value) : [...current, value])} />{label}</label>
                ))}
              </fieldset>
            </div>
            <button className="primary-btn" disabled={busy || !files.some((file) => file.status === 'ready') || !kinds.length}>
              {busy ? '正在生成…' : '生成小测'}
            </button>
          </form>
        )}

        {quiz && !result && (
          <form className="quiz-form" onSubmit={submit}>
            <header className="quiz-heading"><div><p className="eyebrow">课程练习</p><h2>{quiz.title}</h2></div><span>{quiz.question_count} 题</span></header>
            {quiz.questions.map((question) => (
              <article className="quiz-question" key={question.id}>
                <div className="quiz-question-title"><span>{question.ord}</span><strong>{question.kind === 'choice' ? '选择题' : '简答题'}</strong></div>
                <p>{question.prompt}</p>
                {question.kind === 'choice' ? (
                  <div className="quiz-options">{question.options.map((option, index) => {
                    const letter = String.fromCharCode(65 + index);
                    return <label key={letter} className={answers[question.id] === letter ? 'selected' : ''}>
                      <input type="radio" name={question.id} value={letter} checked={answers[question.id] === letter} onChange={() => setAnswers((current) => ({ ...current, [question.id]: letter }))} />
                      <span>{letter}</span>{option}
                    </label>;
                  })}</div>
                ) : <textarea className="quiz-short-answer" rows="3" placeholder="写下你的答案…" value={answers[question.id] || ''} onChange={(event) => setAnswers((current) => ({ ...current, [question.id]: event.target.value }))} />}
                {question.source && <small className="quiz-source">来源：{question.source.file_name} · {question.source.locator} · {question.source.heading}</small>}
              </article>
            ))}
            <div className="quiz-actions"><button type="button" className="ghost-btn" onClick={() => { setQuiz(null); setResult(null); }}>放弃本次练习</button><button className="primary-btn" disabled={busy}>{busy ? '判分中…' : '提交并查看结果'}</button></div>
          </form>
        )}

        {result && (
          <section className="quiz-results">
            <header className="quiz-result-summary"><p className="eyebrow">练习完成</p><h2>{result.score} <small>/ {result.total}</small></h2><p>{Math.round(result.score / result.total * 100)}% 正确 · 错题已记录，可回看解析和原文。</p></header>
            {result.results.map((item, index) => (
              <article key={item.question_id} className={`quiz-result-item ${item.correct ? 'correct' : 'incorrect'}`}>
                <strong>{item.correct ? '回答正确' : '需要复习'} · 第 {index + 1} 题</strong>
                {!item.correct && <p>你的答案：{item.answer || '（未作答）'}<br />参考答案：{item.expected_answer}</p>}
                <p>{item.explanation}</p>
                {item.kind === 'short' && (
                  <div className="regrade-actions">
                    <span>{item.manually_graded ? '已人工改判' : '简答题判分有误？'}</span>
                    <button type="button" className="ghost-btn small" disabled={busy || (item.correct && item.manually_graded)} onClick={() => regrade(item, true)}>判为正确</button>
                    <button type="button" className="ghost-btn small" disabled={busy || (!item.correct && item.manually_graded)} onClick={() => regrade(item, false)}>判为错误</button>
                  </div>
                )}
                {item.source && <blockquote>{item.source.file_name} · {item.source.locator}<br />{item.source.snippet}</blockquote>}
              </article>
            ))}
            <button type="button" className="primary-btn" onClick={() => { setQuiz(null); setResult(null); setAnswers({}); }}>再练一套</button>
          </section>
        )}
      </section>

      <aside className="quiz-history"><h2>练习记录</h2>{attempts.length ? attempts.map((attempt) => (
        <article key={attempt.id} className="attempt-card"><strong>{attempt.score}/{attempt.total} 题正确</strong><span>{new Date(attempt.created_at).toLocaleString()}</span><small>{attempt.results.filter((item) => !item.correct).length} 道错题</small></article>
      )) : <p className="muted">完成第一次练习后，记录会显示在这里。</p>}</aside>
    </div>
  );
}
