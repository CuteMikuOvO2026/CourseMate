import React from 'react';

const LABELS = {
  queued: '等待解析',
  processing: '解析中',
  ready: '已解析',
  failed: '解析失败',
};

export default function StatusBadge({ status }) {
  return (
    <span className={`status-badge status-${status}`}>{LABELS[status] || status}</span>
  );
}
