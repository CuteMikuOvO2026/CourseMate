import React, { useRef, useState } from 'react';

const ACCEPT = '.pdf,.pptx,.docx,.md,.markdown,.txt';

export default function FileDrop({ onFiles, busy }) {
  const inputRef = useRef(null);
  const [dragging, setDragging] = useState(false);

  function pick(files) {
    const list = Array.from(files || []);
    if (list.length) onFiles(list);
  }

  return (
    <div
      className={`dropzone${dragging ? ' dragging' : ''}${busy ? ' busy' : ''}`}
      onClick={() => {
        if (!busy) inputRef.current?.click();
      }}
      onDragOver={(event) => {
        event.preventDefault();
        if (!busy) setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={(event) => {
        event.preventDefault();
        setDragging(false);
        if (!busy) pick(event.dataTransfer.files);
      }}
      role="button"
      tabIndex={0}
      onKeyDown={(event) => {
        if (event.key === 'Enter' || event.key === ' ') inputRef.current?.click();
      }}
    >
      <div className="dropzone-icon">+</div>
      <div className="dropzone-title">
        {busy ? '正在上传…' : '点击或拖拽文件到这里上传'}
      </div>
      <div className="dropzone-hint">
        支持 PDF、PPTX、DOCX、Markdown、TXT，单个文件不超过 50 MB
      </div>
      <input
        ref={inputRef}
        type="file"
        multiple
        accept={ACCEPT}
        hidden
        onChange={(event) => {
          pick(event.target.files);
          event.target.value = '';
        }}
      />
    </div>
  );
}
